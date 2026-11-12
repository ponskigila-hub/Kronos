"""Research-desk helpers for Kronos (not order execution)."""
from __future__ import annotations

import threading
import time
from typing import Optional

from .config import RESEARCH_THESIS_PATH
from . import storage

_lock = threading.Lock()

RESEARCH_TEMPLATES = [
    {
        "id": "wall_street",
        "label": "Wall Street breakdown",
        "prompt": (
            "Run the full Wall Street breakdown on {ticker}: business model, "
            "revenue drivers, growth, margins, cash flow, competitive position, "
            "recent earnings, catalysts, biggest risks, and the key numbers "
            "an investor should monitor."
        ),
    },
    {
        "id": "overview",
        "label": "Overview",
        "prompt": (
            "Give me a research overview of {ticker}: recent price trend, "
            "forecast horizon 14 days, key risks, and what the model is uncertain about."
        ),
    },
    {
        "id": "forecast",
        "label": "Forecast",
        "prompt": (
            "Forecast {ticker} for 14 days and explain the path in plain language, "
            "including the uncertainty band."
        ),
    },
    {
        "id": "compare",
        "label": "Compare",
        "prompt": (
            "Compare {ticker} and {ticker2} on recent trend, forecast direction, "
            "and which looks more stretched."
        ),
    },
    {
        "id": "longterm",
        "label": "Long-term",
        "prompt": (
            "Build a longer-horizon research view on {ticker}: entry zone ideas, "
            "invalidation, and fundamental checklist."
        ),
    },
    {
        "id": "news",
        "label": "News & context",
        "prompt": (
            "What is the recent news tone around {ticker} and does it conflict "
            "with the price forecast?"
        ),
    },
    {
        "id": "risk",
        "label": "Risks",
        "prompt": (
            "What are the main risks for {ticker} over the next 2 weeks according to "
            "volatility, earnings, and the forecast band?"
        ),
    },
    {
        "id": "pre_earnings",
        "label": "Pre-earnings",
        "prompt": (
            "Pre-earnings research on {ticker}: days to report if known, why the band "
            "should be wider, and what would falsify a bullish or bearish stance."
        ),
    },
]


def list_templates():
    return list(RESEARCH_TEMPLATES)


def render_template(template_id, ticker="AAPL", ticker2="MSFT"):
    ticker = (ticker or "AAPL").upper()
    ticker2 = (ticker2 or "MSFT").upper()
    for item in RESEARCH_TEMPLATES:
        if item["id"] == template_id:
            return item["prompt"].format(ticker=ticker, ticker2=ticker2)
    return RESEARCH_TEMPLATES[0]["prompt"].format(ticker=ticker, ticker2=ticker2)


def _load_thesis():
    data = storage.load_json(RESEARCH_THESIS_PATH)
    return data if isinstance(data, dict) else {}


def _save_thesis(data):
    storage.save_json(RESEARCH_THESIS_PATH, data)


def get_thesis(user_id, ticker):
    ticker = (ticker or "").upper()
    with _lock:
        return _load_thesis().get(str(user_id), {}).get(ticker)


def list_theses(user_id):
    with _lock:
        user = _load_thesis().get(str(user_id), {})
        rows = []
        for ticker, payload in user.items():
            if isinstance(payload, dict):
                row = dict(payload)
                row["ticker"] = ticker
                rows.append(row)
        rows.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
        return rows


def save_thesis(
    user_id,
    ticker,
    *,
    thesis="",
    risks="",
    horizon_days=14,
    stance="watching",
    tags=None,
):
    ticker = (ticker or "").upper().strip()
    if not ticker:
        raise ValueError("ticker is required")
    stance = (stance or "watching").strip().lower()
    if stance not in ("bullish", "bearish", "neutral", "watching"):
        stance = "watching"
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError):
        horizon_days = 14
    horizon_days = max(1, min(horizon_days, 365))
    payload = {
        "thesis": (thesis or "").strip(),
        "risks": (risks or "").strip(),
        "horizon_days": horizon_days,
        "stance": stance,
        "tags": list(tags or []),
        "updated_at": time.time(),
    }
    with _lock:
        data = _load_thesis()
        data.setdefault(str(user_id), {})[ticker] = payload
        _save_thesis(data)
    out = dict(payload)
    out["ticker"] = ticker
    return out


