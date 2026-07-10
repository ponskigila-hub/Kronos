"""
Technical indicators computed from OHLCV data. Implemented directly with
pandas (no extra dependency like TA-Lib required) so this runs anywhere.
"""
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
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def compute_indicators(df):
    """
    Add RSI, MACD, SMA20/50, EMA12/26, Bollinger Bands and ATR to a copy of
    `df`. Expects columns: open, high, low, close, volume.
    """
    out = df.copy()
    close, high, low = out["close"], out["high"], out["low"]

    out["sma_20"] = close.rolling(20).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()

    out["rsi_14"] = _rsi(close, 14)

    macd_line, signal_line, hist = _macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist

    bb_upper, bb_mid, bb_lower = _bollinger(close)
    out["bb_upper"] = bb_upper
    out["bb_mid"] = bb_mid
    out["bb_lower"] = bb_lower

    out["atr_14"] = _atr(high, low, close, 14)

    out["volume_sma_20"] = out["volume"].rolling(20).mean()

    return out


def support_resistance(df, window=20):
    """Simple rolling-extrema support/resistance estimate over the last
    `window` bars."""
    recent = df.tail(window)
    return {
        "support": float(recent["low"].min()),
        "resistance": float(recent["high"].max()),
    }


def summarize_latest(ind_df):
    """Pull out the most recent indicator readings as plain values, used by
    assistant.explain to build human-readable reasoning."""
    last = ind_df.iloc[-1]
    prev = ind_df.iloc[-2] if len(ind_df) > 1 else last
    return {
        "close": float(last["close"]),
        "sma_20": float(last["sma_20"]) if pd.notna(last["sma_20"]) else None,
        "sma_50": float(last["sma_50"]) if pd.notna(last["sma_50"]) else None,
        "rsi_14": float(last["rsi_14"]) if pd.notna(last["rsi_14"]) else None,
        "macd": float(last["macd"]) if pd.notna(last["macd"]) else None,
        "macd_signal": float(last["macd_signal"]) if pd.notna(last["macd_signal"]) else None,
        "macd_hist": float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else None,
        "macd_hist_prev": float(prev["macd_hist"]) if pd.notna(prev["macd_hist"]) else None,
        "atr_14": float(last["atr_14"]) if pd.notna(last["atr_14"]) else None,
        "bb_upper": float(last["bb_upper"]) if pd.notna(last["bb_upper"]) else None,
        "bb_lower": float(last["bb_lower"]) if pd.notna(last["bb_lower"]) else None,
        "volume": float(last["volume"]),
        "volume_sma_20": float(last["volume_sma_20"]) if pd.notna(last["volume_sma_20"]) else None,
    }
