"""
Recent price/volume technical read for a ticker.

Trend (50/200), MACD, RSI, Bollinger/Keltner squeeze, VWAP, OBV, volume profile.
Research only — not a prediction or trade recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import math

from . import data_fetcher, indicators


def _n(v) -> Optional[float]:
    try:
        if v is None:
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _fmt(n: Optional[float], d: int = 2) -> str:
    if n is None:
        return "—"
    return f"{float(n):,.{d}f}"


def _fmt_pct(n: Optional[float]) -> str:
    if n is None:
        return "—"
    return f"{float(n):+.2f}%"


def analyze_technicals(ticker: str, lookback_days: int = 260) -> dict[str, Any]:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker required")

    from .ticker_utils import validate_ticker
    ok, symbol = validate_ticker(ticker)
    if not ok:
        raise ValueError(f"'{ticker}' does not look like a valid ticker.")

    # Need ~200+ bars for SMA200; request extra calendar days
    df = data_fetcher.fetch_history(symbol, lookback_days=max(lookback_days, 320), interval="1d")
    if df is None or df.empty or len(df) < 30:
        raise ValueError(f"Not enough daily history for {symbol} (need ~30+ bars).")

    ind = indicators.compute_indicators(df)
    latest = indicators.summarize_latest(ind)
    sr20 = indicators.support_resistance(df, window=20)
    sr60 = indicators.support_resistance(df, window=min(60, len(df)))
    profile = indicators.volume_profile(df, bins=24, lookback=min(90, len(df)))

    closes = ind["close"].astype(float)
    last = float(closes.iloc[-1])
    first = float(closes.iloc[0])
    period_ret = (last - first) / first * 100 if first else None

    sma20 = latest.get("sma_20")
    sma50 = latest.get("sma_50")
    sma200 = latest.get("sma_200")
    ema50 = latest.get("ema_50")
    ema200 = latest.get("ema_200")

    # --- Primary trend (50 / 200) ---
    trend_bits = []
    trend_key = "mixed"
    if sma50 and sma200:
        if last > sma50 > sma200:
            trend_key = "up"
            trend_bits.append("Price **above** SMA50 and SMA200 — primary trend **bullish** stack.")
        elif last < sma50 < sma200:
            trend_key = "down"
            trend_bits.append("Price **below** SMA50 and SMA200 — primary trend **bearish** stack.")
        else:
            trend_bits.append("Price / SMA50 / SMA200 are **mixed** (possible transition or range).")
        # Crossover detection on last two bars
        s50p, s200p = latest.get("sma50_prev"), latest.get("sma200_prev")
        if s50p is not None and s200p is not None:
            if s50p <= s200p and sma50 > sma200:
                trend_bits.append("**Golden cross** style: SMA50 crossed above SMA200 recently.")
            elif s50p >= s200p and sma50 < sma200:
                trend_bits.append("**Death cross** style: SMA50 crossed below SMA200 recently.")
    elif sma50:
        trend_key = "up" if last > sma50 else "down"
        trend_bits.append(f"Price is {'above' if last > sma50 else 'below'} SMA50 (SMA200 not ready — need longer history).")
    else:
        trend_bits.append("Not enough history to classify the primary trend cleanly.")

    if ema50 and ema200:
        trend_bits.append(
            f"EMA50 **{_fmt(ema50)}** vs EMA200 **{_fmt(ema200)}** "
            f"({'bullish' if ema50 > ema200 else 'bearish'} EMA stack)."
        )
    if sma20 and sma50:
        trend_bits.append(f"Intermediate: SMA20 **{_fmt(sma20)}** / SMA50 **{_fmt(sma50)}**.")

    # --- Momentum ---
    mom_bits = []
    rsi = latest.get("rsi_14")
    if rsi is not None:
        if rsi >= 70:
            mom_bits.append(f"RSI(14) **{rsi:.1f}** — overbought / exhaustion zone (>70).")
        elif rsi <= 30:
            mom_bits.append(f"RSI(14) **{rsi:.1f}** — oversold / washed-out zone (<30).")
        else:
            mom_bits.append(f"RSI(14) **{rsi:.1f}** — mid-range momentum.")
    macd_h, macd_hp = latest.get("macd_hist"), latest.get("macd_hist_prev")
    if macd_h is not None and macd_hp is not None:
        if macd_h > 0 and macd_h > macd_hp:
            mom_bits.append("MACD histogram **positive and expanding** (acceleration up).")
        elif macd_h > 0:
            mom_bits.append("MACD histogram positive but not expanding.")
        elif macd_h < 0 and macd_h < macd_hp:
            mom_bits.append("MACD histogram **negative and deepening** (acceleration down).")
        else:
            mom_bits.append("MACD histogram negative / recovering.")

    # --- Volatility / mean reversion ---
    vol_bits = []
    bb_u, bb_l, bb_w = latest.get("bb_upper"), latest.get("bb_lower"), latest.get("bb_width")
    kc_u, kc_l = latest.get("kc_upper"), latest.get("kc_lower")
    if bb_u and last >= bb_u:
        vol_bits.append("Close at/above **upper Bollinger** — extended vs recent volatility.")
    if bb_l and last <= bb_l:
        vol_bits.append("Close at/below **lower Bollinger** — depressed vs recent volatility.")
    if bb_w is not None:
        # percentile of bb_width vs last 100 bars
        widths = ind["bb_width"].dropna()
        if len(widths) >= 20:
            pct = float((widths.tail(100) <= bb_w).mean() * 100)
            vol_bits.append(f"BB width percentile ≈ **{pct:.0f}%** of recent history.")
    if latest.get("squeeze_on"):
        streak = latest.get("squeeze_streak") or 1
        vol_bits.append(
            f"**Volatility squeeze ON** (Bollinger inside Keltner) for **{streak}** bar(s) — "
            "low vol often precedes a sharper directional break."
        )
    else:
        vol_bits.append("No active BB-inside-Keltner squeeze on the latest bar.")
    if kc_u and kc_l:
        vol_bits.append(f"Keltner channel: **{_fmt(kc_l)}** – **{_fmt(kc_u)}**.")

    # --- Volume-price ---
    vp_bits = []
    vol, vol_sma = latest.get("volume"), latest.get("volume_sma_20")
    vol_ratio = None
    if vol is not None and vol_sma and vol_sma > 0:
        vol_ratio = vol / vol_sma
        if vol_ratio >= 1.5:
            vp_bits.append(f"Volume **{vol_ratio:.1f}×** the 20-day average — elevated participation.")
        elif vol_ratio <= 0.7:
            vp_bits.append(f"Volume **{vol_ratio:.1f}×** average — quiet session.")
        else:
            vp_bits.append(f"Volume near average (**{vol_ratio:.1f}×**).")
    vwap = latest.get("vwap")
    if vwap:
        side = "above" if last >= vwap else "below"
        vp_bits.append(
            f"Price is **{side} cumulative VWAP** (**{_fmt(vwap)}**) — "
            "institutional execution often anchors around VWAP."
        )
    obv, obv_sma = latest.get("obv"), latest.get("obv_sma_20")
    if obv is not None and obv_sma is not None:
        if obv >= obv_sma:
            vp_bits.append("OBV holds **above** its 20-day average — volume flow supportive.")
        else:
            vp_bits.append("OBV **below** its 20-day average — volume flow softer.")
    if profile:
        vp_bits.append(
            f"Volume profile (~{profile['lookback_bars']} bars): **POC {_fmt(profile['poc'])}**, "
            f"value area **{_fmt(profile['va_low'])} – {_fmt(profile['va_high'])}**."
        )
        if profile.get("top_nodes"):
            nodes = ", ".join(
                f"{_fmt(n['price_mid'])} ({n['share_pct']:.0f}%)" for n in profile["top_nodes"][:3]
            )
            vp_bits.append(f"High-volume nodes: {nodes}.")

    # --- Patterns ---
    patterns = []
    tail = closes.tail(5)
    if len(tail) >= 5:
        if all(tail.iloc[i] > tail.iloc[i - 1] for i in range(1, 5)):
            patterns.append("Four consecutive higher closes.")
        if all(tail.iloc[i] < tail.iloc[i - 1] for i in range(1, 5)):
            patterns.append("Four consecutive lower closes.")
    if not patterns:
        patterns.append("No strong short-sequence pattern flagged.")

    sample = []
    tail_n = min(10, len(ind))
    for i in range(-tail_n, 0):
        row = ind.iloc[i]
        ts = row.get("timestamps")
        label = str(ts)[:10] if ts is not None else str(i)
        try:
            if hasattr(ts, "strftime"):
                label = ts.strftime("%Y-%m-%d")
        except Exception:
            pass
        sample.append({
            "date": label,
            "close": _n(row.get("close")),
            "volume": _n(row.get("volume")),
            "high": _n(row.get("high")),
            "low": _n(row.get("low")),
        })

    lines = [
        f"## Technical read — {symbol}",
        "",
        f"_Daily bars (~{len(df)} sessions). Research only — not a prediction._",
        "",
        "### Primary trend (50 / 200)",
    ]
    for b in trend_bits:
        lines.append(f"- {b}")
    lines += [
        f"- Period return (window): **{_fmt_pct(period_ret)}** · Last **{_fmt(last)}**",
        f"- SMA50 **{_fmt(sma50)}** · SMA200 **{_fmt(sma200)}** · EMA200 **{_fmt(ema200)}**",
        "",
        "### Momentum (MACD · RSI)",
    ]
    for b in mom_bits or ["- Momentum readings unavailable."]:
        lines.append(f"- {b}" if not b.startswith("-") else b)
    lines += ["", "### Volatility & mean-reversion (Bollinger · Keltner)"]
    for b in vol_bits or ["- Volatility structure unavailable."]:
        lines.append(f"- {b}" if not str(b).startswith("-") else b)
    lines += [
        "",
        "### Support & resistance",
        f"- ~20-session: support **{_fmt(sr20.get('support'))}** / resistance **{_fmt(sr20.get('resistance'))}**",
        f"- ~60-session: support **{_fmt(sr60.get('support'))}** / resistance **{_fmt(sr60.get('resistance'))}**",
        "",
        "### Volume-price (VWAP · OBV · profile)",
    ]
    for b in vp_bits or ["- Volume-price tools unavailable."]:
        lines.append(f"- {b}" if not str(b).startswith("-") else b)
    lines += ["", "### Notable patterns"]
    for p in patterns:
        lines.append(f"- {p}")
    lines += [
        "",
        "### Recent price & volume",
        "| Date | Close | High | Low | Volume |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in sample:
        lines.append(
            f"| {s['date']} | {_fmt(s['close'])} | {_fmt(s['high'])} | {_fmt(s['low'])} | "
            f"{_fmt(s['volume'], 0)} |"
        )
    lines += [
        "",
        "### What the data suggests",
        f"- Structure bias on this window: **{trend_key}**, with nearby support "
        f"**{_fmt(sr20.get('support'))}** and resistance **{_fmt(sr20.get('resistance'))}**.",
        "- Treat MAs, VWAP, and profile nodes as **zones**. Confirmation on volume still matters.",
        "- Nothing here is a guaranteed setup — size risk independently.",
        "",
        f"_Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}._",
    ]

    return {
        "ticker": symbol,
        "trend": trend_key,
        "last": last,
        "period_return_pct": period_ret,
        "sma_20": sma20,
        "sma_50": sma50,
        "sma_200": sma200,
        "ema_50": ema50,
        "ema_200": ema200,
        "rsi_14": rsi,
        "support_20": sr20.get("support"),
        "resistance_20": sr20.get("resistance"),
        "support_60": sr60.get("support"),
        "resistance_60": sr60.get("resistance"),
        "bb_width": latest.get("bb_width"),
        "squeeze_on": latest.get("squeeze_on"),
        "squeeze_streak": latest.get("squeeze_streak"),
        "vwap": vwap,
        "obv": obv,
        "volume_ratio": vol_ratio,
        "volume_profile": profile,
        "patterns": patterns,
        "sample": sample,
        "text": "\n".join(lines),
        "disclaimer": (
            "Technical research from historical OHLCV — not a prediction and not a "
            "recommendation to buy or sell. VWAP on daily bars is cumulative over the window, "
            "not a pure intraday session VWAP."
        ),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