def delete_thesis(user_id, ticker):
    ticker = (ticker or "").upper()
    with _lock:
        data = _load_thesis()
        user = data.get(str(user_id), {})
        if ticker in user:
            del user[ticker]
            _save_thesis(data)
            return True
        return False


def build_evidence(
    ticker,
    hist_df,
    forecast_result,
    *,
    context_signal=None,
    news_summary=None,
    earnings_date=None,
    lookback_used=None,
):
    last_close = as_of = None
    try:
        last_close = float(hist_df["close"].iloc[-1])
        as_of = str(hist_df["timestamps"].iloc[-1])
    except Exception:
        pass
    pred = forecast_result.get("pred_df")
    forecast_close = horizon = None
    try:
        forecast_close = float(pred["close"].iloc[-1])
        horizon = len(pred)
    except Exception:
        pass
    pct = None
    if last_close and forecast_close is not None and last_close > 0:
        pct = round((forecast_close - last_close) / last_close * 100.0, 2)
    ctx = context_signal.to_dict() if hasattr(context_signal, "to_dict") else (context_signal or {})
    news_label = news_summary.get("label") if isinstance(news_summary, dict) else None
    return {
        "ticker": (ticker or "").upper(),
        "as_of": as_of,
        "last_close": last_close,
        "forecast_close": forecast_close,
        "horizon_days": horizon,
        "expected_return_pct": pct,
        "lookback_used": lookback_used or forecast_result.get("lookback_used"),
        "n_runs": forecast_result.get("n_runs"),
        "uncertainty_pct": forecast_result.get("uncertainty_pct"),
        "market_regime": ctx.get("market_regime"),
        "context_label": ctx.get("label"),
        "context_confidence": ctx.get("confidence"),
        "event_risk": ctx.get("event_risk"),
        "earnings_gate": bool(ctx.get("earnings_gate") or earnings_date),
        "earnings_date": str(earnings_date) if earnings_date else ctx.get("earnings_date"),
        "news_label": news_label,
        "disclaimer": (
            "Research scenario only — not a recommendation to buy or sell. "
            "Bands are model uncertainty estimates, not calibrated probabilities."
        ),
    }


def build_scenarios(forecast_result, last_close=None):
    pred = forecast_result.get("pred_df")
    low = forecast_result.get("low_df")
    high = forecast_result.get("high_df")
    if pred is None or "close" not in getattr(pred, "columns", []):
        return []

    def _end(df):
        try:
            return float(df["close"].iloc[-1])
        except Exception:
            return None

    base = _end(pred)
    lo = _end(low) if low is not None else None
    hi = _end(high) if high is not None else None
    if last_close is None:
        try:
            last_close = float(pred["close"].iloc[0])
        except Exception:
            last_close = None

    def row(name, price, note):
        pct = None
        if price is not None and last_close and last_close > 0:
            pct = round((price - last_close) / last_close * 100.0, 2)
        labels = {"base": "Base path", "low": "Lower band", "high": "Upper band"}
        return {
            "id": name,
            "label": labels.get(name, name),
            "price": None if price is None else round(price, 4),
            "pct_from_last": pct,
            "note": note,
        }

    out = [row("base", base, "Central forecast path (median or single-run path).")]
    if lo is not None:
        out.append(row("low", lo, "Lower edge of the uncertainty band."))
    if hi is not None:
        out.append(row("high", hi, "Upper edge of the uncertainty band."))
    return out


