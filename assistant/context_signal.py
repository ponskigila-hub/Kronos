"""
Market-context signal that blends news sentiment + fundamentals into the
forecast *interpretation* (and optionally the displayed confidence band).

Important: Kronos itself remains a pure OHLCV model. This module does NOT
retrain or feed news tokens into the transformer. Instead it:

  1. Scores recent news, earnings proximity, and analyst target vs price.
  2. Produces a structured signal used by explain.py and core_assistant
     so the user sees an honest "price model + market context" view.
  3. Can widen the confidence band when event risk is high (earnings near,
     very negative news) so the chart reflects elevated uncertainty.

This is the practical way to "integrate" news & fundamentals without
pretending the numerical path already priced them in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ContextSignal:
    """Structured context around a Kronos forecast."""

    # -1.0 (strongly bearish context) .. +1.0 (strongly bullish context)
    score: float = 0.0
    label: str = "neutral"  # bullish | lean bullish | neutral | lean bearish | bearish
    confidence: str = "medium"  # low | medium | high  (how much we trust the context itself)
    event_risk: str = "normal"  # normal | elevated | high
    band_widen_factor: float = 1.0  # multiply confidence-band width by this
    # True when earnings is inside the gate window — UI should show a strong warning
    earnings_gate: bool = False
    earnings_date: Optional[str] = None
    analyst_nudge_applied: bool = False
    notes: list[str] = field(default_factory=list)
    components: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "label": self.label,
            "confidence": self.confidence,
            "event_risk": self.event_risk,
            "band_widen_factor": self.band_widen_factor,
            "earnings_gate": self.earnings_gate,
            "earnings_date": self.earnings_date,
            "analyst_nudge_applied": self.analyst_nudge_applied,
            "notes": list(self.notes),
            "components": dict(self.components),
        }


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def build_context_signal(
    news_summary: Optional[dict] = None,
    earnings_date=None,
    analyst: Optional[dict] = None,
    fundamentals: Optional[dict] = None,
    pred_len: int = 14,
    kronos_pct_change: Optional[float] = None,
) -> ContextSignal:
    """
    Combine available side channels into one ContextSignal.

    Weights (intentional, transparent):
      news sentiment     ~ 0.45
      analyst upside     ~ 0.35
      valuation stretch  ~ 0.20  (soft: high PE alone is not a short signal)
    Earnings proximity does not move the directional score; it raises
    event_risk and widens the band.
    """
    notes: list[str] = []
    components: dict[str, Any] = {}
    parts: list[tuple[float, float]] = []  # (weight, score)

    # --- News ---
    news_score = 0.0
    if news_summary and news_summary.get("label") != "no data":
        avg = float(news_summary.get("avg_score") or 0.0)
        # avg_score from news.py is roughly -1..+1 already (keyword lexicon)
        news_score = _clamp(avg)
        components["news"] = {
            "avg_score": avg,
            "label": news_summary.get("label"),
            "positive": news_summary.get("positive"),
            "negative": news_summary.get("negative"),
            "neutral": news_summary.get("neutral"),
        }
        parts.append((0.45, news_score))
        if news_summary.get("label") == "mostly positive":
            notes.append("Recent headlines lean positive.")
        elif news_summary.get("label") == "mostly negative":
            notes.append("Recent headlines lean negative — sentiment can move price faster than the model expects.")
        else:
            notes.append("News sentiment is mixed / neutral.")
    else:
        components["news"] = {"label": "no data"}
        notes.append("No usable recent headlines for this ticker.")

    # --- Analyst targets ---
    analyst_score = 0.0
    if analyst and analyst.get("target_mean") and analyst.get("current_price"):
        try:
            cur = float(analyst["current_price"])
            tgt = float(analyst["target_mean"])
            if cur > 0:
                upside = (tgt - cur) / cur  # e.g. 0.12 = +12%
                # Map ±25% upside into ±1 score, soft-clip
                analyst_score = _clamp(upside / 0.25)
                components["analyst"] = {
                    "current_price": cur,
                    "target_mean": tgt,
                    "upside_pct": round(upside * 100, 1),
                    "recommendation": analyst.get("recommendation"),
                    "num_analysts": analyst.get("num_analysts"),
                }
                parts.append((0.35, analyst_score))
                rec = (analyst.get("recommendation") or "").replace("_", " ")
                notes.append(
                    f"Analyst mean target implies {upside * 100:+.1f}% vs last price"
                    + (f" (consensus: {rec})" if rec else "")
                    + "."
                )
        except (TypeError, ValueError):
            components["analyst"] = {"label": "unavailable"}
    else:
        components["analyst"] = {"label": "unavailable"}

    # --- Soft valuation context (does not dominate) ---
    if fundamentals:
        pe = fundamentals.get("pe_ratio")
        components["fundamentals_snapshot"] = {
            "pe_ratio": pe,
            "sector": fundamentals.get("sector"),
            "market_cap": fundamentals.get("market_cap"),
        }
        # Extreme PE only nudges score slightly; many growth names run high PE.
        if pe is not None:
            try:
                pe = float(pe)
                if pe > 60:
                    parts.append((0.1, -0.25))
                    notes.append(f"Trailing P/E is elevated ({pe:.0f}×) — valuation leaves less room for disappointment.")
                elif 0 < pe < 12:
                    parts.append((0.1, 0.15))
                    notes.append(f"Trailing P/E is modest ({pe:.1f}×) relative to many peers.")
            except (TypeError, ValueError):
                pass

    # --- Weighted directional score ---
    if parts:
        w_sum = sum(w for w, _ in parts)
        score = sum(w * s for w, s in parts) / w_sum
    else:
        score = 0.0
    score = _clamp(score)

    if score >= 0.35:
        label = "bullish"
    elif score >= 0.12:
        label = "lean bullish"
    elif score <= -0.35:
        label = "bearish"
    elif score <= -0.12:
        label = "lean bearish"
    else:
        label = "neutral"

    # --- Event risk + earnings gate ---
    from .config import FORECAST_EARNINGS_GATE_DAYS
    import datetime as _dt

    event_risk = "normal"
    band_widen = 1.0
    earnings_gate = False
    earnings_date_str = None

    if earnings_date is not None:
        earnings_date_str = str(earnings_date)
        components["earnings_date"] = earnings_date_str
        try:
            if isinstance(earnings_date, _dt.date):
                days_to = (earnings_date - _dt.date.today()).days
            else:
                days_to = None
        except Exception:
            days_to = None
        components["days_to_earnings"] = days_to
        event_risk = "high"
        band_widen = 1.45
        # Gate: inside explicit day window OR already flagged inside horizon
        if days_to is not None and 0 <= days_to <= FORECAST_EARNINGS_GATE_DAYS:
            earnings_gate = True
            notes.append(
                f"⚠ Earnings gate: report expected in ~{days_to} day(s) ({earnings_date}). "
                f"Point forecasts are unreliable across earnings — use as a pre-event scenario only."
            )
        else:
            notes.append(
                f"Earnings expected around {earnings_date} near this forecast window — "
                f"price gaps are common; treat the path as a pre-event scenario only."
            )
            earnings_gate = True  # still gate if earnings_within_horizon returned a date
    elif news_summary and news_summary.get("label") == "mostly negative" and abs(news_score) > 0.25:
        event_risk = "elevated"
        band_widen = 1.2

    # How much we trust the *context* itself
    conf = "medium"
    n_sources = 0
    if components.get("news", {}).get("label") not in (None, "no data"):
        n_sources += 1
    if components.get("analyst", {}).get("target_mean"):
        n_sources += 1
    if n_sources >= 2 and event_risk == "normal":
        conf = "high"
    if event_risk == "high" or n_sources == 0:
        conf = "low"

    # Alignment note: Kronos direction vs context
    if kronos_pct_change is not None:
        k = float(kronos_pct_change)
        aligned = (k > 1 and score > 0.1) or (k < -1 and score < -0.1)
        conflict = (k > 1 and score < -0.15) or (k < -1 and score > 0.15)
        components["kronos_pct_change"] = k
        if aligned:
            notes.append("Price-model direction and news/analyst context roughly agree.")
        elif conflict:
            notes.append(
                "Price-model direction and news/analyst context disagree — "
                "prefer the wider confidence band and wait for confirmation."
            )
            band_widen = max(band_widen, 1.25)

    return ContextSignal(
        score=round(score, 3),
        label=label,
        confidence=conf,
        event_risk=event_risk,
        band_widen_factor=round(band_widen, 2),
        earnings_gate=earnings_gate,
        earnings_date=earnings_date_str,
        notes=notes,
        components=components,
    )


def widen_forecast_bands(forecast_result: dict, factor: float) -> dict:
    """
    Expand low/high close bands around the median path when event risk is high.
    Does not change the central (median) prediction — only uncertainty width.
    """
    if factor is None or factor <= 1.0:
        return forecast_result
    low = forecast_result.get("low_df")
    high = forecast_result.get("high_df")
    pred = forecast_result.get("pred_df")
    if low is None or high is None or pred is None or "close" not in pred.columns:
        return forecast_result

    mid = pred["close"].values.astype(float)
    low_c = low["close"].values.astype(float)
    high_c = high["close"].values.astype(float)
    # Expand symmetrically around median
    new_low = mid - (mid - low_c) * factor
    new_high = mid + (high_c - mid) * factor

    out = dict(forecast_result)
    out["low_df"] = low.copy()
    out["high_df"] = high.copy()
    out["low_df"]["close"] = new_low
    out["high_df"]["close"] = new_high
    out["band_widen_factor"] = factor
    return out


def apply_analyst_nudge(forecast_result: dict, analyst: Optional[dict], alpha: float = None) -> tuple:
    """
    Soft-blend the Kronos close path toward a straight line from last known
    close to the analyst mean target over the horizon.

    Returns (updated_forecast_result, applied: bool).
    alpha=0 disables. Only applied when target_mean and a sensible current
    price exist. OHLC other columns shift by the same close delta.
    """
    from .config import FORECAST_ANALYST_NUDGE
    import numpy as np

    if alpha is None:
        alpha = FORECAST_ANALYST_NUDGE
    if not alpha or alpha <= 0:
        return forecast_result, False
    if not analyst or not analyst.get("target_mean"):
        return forecast_result, False

    pred = forecast_result.get("pred_df")
    if pred is None or "close" not in pred.columns or len(pred) < 1:
        return forecast_result, False

    try:
        target = float(analyst["target_mean"])
        # Prefer last predicted step's "start" = first close after anchor,
        # but the true last market close is better taken from analyst current
        # or from the first row's implied level. Use current_price if present,
        # else the first forecast close as proxy for last close (already anchored).
        if analyst.get("current_price"):
            last_close = float(analyst["current_price"])
        else:
            last_close = float(pred["close"].iloc[0])
        if last_close <= 0 or not np.isfinite(target):
            return forecast_result, False
    except (TypeError, ValueError):
        return forecast_result, False

    alpha = min(0.25, float(alpha))  # hard cap so consensus never dominates
    n = len(pred)
    # Linear path from last_close → target over n steps
    analyst_path = last_close + (target - last_close) * (np.arange(1, n + 1) / n)
    kronos_close = pred["close"].values.astype(float)
    blended = (1.0 - alpha) * kronos_close + alpha * analyst_path
    delta = blended - kronos_close

    out = dict(forecast_result)
    new_pred = pred.copy()
    new_pred["close"] = blended
    for col in ("open", "high", "low"):
        if col in new_pred.columns:
            new_pred[col] = new_pred[col].values.astype(float) + delta
    out["pred_df"] = new_pred

    # Shift mean/bands the same way if present
    for key in ("mean_df", "low_df", "high_df"):
        df = forecast_result.get(key)
        if df is not None and "close" in df.columns and len(df) == n:
            shifted = df.copy()
            shifted["close"] = df["close"].values.astype(float) + delta
            out[key] = shifted

    out["analyst_nudge_alpha"] = alpha
    return out, True


def format_context_block(signal: ContextSignal, beginner: bool = False) -> str:
    """Plain-language paragraph for chat / forecast page."""
    if beginner:
        head = {
            "bullish": "Outside the price chart, the broader backdrop looks constructive.",
            "lean bullish": "Outside the price chart, the broader backdrop leans slightly positive.",
            "neutral": "Outside the price chart, the broader backdrop is mixed.",
            "lean bearish": "Outside the price chart, the broader backdrop leans slightly cautious.",
            "bearish": "Outside the price chart, the broader backdrop looks cautious.",
        }.get(signal.label, "Outside the price chart, context is mixed.")
    else:
        head = (
            f"Market context (news + fundamentals) scores {signal.score:+.2f} "
            f"→ {signal.label} (context confidence: {signal.confidence}, "
            f"event risk: {signal.event_risk})."
        )

    bits = [head]
    bits.extend(signal.notes)
    if signal.analyst_nudge_applied:
        bits.append("A small analyst-target nudge was applied to the displayed path (model still primary).")
    if signal.band_widen_factor > 1.0:
        bits.append(
            f"Confidence band widened ×{signal.band_widen_factor} to reflect elevated uncertainty."
        )
    bits.append(
        "Note: Kronos still forecasts from price history only; news and fundamentals "
        "adjust the interpretation, risk band, and a light path nudge — not the model weights."
    )
    return " ".join(bits)
