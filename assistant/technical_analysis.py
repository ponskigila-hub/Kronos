"""
Recent price/volume technical read for a ticker.

Uses OHLCV + indicators (RSI, MACD, SMA, volume SMA, S/R). Research only —
not a prediction or trade recommendation.
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


def analyze_technicals(ticker: str, lookback_days: int = 120) -> dict[str, Any]:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker required")

    from .ticker_utils import validate_ticker
    ok, symbol = validate_ticker(ticker)
    if not ok:
        raise ValueError(f"'{ticker}' does not look like a valid ticker.")

    df = data_fetcher.fetch_history(symbol, lookback_days=lookback_days, interval="1d")
    if df is None or df.empty or len(df) < 30:
        raise ValueError(f"Not enough daily history for {symbol} (need ~30+ bars).")

    ind = indicators.compute_indicators(df)
    latest = indicators.summarize_latest(ind)
    sr20 = indicators.support_resistance(df, window=20)
    sr60 = indicators.support_resistance(df, window=min(60, len(df)))

    closes = ind["close"].astype(float)
    volumes = ind["volume"].astype(float)
    last = float(closes.iloc[-1])
    first = float(closes.iloc[0])
    period_ret = (last - first) / first * 100 if first else None

    # Trend: price vs SMA20/50
    sma20, sma50 = latest.get("sma_20"), latest.get("sma_50")
    if sma20 and sma50:
        if last > sma20 > sma50:
            trend = "Primary trend looks **up** (price above rising intermediate averages)."
            trend_key = "up"
        elif last < sma20 < sma50:
            trend = "Primary trend looks **down** (price below intermediate averages)."
            trend_key = "down"
        else:
            trend = "Trend looks **mixed / range-bound** (price and averages are crossed or flat)."
            trend_key = "mixed"
    elif sma20:
        trend_key = "up" if last > sma20 else "down"
        trend = f"Price is {'above' if last > sma20 else 'below'} the 20-day average."
    else:
        trend_key = "mixed"
        trend = "Not enough data to classify the trend cleanly."

    # Momentum RSI / MACD
    rsi = latest.get("rsi_14")
    mom_bits = []
    if rsi is not None:
        if rsi >= 70:
            mom_bits.append(f"RSI(14) **{rsi:.1f}** — elevated / overbought zone.")
        elif rsi <= 30:
            mom_bits.append(f"RSI(14) **{rsi:.1f}** — washed-out / oversold zone.")
        else:
            mom_bits.append(f"RSI(14) **{rsi:.1f}** — mid-range momentum.")
    macd_h, macd_hp = latest.get("macd_hist"), latest.get("macd_hist_prev")
    if macd_h is not None and macd_hp is not None:
        if macd_h > 0 and macd_h > macd_hp:
            mom_bits.append("MACD histogram positive and expanding.")
        elif macd_h > 0:
            mom_bits.append("MACD histogram positive but not expanding.")
        elif macd_h < 0 and macd_h < macd_hp:
            mom_bits.append("MACD histogram negative and deepening.")
        else:
            mom_bits.append("MACD histogram negative / recovering.")

    # Volume
    vol, vol_sma = latest.get("volume"), latest.get("volume_sma_20")
    vol_note = "Volume vs 20-day average unavailable."
    vol_ratio = None
    if vol is not None and vol_sma and vol_sma > 0:
        vol_ratio = vol / vol_sma
        if vol_ratio >= 1.5:
            vol_note = f"Latest volume **{vol_ratio:.1f}×** the 20-day average — elevated participation."
        elif vol_ratio <= 0.7:
            vol_note = f"Latest volume **{vol_ratio:.1f}×** the 20-day average — quiet session."
        else:
            vol_note = f"Latest volume near average (**{vol_ratio:.1f}×** 20-day avg)."

    # Patterns (simple, transparent rules)
    patterns = []
    tail = closes.tail(5)
    if len(tail) >= 5:
        if all(tail.iloc[i] > tail.iloc[i - 1] for i in range(1, 5)):
            patterns.append("Four consecutive higher closes (short bullish sequence).")
        if all(tail.iloc[i] < tail.iloc[i - 1] for i in range(1, 5)):
            patterns.append("Four consecutive lower closes (short bearish sequence).")
    if sma20 and sma50 and len(closes) >= 3:
        prev_c = float(closes.iloc[-3])
        # rough golden/death cross recent
        sma20_s = ind["sma_20"].dropna()
        sma50_s = ind["sma_50"].dropna()
        if len(sma20_s) >= 5 and len(sma50_s) >= 5:
            a, b = float(sma20_s.iloc[-1]), float(sma50_s.iloc[-1])
            a0, b0 = float(sma20_s.iloc[-5]), float(sma50_s.iloc[-5])
            if a0 <= b0 and a > b:
                patterns.append("SMA20 recently crossed above SMA50 (golden-cross style).")
            if a0 >= b0 and a < b:
                patterns.append("SMA20 recently crossed below SMA50 (death-cross style).")
    bb_u, bb_l = latest.get("bb_upper"), latest.get("bb_lower")
    if bb_u and last >= bb_u:
        patterns.append("Close at/above upper Bollinger band — extended vs recent volatility.")
    if bb_l and last <= bb_l:
        patterns.append("Close at/below lower Bollinger band — depressed vs recent volatility.")
    if not patterns:
        patterns.append("No strong textbook pattern flagged by the simple rule set.")

    # Sample of recent price/volume for transparency
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
        f"_Daily bars, last ~{len(df)} sessions. Not a prediction._",
        "",
        "### Primary trend",
        f"- {trend}",
        f"- Period return (window): **{_fmt_pct(period_ret)}** · Last close **{_fmt(last)}**",
        f"- SMA20 **{_fmt(sma20)}** · SMA50 **{_fmt(sma50)}**",
        "",
        "### Support & resistance (recent)",
        f"- ~20-session range: support **{_fmt(sr20.get('support'))}** / resistance **{_fmt(sr20.get('resistance'))}**",
        f"- ~60-session range: support **{_fmt(sr60.get('support'))}** / resistance **{_fmt(sr60.get('resistance'))}**",
        "",
        "### Momentum",
    ]
    for m in mom_bits:
        lines.append(f"- {m}")
    if not mom_bits:
        lines.append("- Momentum readings unavailable.")
    lines += ["", "### Volume", f"- {vol_note}", "", "### Notable patterns"]
    for p in patterns:
        lines.append(f"- {p}")
    lines += [
        "",
        "### Recent price & volume (last sessions)",
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
        f"- Structure: **{trend_key}** bias on this window, with nearby support near "
        f"**{_fmt(sr20.get('support'))}** and resistance near **{_fmt(sr20.get('resistance'))}**.",
        "- Treat levels as **zones**, not precise lines. Volume confirmation matters on breaks.",
        "- Nothing here is a guaranteed setup — combine with fundamentals, catalysts, and risk limits.",
        "",
        f"_Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}._",
    ]

    return {
        "ticker": symbol,
        "trend": trend_key,
        "trend_text": trend,
        "last": last,
        "period_return_pct": period_ret,
        "sma_20": sma20,
        "sma_50": sma50,
        "rsi_14": rsi,
        "support_20": sr20.get("support"),
        "resistance_20": sr20.get("resistance"),
        "support_60": sr60.get("support"),
        "resistance_60": sr60.get("resistance"),
        "volume_ratio": vol_ratio,
        "patterns": patterns,
        "sample": sample,
        "text": "\n".join(lines),
        "disclaimer": (
            "Technical research synthesis from historical OHLCV — not a prediction "
            "and not a recommendation to buy or sell."
        ),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