def format_research_card_text(evidence, scenarios):
    bits = []
    if evidence.get("uncertainty_pct") is not None:
        bits.append(
            f"Uncertainty band width ≈ {evidence['uncertainty_pct']:.1f}% of last price."
        )
    if scenarios:
        parts = []
        for s in scenarios:
            if s.get("price") is None:
                continue
            pct = s.get("pct_from_last")
            pct_s = f" ({pct:+.1f}%)" if pct is not None else ""
            parts.append(f"{s['label']}: {s['price']:.2f}{pct_s}")
        if parts:
            bits.append("Scenarios — " + "; ".join(parts) + ".")
    if evidence.get("earnings_gate"):
        bits.append("Earnings gate is active — treat the path as a pre-event scenario only.")
    if evidence.get("market_regime") and evidence["market_regime"] not in (None, "neutral"):
        bits.append(f"Detected regime: {str(evidence['market_regime']).replace('_', ' ')}.")
    bits.append(evidence.get("disclaimer") or "")
    return " ".join(b for b in bits if b)


def compare_tickers(tickers, pred_len=14):
    from . import data_fetcher, indicators, forecaster, news as news_mod, fundamentals
    from .context_signal import build_context_signal

    cleaned = []
    for t in tickers or []:
        s = str(t).strip().upper()
        if s and s not in cleaned:
            cleaned.append(s)
    cleaned = cleaned[:8]
    rows, errors = [], []
    for ticker in cleaned:
        try:
            hist = data_fetcher.fetch_history(ticker)
            ind = indicators.compute_indicators(hist)
            fc = forecaster.run_forecast(hist, pred_len=pred_len, n_runs=1)
            last = float(hist["close"].iloc[-1])
            pred_close = float(fc["pred_df"]["close"].iloc[-1])
            pct = (pred_close - last) / last * 100.0 if last else 0.0
            try:
                _items, news_summary = news_mod.get_news(ticker)
            except Exception:
                news_summary = None
            try:
                earnings = fundamentals.earnings_within_horizon(ticker, pred_len)
            except Exception:
                earnings = None
            try:
                analyst = fundamentals.get_analyst_targets(ticker)
            except Exception:
                analyst = None
            ctx = build_context_signal(
                news_summary=news_summary,
                earnings_date=earnings,
                analyst=analyst,
                pred_len=pred_len,
                kronos_pct_change=pct,
                hist_df=hist,
                ind_df=ind,
            )
            rsi = None
            try:
                if "rsi_14" in ind.columns:
                    rsi = float(ind["rsi_14"].iloc[-1])
            except Exception:
                pass
            rows.append(
                {
                    "ticker": ticker,
                    "last_close": round(last, 4),
                    "forecast_close": round(pred_close, 4),
                    "expected_return_pct": round(pct, 2),
                    "uncertainty_pct": fc.get("uncertainty_pct"),
                    "regime": ctx.market_regime,
                    "context_label": ctx.label,
                    "news_label": (news_summary or {}).get("label"),
                    "earnings_gate": ctx.earnings_gate,
                    "rsi_14": None if rsi is None else round(rsi, 1),
                    "error": None,
                }
            )
        except Exception as e:
            errors.append({"ticker": ticker, "error": str(e)})
            rows.append(
                {
                    "ticker": ticker,
                    "error": str(e),
                    "last_close": None,
                    "forecast_close": None,
                    "expected_return_pct": None,
                    "uncertainty_pct": None,
                    "regime": None,
                    "context_label": None,
                    "news_label": None,
                    "earnings_gate": None,
                    "rsi_14": None,
                }
            )

    def sort_key(r):
        if r.get("error"):
            return (1, 0, 999)
        er = abs(r.get("expected_return_pct") or 0)
        unc = r.get("uncertainty_pct") if r.get("uncertainty_pct") is not None else 999
        return (0, -er, unc)

    return {
        "pred_len": pred_len,
        "rows": sorted(rows, key=sort_key),
        "errors": errors,
        "disclaimer": (
            "Comparison is a research triage table, not a ranking of what to buy. "
            "Uncertainty is a model band width estimate."
        ),
    }
