"""
Technical indicators from OHLCV (pandas only, no TA-Lib).

Covers trend/momentum, volatility channels, and volume-price tools used by
the Stock technical panel and chat `technicals` intent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _bollinger(close, period=20, num_std=2):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def _atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _keltner(high, low, close, period=20, atr_mult=1.5):
    mid = close.ewm(span=period, adjust=False).mean()
    atr = _atr(high, low, close, period)
    upper = mid + atr_mult * atr
    lower = mid - atr_mult * atr
    return upper, mid, lower


def _obv(close, volume):
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume.fillna(0)).cumsum()


def _vwap_session(df):
    """
    Approximate VWAP over the provided frame (typical for daily bars:
    cumulative typical-price * volume / cumulative volume from the start
    of the series). For true intraday session VWAP use intraday bars.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].fillna(0).clip(lower=0)
    cum_pv = (tp * vol).cumsum()
    cum_v = vol.cumsum().replace(0, np.nan)
    return cum_pv / cum_v


def compute_indicators(df):
    """
    Add trend, momentum, volatility, and volume indicators to a copy of `df`.
    Expects columns: open, high, low, close, volume.
    """
    out = df.copy()
    close, high, low = out["close"], out["high"], out["low"]
    volume = out["volume"]

    # --- Trend MAs ---
    out["sma_20"] = close.rolling(20).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["sma_200"] = close.rolling(200).mean()
    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()
    out["ema_50"] = close.ewm(span=50, adjust=False).mean()
    out["ema_200"] = close.ewm(span=200, adjust=False).mean()

    # --- Momentum ---
    out["rsi_14"] = _rsi(close, 14)
    macd_line, signal_line, hist = _macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist

    # --- Volatility ---
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    out["bb_upper"] = bb_upper
    out["bb_mid"] = bb_mid
    out["bb_lower"] = bb_lower
    out["bb_width"] = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)

    kc_upper, kc_mid, kc_lower = _keltner(high, low, close)
    out["kc_upper"] = kc_upper
    out["kc_mid"] = kc_mid
    out["kc_lower"] = kc_lower

    # Squeeze: Bollinger inside Keltner (TTM-style)
    out["squeeze_on"] = (bb_lower > kc_lower) & (bb_upper < kc_upper)

    out["atr_14"] = _atr(high, low, close, 14)

    # --- Volume-price ---
    out["volume_sma_20"] = volume.rolling(20).mean()
    out["obv"] = _obv(close, volume)
    out["obv_sma_20"] = out["obv"].rolling(20).mean()
    out["vwap"] = _vwap_session(out)

    return out


def support_resistance(df, window=20):
    """Simple rolling-extrema support/resistance over the last `window` bars."""
    recent = df.tail(window)
    return {
        "support": float(recent["low"].min()),
        "resistance": float(recent["high"].max()),
    }


def volume_profile(df, bins=24, lookback=90):
    """
    Lightweight volume profile over the last `lookback` bars.
    Returns POC (point of control), value-area-ish high/low (70% volume),
    and top bins by volume.
    """
    if df is None or df.empty:
        return None
    recent = df.tail(lookback).copy()
    if len(recent) < 10:
        recent = df.copy()
    price_low = float(recent["low"].min())
    price_high = float(recent["high"].max())
    if not np.isfinite(price_low) or not np.isfinite(price_high) or price_high <= price_low:
        return None

    edges = np.linspace(price_low, price_high, bins + 1)
    vol = recent["volume"].fillna(0).astype(float).values
    # distribute each bar's volume into the bin of its typical price
    tp = ((recent["high"] + recent["low"] + recent["close"]) / 3.0).astype(float).values
    hist = np.zeros(bins)
    for p, v in zip(tp, vol):
        if not np.isfinite(p) or v <= 0:
            continue
        idx = int(np.searchsorted(edges, p, side="right") - 1)
        idx = max(0, min(bins - 1, idx))
        hist[idx] += v

    total = hist.sum()
    if total <= 0:
        return None
    poc_i = int(hist.argmax())
    poc = float((edges[poc_i] + edges[poc_i + 1]) / 2)

    # Expand from POC until ~70% of volume is covered (simple VA)
    lo_i = hi_i = poc_i
    covered = hist[poc_i]
    while covered / total < 0.70 and (lo_i > 0 or hi_i < bins - 1):
        left = hist[lo_i - 1] if lo_i > 0 else -1
        right = hist[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left and hi_i < bins - 1:
            hi_i += 1
            covered += hist[hi_i]
        elif lo_i > 0:
            lo_i -= 1
            covered += hist[lo_i]
        else:
            break

    va_low = float(edges[lo_i])
    va_high = float(edges[hi_i + 1])

    top = sorted(
        [
            {
                "price_mid": float((edges[i] + edges[i + 1]) / 2),
                "volume": float(hist[i]),
                "share_pct": float(hist[i] / total * 100),
            }
            for i in range(bins)
            if hist[i] > 0
        ],
        key=lambda x: -x["volume"],
    )[:5]

    return {
        "poc": poc,
        "va_low": va_low,
        "va_high": va_high,
        "price_low": price_low,
        "price_high": price_high,
        "bins": bins,
        "lookback_bars": int(len(recent)),
        "top_nodes": top,
    }


def summarize_latest(ind_df):
    """Latest indicator readings for narrative / API."""
    last = ind_df.iloc[-1]
    prev = ind_df.iloc[-2] if len(ind_df) > 1 else last

    def f(key):
        v = last.get(key)
        return float(v) if pd.notna(v) else None

    def fprev(key):
        v = prev.get(key)
        return float(v) if pd.notna(v) else None

    # Squeeze streak
    squeeze_on = bool(last.get("squeeze_on")) if pd.notna(last.get("squeeze_on")) else False
    streak = 0
    if "squeeze_on" in ind_df.columns:
        for val in ind_df["squeeze_on"].iloc[::-1]:
            if bool(val):
                streak += 1
            else:
                break

    return {
        "close": f("close"),
        "sma_20": f("sma_20"),
        "sma_50": f("sma_50"),
        "sma_200": f("sma_200"),
        "ema_50": f("ema_50"),
        "ema_200": f("ema_200"),
        "rsi_14": f("rsi_14"),
        "macd": f("macd"),
        "macd_signal": f("macd_signal"),
        "macd_hist": f("macd_hist"),
        "macd_hist_prev": fprev("macd_hist"),
        "atr_14": f("atr_14"),
        "bb_upper": f("bb_upper"),
        "bb_lower": f("bb_lower"),
        "bb_mid": f("bb_mid"),
        "bb_width": f("bb_width"),
        "kc_upper": f("kc_upper"),
        "kc_lower": f("kc_lower"),
        "kc_mid": f("kc_mid"),
        "squeeze_on": squeeze_on,
        "squeeze_streak": streak,
        "volume": f("volume"),
        "volume_sma_20": f("volume_sma_20"),
        "obv": f("obv"),
        "obv_sma_20": f("obv_sma_20"),
        "vwap": f("vwap"),
        "sma50_prev": fprev("sma_50"),
        "sma200_prev": fprev("sma_200"),
        "ema50_prev": fprev("ema_50"),
        "ema200_prev": fprev("ema_200"),
    }
