"""
Medium/long-horizon research signals for Kronos (not trade signals).

Layers:
  1. Earnings revisions / post-earnings drift cues (PEAD-lite)
  2. Relative valuation multiples vs peers and simple history bands
  3. Transparent single-stage / two-stage DCF sanity range
  4. Macro snapshot (rates, USD, equity benchmark)
  5. News/NLP-lite sentiment from the existing news lexicon

All outputs are research scenarios. Yahoo Finance fields can be missing or lag.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional


def _n(value) -> Optional[float]:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _pct(a, b) -> Optional[float]:
    a, b = _n(a), _n(b)
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100.0


# ---------------------------------------------------------------------------
# Earnings revisions & PEAD-lite
# ---------------------------------------------------------------------------
def _earnings_revision_block(ticker: str) -> dict:
    """Best-effort PEAD / revision cues from yfinance."""
    out = {
        "available": False,
        "last_report": None,
        "surprise_pct": None,
        "beat": None,
        "eps_trend": None,
        "revision_label": "unavailable",
        "pead_bias": "unknown",
        "notes": [],
    }
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        out["notes"].append(f"Could not load earnings fields: {e}")
        return out

    # Earnings history (actual vs estimate)
    surprise_pct = None
    try:
        eh = t.earnings_history
        if eh is not None and len(eh) > 0:
            row = eh.iloc[0]
            # columns vary by yfinance version
            for col in ("surprisePercent", "surprise_pct", "pct_diff"):
                if col in eh.columns:
                    surprise_pct = _n(row.get(col) if hasattr(row, "get") else row[col])
                    break
            if surprise_pct is None:
                act = _n(row.get("epsActual") if hasattr(row, "get") else row.get("actual"))
                est = _n(row.get("epsEstimate") if hasattr(row, "get") else row.get("estimate"))
                if act is not None and est not in (None, 0):
                    surprise_pct = (act - est) / abs(est) * 100.0
            out["last_report"] = {
                "period": str(row.name) if hasattr(row, "name") else None,
                "surprise_pct": None if surprise_pct is None else round(surprise_pct, 2),
            }
            out["surprise_pct"] = None if surprise_pct is None else round(surprise_pct, 2)
            if surprise_pct is not None:
                out["beat"] = surprise_pct > 0
                out["available"] = True
    except Exception:
        pass

    # Analyst EPS trend (current vs 30/60/90d ago) when present
    growth = _n(info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"))
    rev_growth = _n(info.get("revenueGrowth"))
    target_mean = _n(info.get("targetMeanPrice"))
    price = _n(info.get("currentPrice") or info.get("regularMarketPrice"))
    rec = info.get("recommendationKey") or info.get("recommendationMean")

    trend = {
        "earnings_growth": growth,
        "revenue_growth": rev_growth,
        "recommendation": rec,
        "analyst_upside_pct": _pct(target_mean, price),
    }
    out["eps_trend"] = trend

    # Heuristic revision / PEAD bias (transparent, not a model)
    score = 0
    if surprise_pct is not None:
        if surprise_pct >= 5:
            score += 2
            out["notes"].append(f"Last reported EPS surprise ≈ {surprise_pct:+.1f}% (beat).")
        elif surprise_pct <= -5:
            score -= 2
            out["notes"].append(f"Last reported EPS surprise ≈ {surprise_pct:+.1f}% (miss).")
        else:
            out["notes"].append(f"Last reported EPS surprise ≈ {surprise_pct:+.1f}% (near consensus).")
    if growth is not None:
        if growth > 0.1:
            score += 1
        elif growth < -0.05:
            score -= 1
    upside = trend.get("analyst_upside_pct")
    if upside is not None:
        if upside > 10:
            score += 1
        elif upside < -10:
            score -= 1

    if score >= 2:
        out["revision_label"] = "constructive"
        out["pead_bias"] = "positive_drift_bias"
    elif score <= -2:
        out["revision_label"] = "deteriorating"
        out["pead_bias"] = "negative_drift_bias"
    elif out["available"] or growth is not None:
        out["revision_label"] = "mixed"
        out["pead_bias"] = "neutral"
        out["available"] = True
    else:
        out["notes"].append("Not enough earnings-revision fields from the data provider.")

    out["notes"].append(
        "PEAD here is a research heuristic (surprise + growth + analyst upside), "
        "not a formal event-study result."
    )
    return out


# ---------------------------------------------------------------------------
# Relative multiples
# ---------------------------------------------------------------------------
def _relative_multiples(ticker: str, peer_tickers: Optional[list] = None) -> dict:
    from . import valuation as val_mod

    peers = peer_tickers or []
    if not peers:
        # Soft default: empty peers → company-only snapshot
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
        except Exception as e:
            return {"available": False, "error": str(e), "company": {}, "peers": []}

        company = {
            "ticker": ticker.upper(),
            "pe_trailing": _n(info.get("trailingPE")),
            "pe_forward": _n(info.get("forwardPE")),
            "ev_ebitda": _n(info.get("enterpriseToEbitda")),
            "price_to_book": _n(info.get("priceToBook")),
            "price_to_sales": _n(info.get("priceToSalesTrailing12Months")),
            "fcf_yield": None,
            "sector": info.get("sector"),
        }
        fcf = _n(info.get("freeCashflow"))
        mcap = _n(info.get("marketCap"))
        if fcf and mcap and mcap > 0:
            company["fcf_yield"] = round(fcf / mcap * 100.0, 2)
        return {
            "available": True,
            "company": company,
            "peers": [],
            "vs_peers": None,
            "notes": [
                "No peers supplied — showing company multiples only. "
                "Add peers on the Valuation page for relative ranges."
            ],
        }

    try:
        result = val_mod.fetch_relative_valuation(ticker, peers)
        return {
            "available": True,
            "relative_valuation": result,
            "notes": result.get("warnings") or [],
        }
    except Exception as e:
        return {"available": False, "error": str(e), "notes": [str(e)]}


# ---------------------------------------------------------------------------
# Transparent DCF (sanity range, not a bank model)
# ---------------------------------------------------------------------------
def simple_dcf(
    ticker: str,
    *,
    fcf: Optional[float] = None,
    shares: Optional[float] = None,
    growth_years: int = 5,
    growth_rate: Optional[float] = None,
    terminal_growth: float = 0.025,
    wacc: Optional[float] = None,
    net_debt: Optional[float] = None,
) -> dict:
    """Two-stage FCF DCF with explicit assumptions and a sensitivity band."""
    notes = []
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        return {"available": False, "error": str(e), "notes": [str(e)]}

    fcf = _n(fcf) or _n(info.get("freeCashflow"))
    shares = _n(shares) or _n(info.get("sharesOutstanding"))
    price = _n(info.get("currentPrice") or info.get("regularMarketPrice"))
    debt = _n(info.get("totalDebt")) or 0.0
    cash = _n(info.get("totalCash")) or 0.0
    if net_debt is None:
        net_debt = debt - cash

    if growth_rate is None:
        growth_rate = _n(info.get("earningsGrowth")) or _n(info.get("revenueGrowth")) or 0.06
        # Clamp absurd growth prints
        growth_rate = max(-0.05, min(0.25, growth_rate))
        notes.append(f"Growth defaulted from provider fields / 6% floor-cap → {growth_rate:.1%}.")
    if wacc is None:
        beta = _n(info.get("beta")) or 1.0
        # Rough CAPM-ish WACC: rf 4% + beta * 5% ERP, debt ignored for simplicity
        wacc = 0.04 + beta * 0.05
        wacc = max(0.06, min(0.14, wacc))
        notes.append(f"WACC approximated from beta ({beta:.2f}) → {wacc:.1%} (not company-specific CoD).")

    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return {
            "available": False,
            "notes": notes + ["Need positive free cash flow and shares outstanding for DCF."],
            "assumptions": {
                "growth_rate": growth_rate,
                "terminal_growth": terminal_growth,
                "wacc": wacc,
            },
        }

    if terminal_growth >= wacc:
        terminal_growth = max(0.0, wacc - 0.01)
        notes.append("Terminal growth capped below WACC.")

    def _value(g, w, tg):
        pv = 0.0
        cf = fcf
        for yr in range(1, growth_years + 1):
            cf *= 1.0 + g
            pv += cf / ((1.0 + w) ** yr)
        terminal_cf = cf * (1.0 + tg)
        terminal_val = terminal_cf / (w - tg)
        pv += terminal_val / ((1.0 + w) ** growth_years)
        equity = pv - (net_debt or 0.0)
        return equity / shares

    base = _value(growth_rate, wacc, terminal_growth)
    low = _value(max(-0.02, growth_rate - 0.03), wacc + 0.015, max(0.0, terminal_growth - 0.005))
    high = _value(min(0.28, growth_rate + 0.03), max(0.055, wacc - 0.01), min(wacc - 0.005, terminal_growth + 0.005))

    upside = _pct(base, price) if price else None
    return {
        "available": True,
        "per_share": {
            "base": round(base, 2),
            "low": round(min(low, high), 2),
            "high": round(max(low, high), 2),
        },
        "current_price": price,
        "upside_vs_price_pct": None if upside is None else round(upside, 1),
        "assumptions": {
            "fcf": fcf,
            "shares": shares,
            "net_debt": net_debt,
            "growth_years": growth_years,
            "growth_rate": round(growth_rate, 4),
            "terminal_growth": round(terminal_growth, 4),
            "wacc": round(wacc, 4),
        },
        "notes": notes + [
            "DCF is a transparent sanity range, not a bank-grade intrinsic value. "
            "Small changes in WACC/growth move results a lot."
        ],
    }


# ---------------------------------------------------------------------------
# Macro snapshot
# ---------------------------------------------------------------------------
def macro_snapshot() -> dict:
    """Lightweight macro panel via public Yahoo symbols."""
    symbols = {
        "us_10y": "^TNX",       # 10Y yield *10 on Yahoo historically; treat carefully
        "us_equity": "SPY",
        "usd": "DX-Y.NYB",
        "gold": "GC=F",
        "oil": "CL=F",
    }
    rows = {}
    notes = []
    try:
        import yfinance as yf
        data = yf.download(
            list(symbols.values()),
            period="6mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return {"available": False, "rows": {}, "notes": [str(e)]}

    for name, sym in symbols.items():
        try:
            if len(symbols) == 1:
                close = data["Close"].dropna()
            else:
                # Multi-index columns
                if hasattr(data.columns, "levels"):
                    close = data[sym]["Close"].dropna() if sym in data.columns.get_level_values(0) else None
                    if close is None:
                        # alternate orientation
                        close = data["Close"][sym].dropna() if "Close" in data and sym in data["Close"] else None
                else:
                    close = data["Close"].dropna()
            if close is None or len(close) < 25:
                continue
            last = float(close.iloc[-1])
            d1 = float(close.pct_change().iloc[-1]) * 100
            d21 = float(close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) >= 22 else None
            d63 = float(close.iloc[-1] / close.iloc[-64] - 1) * 100 if len(close) >= 64 else None
            rows[name] = {
                "symbol": sym,
                "last": round(last, 4),
                "chg_1d_pct": round(d1, 2),
                "chg_1m_pct": None if d21 is None else round(d21, 2),
                "chg_3m_pct": None if d63 is None else round(d63, 2),
            }
        except Exception:
            continue

    if not rows:
        notes.append("Macro series unavailable from provider right now.")
        return {"available": False, "rows": {}, "notes": notes}

    # Simple regime tags
    tags = []
    eq = rows.get("us_equity")
    if eq and eq.get("chg_1m_pct") is not None:
        tags.append("equity_risk_on" if eq["chg_1m_pct"] > 0 else "equity_soft")
    yld = rows.get("us_10y")
    if yld and yld.get("chg_1m_pct") is not None:
        tags.append("yields_up" if yld["chg_1m_pct"] > 0 else "yields_down")
    notes.append(
        "Macro panel is a desk snapshot (SPY, USD, 10Y proxy, commodities) — "
        "not a full sector-rotation model."
    )
    return {"available": True, "rows": rows, "tags": tags, "notes": notes}


# ---------------------------------------------------------------------------
# Sentiment (reuses news lexicon; FinBERT optional later)
# ---------------------------------------------------------------------------
def sentiment_block(ticker: str) -> dict:
    try:
        from . import news as news_mod
        items, summary = news_mod.get_news(ticker)
    except Exception as e:
        return {"available": False, "notes": [str(e)], "summary": None, "headlines": []}

    headlines = []
    for it in (items or [])[:6]:
        headlines.append({
            "title": it.get("title") or it.get("headline"),
            "publisher": it.get("publisher"),
            "score": it.get("score"),
        })
    return {
        "available": summary is not None,
        "summary": summary,
        "headlines": headlines,
        "notes": [
            "Sentiment is lexicon/NLP-lite over recent headlines (not FinBERT on full transcripts). "
            "Tone can diverge from price."
        ],
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def build_fundamental_insight(
    ticker: str,
    peer_tickers: Optional[list] = None,
    include_macro: bool = True,
) -> dict:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")

    peers = []
    for p in peer_tickers or []:
        s = str(p).strip().upper()
        if s and s != ticker and s not in peers:
            peers.append(s)

    earnings = _earnings_revision_block(ticker)
    relative = _relative_multiples(ticker, peers)
    dcf = simple_dcf(ticker)
    sentiment = sentiment_block(ticker)
    macro = macro_snapshot() if include_macro else {"available": False, "rows": {}, "notes": []}

    # Composite research stance (transparent weights, not a rating agency score)
    score = 0.0
    weights_used = []
    if earnings.get("revision_label") == "constructive":
        score += 1
        weights_used.append("earnings+")
    elif earnings.get("revision_label") == "deteriorating":
        score -= 1
        weights_used.append("earnings-")
    if dcf.get("available") and dcf.get("upside_vs_price_pct") is not None:
        u = dcf["upside_vs_price_pct"]
        if u > 15:
            score += 1
            weights_used.append("dcf+")
        elif u < -15:
            score -= 1
            weights_used.append("dcf-")
    lab = (sentiment.get("summary") or {}).get("label")
    if lab == "mostly positive":
        score += 0.5
        weights_used.append("news+")
    elif lab == "mostly negative":
        score -= 0.5
        weights_used.append("news-")

    if score >= 1.5:
        stance = "fundamentally constructive"
    elif score <= -1.5:
        stance = "fundamentally cautious"
    else:
        stance = "mixed / needs judgment"

    return {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "stance": stance,
        "stance_drivers": weights_used,
        "earnings": earnings,
        "relative": relative,
        "dcf": dcf,
        "sentiment": sentiment,
        "macro": macro,
        "disclaimer": (
            "Research synthesis only — not a recommendation to buy or sell. "
            "DCF and PEAD heuristics are simplified; provider data may be incomplete."
        ),
    }
