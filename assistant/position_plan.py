"""
Long-term / swing position planner.

Suggests an *entry zone* and *sell targets* from price structure, moving
averages, Kronos forecast, and analyst consensus — not intraday ORB signals.

This is a research aid, not financial advice. Nothing places an order.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from . import data_fetcher, fundamentals, indicators, forecaster
from .config import DEFAULT_PRED_LEN
from .ticker_utils import validate_ticker


class PositionPlanError(Exception):
    pass


def _f(x):
    try:
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _round_px(x):
    v = _f(x)
    if v is None:
        return None
    if abs(v) >= 1000:
        return round(v, 1)
    if abs(v) >= 100:
        return round(v, 2)
    return round(v, 4)


def _check(id_, label, status, detail, value=None):
    """status: pass | caution | fail | na"""
    return {
        "id": id_,
        "label": label,
        "status": status,
        "detail": detail,
        "value": value,
    }


def build_fundamental_checklist(ticker: str, fund: dict = None) -> dict:
    """
    Simple long-term quality checklist from public fundamentals.
    Heuristics only — sector norms differ; treat as a prompt, not a grade.
    """
    if fund is None:
        try:
            fund = fundamentals.get_fundamentals(ticker)
        except Exception as e:
            return {
                "items": [],
                "score": None,
                "summary": f"Fundamentals unavailable ({e}).",
                "name": ticker,
            }

    items = []
    pe = _f(fund.get("pe_ratio"))
    fpe = _f(fund.get("forward_pe"))
    peg = _f(fund.get("peg_ratio"))
    rev_g = _f(fund.get("revenue_growth"))
    earn_g = _f(fund.get("earnings_growth"))
    margin = _f(fund.get("profit_margin"))
    op_margin = _f(fund.get("operating_margin"))
    roe = _f(fund.get("roe"))
    dte = _f(fund.get("debt_to_equity"))
    cr = _f(fund.get("current_ratio"))
    fcf = _f(fund.get("free_cashflow"))
    beta = _f(fund.get("beta"))
    mcap = _f(fund.get("market_cap"))

    # Valuation
    if pe is None and fpe is None:
        items.append(_check("valuation", "Valuation (P/E)", "na", "No P/E (ETF, loss-making, or data gap)."))
    else:
        use_pe = fpe if fpe is not None else pe
        label_pe = "forward P/E" if fpe is not None else "trailing P/E"
        if use_pe < 0:
            items.append(_check("valuation", "Valuation (P/E)", "caution", f"Negative {label_pe} ({use_pe:.1f}) — losses or accounting distortion.", use_pe))
        elif use_pe < 25:
            items.append(_check("valuation", "Valuation (P/E)", "pass", f"{label_pe} {use_pe:.1f} is not extreme by broad-market rules of thumb.", use_pe))
        elif use_pe < 40:
            items.append(_check("valuation", "Valuation (P/E)", "caution", f"{label_pe} {use_pe:.1f} is elevated — growth must justify it.", use_pe))
        else:
            items.append(_check("valuation", "Valuation (P/E)", "fail", f"{label_pe} {use_pe:.1f} is very high — priced for perfection.", use_pe))

    if peg is not None and peg > 0:
        if peg < 1.2:
            items.append(_check("peg", "PEG ratio", "pass", f"PEG {peg:.2f} suggests growth is not fully ignored.", peg))
        elif peg < 2.0:
            items.append(_check("peg", "PEG ratio", "caution", f"PEG {peg:.2f} — fair to expensive vs growth.", peg))
        else:
            items.append(_check("peg", "PEG ratio", "fail", f"PEG {peg:.2f} — expensive vs expected growth.", peg))
    else:
        items.append(_check("peg", "PEG ratio", "na", "PEG not available."))

    # Growth
    if rev_g is None:
        items.append(_check("revenue_growth", "Revenue growth", "na", "No revenue growth figure."))
    elif rev_g > 0.08:
        items.append(_check("revenue_growth", "Revenue growth", "pass", f"YoY revenue growth {rev_g*100:.1f}%.", rev_g))
    elif rev_g > 0:
        items.append(_check("revenue_growth", "Revenue growth", "caution", f"Modest YoY revenue growth {rev_g*100:.1f}%.", rev_g))
    else:
        items.append(_check("revenue_growth", "Revenue growth", "fail", f"Revenue declining ({rev_g*100:.1f}% YoY).", rev_g))

    if earn_g is None:
        items.append(_check("earnings_growth", "Earnings growth", "na", "No earnings growth figure."))
    elif earn_g > 0.05:
        items.append(_check("earnings_growth", "Earnings growth", "pass", f"Earnings growth {earn_g*100:.1f}%.", earn_g))
    elif earn_g > -0.05:
        items.append(_check("earnings_growth", "Earnings growth", "caution", f"Flat-ish earnings growth ({earn_g*100:.1f}%).", earn_g))
    else:
        items.append(_check("earnings_growth", "Earnings growth", "fail", f"Earnings shrinking ({earn_g*100:.1f}%).", earn_g))

    # Profitability
    if margin is None:
        items.append(_check("margin", "Profit margin", "na", "No profit margin."))
    elif margin > 0.12:
        items.append(_check("margin", "Profit margin", "pass", f"Net margin {margin*100:.1f}%.", margin))
    elif margin > 0.03:
        items.append(_check("margin", "Profit margin", "caution", f"Thin net margin {margin*100:.1f}%.", margin))
    else:
        items.append(_check("margin", "Profit margin", "fail", f"Very low/negative margin ({margin*100:.1f}%).", margin))

    if roe is None:
        items.append(_check("roe", "Return on equity", "na", "No ROE."))
    elif roe > 0.15:
        items.append(_check("roe", "Return on equity", "pass", f"ROE {roe*100:.1f}%.", roe))
    elif roe > 0.08:
        items.append(_check("roe", "Return on equity", "caution", f"ROE {roe*100:.1f}% is average.", roe))
    else:
        items.append(_check("roe", "Return on equity", "fail", f"Weak ROE ({roe*100:.1f}%).", roe))

    # Balance sheet
    # yfinance debtToEquity is often in percent-like units (e.g. 50 = 50%)
    if dte is None:
        items.append(_check("debt", "Debt / equity", "na", "No debt-to-equity figure."))
    else:
        dte_n = dte / 100.0 if dte > 10 else dte  # normalize common yfinance scale
        if dte_n < 1.0:
            items.append(_check("debt", "Debt / equity", "pass", f"D/E ≈ {dte_n:.2f} — leverage not extreme.", dte))
        elif dte_n < 2.0:
            items.append(_check("debt", "Debt / equity", "caution", f"D/E ≈ {dte_n:.2f} — meaningful leverage.", dte))
        else:
            items.append(_check("debt", "Debt / equity", "fail", f"D/E ≈ {dte_n:.2f} — high leverage.", dte))

    if cr is None:
        items.append(_check("liquidity", "Current ratio", "na", "No current ratio."))
    elif cr >= 1.2:
        items.append(_check("liquidity", "Current ratio", "pass", f"Current ratio {cr:.2f}.", cr))
    elif cr >= 0.9:
        items.append(_check("liquidity", "Current ratio", "caution", f"Current ratio {cr:.2f} is tight.", cr))
    else:
        items.append(_check("liquidity", "Current ratio", "fail", f"Current ratio {cr:.2f} — short-term liquidity risk.", cr))

    if fcf is None:
        items.append(_check("fcf", "Free cash flow", "na", "No FCF figure."))
    elif fcf > 0:
        items.append(_check("fcf", "Free cash flow", "pass", "Positive free cash flow.", fcf))
    else:
        items.append(_check("fcf", "Free cash flow", "fail", "Negative free cash flow.", fcf))

    if beta is None:
        items.append(_check("beta", "Beta (volatility)", "na", "No beta."))
    elif beta < 1.2:
        items.append(_check("beta", "Beta (volatility)", "pass", f"Beta {beta:.2f} — not hyper-volatile vs market.", beta))
    elif beta < 1.6:
        items.append(_check("beta", "Beta (volatility)", "caution", f"Beta {beta:.2f} — swings more than the market.", beta))
    else:
        items.append(_check("beta", "Beta (volatility)", "fail", f"Beta {beta:.2f} — high volatility; size smaller.", beta))

    if mcap is None:
        items.append(_check("size", "Market cap", "na", "No market cap."))
    elif mcap >= 10e9:
        items.append(_check("size", "Market cap", "pass", f"Large/mid liquid name (~${mcap/1e9:.1f}B).", mcap))
    elif mcap >= 2e9:
        items.append(_check("size", "Market cap", "caution", f"Smaller mid-cap (~${mcap/1e9:.1f}B).", mcap))
    else:
        items.append(_check("size", "Market cap", "fail", f"Smaller company (~${mcap/1e9:.2f}B) — liquidity/risk higher.", mcap))

    scored = [i for i in items if i["status"] != "na"]
    points = sum(1 if i["status"] == "pass" else 0.5 if i["status"] == "caution" else 0 for i in scored)
    score = round(100 * points / len(scored)) if scored else None
    n_pass = sum(1 for i in scored if i["status"] == "pass")
    n_fail = sum(1 for i in scored if i["status"] == "fail")
    if score is None:
        summary = "Not enough fundamental data for a score."
    elif score >= 70:
        summary = f"Checklist looks constructive ({n_pass} pass, {n_fail} fail)."
    elif score >= 45:
        summary = f"Mixed fundamentals ({n_pass} pass, {n_fail} fail) — dig deeper before sizing up."
    else:
        summary = f"Weak checklist ({n_pass} pass, {n_fail} fail) — high bar to justify a long."

    return {
        "name": fund.get("name") or ticker,
        "sector": fund.get("sector"),
        "industry": fund.get("industry"),
        "items": items,
        "score": score,
        "summary": summary,
    }


def build_position_plan(
    ticker: str,
    pred_len: int = None,
    lookback_days: int = 400,
    risk_pct: float = 1.0,
    equity: float = 100000.0,
) -> dict:
    """
    Build a multi-horizon position ticket:

      - current price & regime vs SMAs
      - entry zone (pullback band toward support / value)
      - invalidation / protective stop (structure-based)
      - sell targets: T1 Kronos path, T2 analyst mean, T3 analyst high / stretch
      - optional share size for risk_pct of equity to the stop

    pred_len defaults to a longer swing horizon (max of app default and 30).
    """
    ok, symbol = validate_ticker(ticker)
    if not ok:
        raise PositionPlanError(f"'{ticker}' does not look like a valid ticker.")
    ticker = symbol

    if pred_len is None:
        pred_len = max(int(DEFAULT_PRED_LEN), 30)
    pred_len = max(5, min(int(pred_len), 90))

    hist = data_fetcher.fetch_history(ticker, lookback_days=lookback_days)
    if hist is None or len(hist) < 50:
        raise PositionPlanError(f"Not enough history for {ticker}.")

    ind = indicators.compute_indicators(hist)
    last = ind.iloc[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])

    sma20 = _f(last.get("sma_20"))
    sma50 = _f(last.get("sma_50"))
    # SMA200 if enough bars
    sma200 = None
    if len(ind) >= 200:
        sma200 = _f(ind["close"].rolling(200).mean().iloc[-1])
    atr = _f(last.get("atr_14") or last.get("atr"))
    if atr is None and "atr" in ind.columns:
        atr = _f(ind["atr"].iloc[-1])
    # fallback ATR from true range average
    if atr is None or atr <= 0:
        tr = (ind["high"] - ind["low"]).abs()
        atr = float(tr.tail(14).mean()) if len(tr) else close * 0.02

    rsi = _f(last.get("rsi_14") or last.get("rsi"))
    bb_low = _f(last.get("bb_lower") or last.get("bb_low"))
    bb_mid = _f(last.get("bb_mid") or last.get("bb_middle"))
    bb_up = _f(last.get("bb_upper") or last.get("bb_high"))

    # Recent swing low / high (20 and 60 sessions)
    swing_low_20 = float(ind["low"].tail(20).min())
    swing_high_20 = float(ind["high"].tail(20).max())
    swing_low_60 = float(ind["low"].tail(min(60, len(ind))).min())
    swing_high_60 = float(ind["high"].tail(min(60, len(ind))).max())

    # --- Kronos path ---
    fc = forecaster.run_forecast(hist, pred_len=pred_len, n_runs=1)
    pred_close = float(fc["pred_df"]["close"].iloc[-1])
    kronos_pct = (pred_close - close) / close * 100.0
    kronos_trend = (
        "bullish" if kronos_pct > 1.0
        else "bearish" if kronos_pct < -1.0
        else "neutral"
    )
    # Intermediate path points (~1/3 and 2/3 of horizon)
    n = len(fc["pred_df"])
    t1_idx = max(0, n // 3 - 1)
    t2_idx = max(0, (2 * n) // 3 - 1)
    kronos_t1 = float(fc["pred_df"]["close"].iloc[t1_idx])
    kronos_t2 = float(fc["pred_df"]["close"].iloc[t2_idx])

    # --- Analyst ---
    analyst = None
    try:
        analyst = fundamentals.get_analyst_targets(ticker)
    except Exception:
        analyst = None
    target_mean = _f((analyst or {}).get("target_mean") or (analyst or {}).get("targetMeanPrice"))
    target_high = _f((analyst or {}).get("target_high") or (analyst or {}).get("targetHighPrice"))
    target_low = _f((analyst or {}).get("target_low") or (analyst or {}).get("targetLowPrice"))
    num_analysts = (analyst or {}).get("number_of_analysts") or (analyst or {}).get("numberOfAnalystOpinions")

    # --- Earnings proximity ---
    earnings = None
    try:
        earnings = fundamentals.earnings_within_horizon(ticker, pred_len)
    except Exception:
        earnings = None

    # ========== ENTRY ZONE ==========
    # Prefer buying weakness toward value: cluster of SMA50, BB lower, swing lows.
    support_candidates = [x for x in [sma50, sma200, bb_low, swing_low_20, swing_low_60] if x and x < close]
    # If price already under SMA50, use deeper supports
    if not support_candidates:
        support_candidates = [x for x in [swing_low_20, swing_low_60, bb_low, sma50] if x]

    if support_candidates:
        entry_low = min(support_candidates)
        # Entry high: nearer support or mild pullback (max 1 ATR under close, or SMA20)
        near = [x for x in support_candidates if x >= close - 2.5 * atr]
        entry_high = max(near) if near else max(support_candidates)
        # Cap entry_high below last close unless already discounted
        if entry_high > close:
            entry_high = close
        if entry_low > entry_high:
            entry_low, entry_high = entry_high * 0.98, entry_high
    else:
        # Momentum case: no clear discount — zone is "buy near close" with tight band
        entry_high = close
        entry_low = close - 1.0 * atr

    # Ideal limit = midpoint of zone (or SMA50 if inside zone)
    ideal = (entry_low + entry_high) / 2.0
    if sma50 and entry_low <= sma50 <= entry_high:
        ideal = sma50

    # ========== INVALIDATION / STOP ==========
    # Below entry zone and recent structure — about 1 ATR under entry_low or swing
    stop = min(entry_low, swing_low_20) - 0.5 * atr
    if stop >= entry_low:
        stop = entry_low - 0.75 * atr
    if stop <= 0:
        stop = entry_low * 0.92

    # ========== SELL TARGETS ==========
    targets = []
    # T1: nearer of Kronos intermediate or +1R
    r_unit = max(ideal - stop, 0.5 * atr)
    t1_r = ideal + 1.0 * r_unit
    t1_k = max(kronos_t1, kronos_t2) if kronos_pct > 0 else kronos_t1
    t1 = max(t1_r, t1_k) if kronos_pct > 0 else t1_r
    targets.append({
        "id": "T1",
        "label": "First take-profit",
        "price": _round_px(t1),
        "basis": "≈1R from ideal entry and/or early Kronos path",
        "pct_from_ideal": _round_px((t1 - ideal) / ideal * 100) if ideal else None,
    })

    # T2: Kronos horizon close or analyst mean
    t2_candidates = [pred_close]
    if target_mean:
        t2_candidates.append(target_mean)
    t2 = max(t2_candidates) if kronos_pct >= 0 else (target_mean or pred_close)
    if t2 <= t1:
        t2 = max(t1 + 0.5 * r_unit, pred_close)
    targets.append({
        "id": "T2",
        "label": "Primary target",
        "price": _round_px(t2),
        "basis": "Kronos horizon close"
                 + (" and/or analyst mean target" if target_mean else ""),
        "pct_from_ideal": _round_px((t2 - ideal) / ideal * 100) if ideal else None,
    })

    # T3: stretch — analyst high or 2R
    t3 = ideal + 2.0 * r_unit
    if target_high:
        t3 = max(t3, target_high)
    if t3 <= t2:
        t3 = t2 + 0.5 * r_unit
    targets.append({
        "id": "T3",
        "label": "Stretch target",
        "price": _round_px(t3),
        "basis": "≈2R and/or analyst high target",
        "pct_from_ideal": _round_px((t3 - ideal) / ideal * 100) if ideal else None,
    })

    # ========== REGIME / STANCE ==========
    above_50 = sma50 is not None and close >= sma50
    above_200 = sma200 is not None and close >= sma200
    if above_200 and above_50 and kronos_trend == "bullish":
        stance = "constructive"
        stance_note = "Price is above major averages and the model path leans up — pullback entries are favored over chasing."
    elif above_200 and kronos_trend != "bearish":
        stance = "neutral-positive"
        stance_note = "Longer-term trend intact; wait for the entry zone rather than paying extended prices."
    elif not above_200 and kronos_trend == "bearish":
        stance = "defensive"
        stance_note = "Below the long average with a soft model path — smaller size or stand aside until structure improves."
    else:
        stance = "mixed"
        stance_note = "Signals disagree — prefer the lower half of the entry zone and a defined stop."

    # ========== SIZING ==========
    risk_per_share = max(ideal - stop, 1e-6)
    risk_dollars = float(equity) * (float(risk_pct) / 100.0)
    shares = int(risk_dollars // risk_per_share)
    size = {
        "shares": shares,
        "cost_at_ideal": _round_px(shares * ideal),
        "risk_dollars": _round_px(risk_dollars),
        "risk_pct": risk_pct,
        "equity": equity,
        "note": "Size so a stop-out ≈ your risk %. Not a recommendation to buy.",
    }

    # Actionable summary lines
    actions = []
    if close > entry_high * 1.01:
        actions.append(
            f"Price ({_round_px(close)}) is above the entry zone — consider a limit in "
            f"{_round_px(entry_low)}–{_round_px(entry_high)} instead of chasing."
        )
    elif entry_low <= close <= entry_high:
        actions.append(
            f"Price is inside the entry zone. Ideal limit near {_round_px(ideal)}; "
            f"invalidation below {_round_px(stop)}."
        )
    else:
        actions.append(
            f"Price is below the zone (possible breakdown). Wait for reclaim of "
            f"{_round_px(entry_low)} or reassess — do not average blindly."
        )
    actions.append(
        f"Scale out: partial near T1 {_round_px(t1)}, main at T2 {_round_px(t2)}, "
        f"optional runner toward T3 {_round_px(t3)}."
    )
    if earnings:
        actions.append(
            f"Earnings near {earnings} — widen risk awareness; entries into the print are speculative."
        )

    # ========== FUNDAMENTAL CHECKLIST ==========
    fund_data = None
    try:
        fund_data = fundamentals.get_fundamentals(ticker)
    except Exception:
        fund_data = None
    checklist = build_fundamental_checklist(ticker, fund_data)
    if checklist.get("score") is not None and checklist["score"] < 45:
        actions.append(
            f"Fundamental checklist is weak (score {checklist['score']}/100) — "
            "prefer smaller size or skip unless you have a strong thesis."
        )
    elif checklist.get("score") is not None and checklist["score"] >= 70:
        actions.append(
            f"Fundamental checklist looks constructive (score {checklist['score']}/100)."
        )

    return {
        "ticker": ticker,
        "as_of_price": _round_px(close),
        "horizon_days": pred_len,
        "stance": stance,
        "stance_note": stance_note,
        "entry": {
            "zone_low": _round_px(entry_low),
            "zone_high": _round_px(entry_high),
            "ideal": _round_px(ideal),
            "basis": "Cluster of SMA50 / SMA200 / Bollinger lower / recent swing lows",
        },
        "stop": {
            "price": _round_px(stop),
            "basis": "Under entry zone and 20-day swing low, buffered by ATR",
        },
        "targets": targets,
        "kronos": {
            "horizon_close": _round_px(pred_close),
            "pct": round(kronos_pct, 2),
            "trend": kronos_trend,
        },
        "analyst": {
            "mean": _round_px(target_mean),
            "high": _round_px(target_high),
            "low": _round_px(target_low),
            "n": num_analysts,
        },
        "levels": {
            "sma20": _round_px(sma20),
            "sma50": _round_px(sma50),
            "sma200": _round_px(sma200),
            "atr": _round_px(atr),
            "rsi": round(rsi, 1) if rsi is not None else None,
            "swing_low_20": _round_px(swing_low_20),
            "swing_high_20": _round_px(swing_high_20),
            "bb_low": _round_px(bb_low),
            "bb_up": _round_px(bb_up),
        },
        "checklist": checklist,
        "earnings": str(earnings) if earnings else None,
        "size": size,
        "actions": actions,
        "disclaimer": (
            "Research aid only — not financial advice. Combines price structure, "
            "Kronos path, public analyst targets, and a simple fundamental checklist. "
            "No order is placed."
        ),
    }
