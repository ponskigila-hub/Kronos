"""
All quantitative metrics the screener ranks on, computed as of the most
recent bar in `df` -- trend, momentum, volatility, liquidity, price
structure, risk, and relative strength vs a benchmark.

Reuses assistant.indicators for the pieces the forecaster/chat flow already
compute (RSI, MACD, SMA20/50, Bollinger Bands, ATR) instead of duplicating
them, and adds the extra series a screener specifically needs (SMA100/200,
ROC, Stochastic, ADX, CCI, drawdown, Sharpe/Sortino, beta, relative
strength) on top.

Every metric here is calculated purely from `df`'s own history up to and
including its last row -- nothing here looks past the last available bar,
which is what keeps a future point-in-time/backtest use of this module
free of look-ahead bias (compute_metrics on a truncated df gives you
exactly what a screen run on that date would have seen).
"""
import numpy as np
import pandas as pd

from ..indicators import _rsi, _macd, _bollinger, _atr

TRADING_DAYS_YEAR = 252

HORIZONS = {
    "20d": 20,
    "50d": 50,
    "3m": 63,
    "6m": 126,
    "1y": 252,
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _last(series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    return float(val) if pd.notna(val) else None


def _pct_return(close, days):
    if len(close) <= days:
        return None
    a, b = close.iloc[-1 - days], close.iloc[-1]
    if a == 0 or pd.isna(a) or pd.isna(b):
        return None
    return float((b - a) / a)


def _slope(series, window=10):
    """Simple linear-regression slope over the last `window` points,
    normalized by the series level so it's comparable across price scales."""
    s = series.dropna().tail(window)
    if len(s) < max(3, window // 2):
        return None
    y = s.values
    x = np.arange(len(y))
    try:
        coeffs = np.polyfit(x, y, 1)
    except Exception:
        return None
    level = float(np.mean(y)) or 1.0
    return float(coeffs[0] / level)


def _annualized_vol(returns, window=None):
    r = returns.tail(window) if window else returns
    r = r.dropna()
    if len(r) < 5:
        return None
    return float(r.std() * np.sqrt(TRADING_DAYS_YEAR))


def _stochastic(high, low, close, k_period=14, d_period=3):
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    rng = (highest - lowest).replace(0, np.nan)
    k = (close - lowest) / rng * 100
    d = k.rolling(d_period).mean()
    return k, d


def _adx(high, low, close, period=14):
    """Wilder's ADX (+DI/-DI trend strength, not direction)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    prev_close = close.shift(1)
    true_range = pd.concat([
        (high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx, plus_di, minus_di


def _cci(high, low, close, period=20):
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mean_dev = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * mean_dev.replace(0, np.nan))


def _roc(close, period=10):
    return (close / close.shift(period) - 1) * 100


def _max_drawdown(close):
    cum_max = close.cummax()
    dd = (close - cum_max) / cum_max
    return float(dd.min()) if len(dd) else None


# ---------------------------------------------------------------------------
# category classifiers
# ---------------------------------------------------------------------------
def _classify_trend(price, sma50, sma200, sma50_slope):
    if None in (price, sma50, sma200):
        return "Unknown"
    if price > sma50 > sma200 and (sma50_slope or 0) > 0:
        return "Strong Uptrend"
    if price > sma50 and sma50 > sma200:
        return "Uptrend"
    if price < sma50 < sma200 and (sma50_slope or 0) < 0:
        return "Strong Downtrend"
    if price < sma50 and sma50 < sma200:
        return "Downtrend"
    return "Neutral"


def _classify_volatility(atr_pct, atr_pct_series):
    if atr_pct is None or atr_pct_series is None or atr_pct_series.dropna().empty:
        return "Unknown"
    hist = atr_pct_series.dropna()
    pct_rank = float((hist < atr_pct).mean())
    if pct_rank < 0.25:
        return "Low Volatility"
    if pct_rank < 0.75:
        return "Normal Volatility"
    if pct_rank < 0.90:
        return "High Volatility"
    return "Extreme Volatility"


def _classify_rs(rs_blend):
    if rs_blend is None:
        return "Unknown"
    pct = rs_blend * 100
    if pct > 15:
        return "Strong Outperformance"
    if pct > 5:
        return "Outperformance"
    if pct > -5:
        return "Neutral"
    if pct > -15:
        return "Underperformance"
    return "Strong Underperformance"


def _classify_price_structure(dist_from_high, dist_from_low, rel_volume):
    if dist_from_high is None:
        return "Unknown"
    if dist_from_high >= 0:
        return "At 52-Week High"
    if dist_from_high > -0.03 and (rel_volume or 0) > 1.2:
        return "Near Breakout"
    if dist_from_high > -0.05:
        return "Near 52-Week High"
    if dist_from_low is not None and dist_from_low < 0.10:
        return "Near 52-Week Low"
    if dist_from_high < -0.30:
        return "Deep Drawdown"
    return "Mid-Range"


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def compute_metrics(df, benchmark_df=None):
    """
    df: cleaned OHLCV history (assistant.data_fetcher schema), ascending by
        date, at least a handful of rows.
    benchmark_df: same schema for the benchmark (e.g. SPY), optional --
        relative-strength and beta are omitted (None) without it.

    Returns a flat dict of metric values/classifications. Numeric values
    are plain Python floats (or None where there isn't enough history yet
    for that particular metric) so this is directly JSON-serializable.
    """
    df = df.sort_values("timestamps").reset_index(drop=True)
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    out = {"as_of": df["timestamps"].iloc[-1].strftime("%Y-%m-%d"),
           "price": _last(close), "history_days": len(df)}

    # ---------------------------------------------------------- trend
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma100 = close.rolling(100).mean()
    sma200 = close.rolling(200).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    price = out["price"]
    sma20_v, sma50_v, sma100_v, sma200_v = _last(sma20), _last(sma50), _last(sma100), _last(sma200)
    sma50_slope = _slope(sma50, 10)

    out.update({
        "trend_sma20": sma20_v, "trend_sma50": sma50_v, "trend_sma100": sma100_v, "trend_sma200": sma200_v,
        "trend_ema20": _last(ema20), "trend_ema50": _last(ema50),
        "trend_price_vs_sma20": (price / sma20_v - 1) if price and sma20_v else None,
        "trend_price_vs_sma50": (price / sma50_v - 1) if price and sma50_v else None,
        "trend_price_vs_sma200": (price / sma200_v - 1) if price and sma200_v else None,
        "trend_sma50_vs_sma200": (sma50_v / sma200_v - 1) if sma50_v and sma200_v else None,
        "trend_sma50_slope": sma50_slope,
        "trend_return_20d": _pct_return(close, HORIZONS["20d"]),
        "trend_return_50d": _pct_return(close, HORIZONS["50d"]),
        "trend_return_3m": _pct_return(close, HORIZONS["3m"]),
        "trend_return_6m": _pct_return(close, HORIZONS["6m"]),
        "trend_return_1y": _pct_return(close, HORIZONS["1y"]),
        "trend_regime": _classify_trend(price, sma50_v, sma200_v, sma50_slope),
    })

    # ------------------------------------------------------- momentum
    rsi = _rsi(close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    stoch_k, stoch_d = _stochastic(high, low, close)
    adx, plus_di, minus_di = _adx(high, low, close)
    cci = _cci(high, low, close)
    roc10 = _roc(close, 10)

    macd_hist_v = _last(macd_hist)
    macd_hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) > 1 and pd.notna(macd_hist.iloc[-2]) else None
    momentum_accel = None
    if macd_hist_v is not None and macd_hist_prev is not None:
        momentum_accel = "accelerating" if macd_hist_v > macd_hist_prev else "decelerating"

    out.update({
        "momentum_rsi14": _last(rsi),
        "momentum_macd": _last(macd_line), "momentum_macd_signal": _last(macd_signal),
        "momentum_macd_hist": macd_hist_v, "momentum_macd_bullish": (macd_hist_v or 0) > 0,
        "momentum_roc10": _last(roc10),
        "momentum_stoch_k": _last(stoch_k), "momentum_stoch_d": _last(stoch_d),
        "momentum_adx": _last(adx), "momentum_plus_di": _last(plus_di), "momentum_minus_di": _last(minus_di),
        "momentum_cci": _last(cci),
        "momentum_trend": momentum_accel,
        "momentum_bullish": bool((_last(plus_di) or 0) > (_last(minus_di) or 0)),
    })

    # ------------------------------------------------------ volatility
    atr = _atr(high, low, close, 14)
    atr_pct_series = atr / close
    atr_pct = _last(atr_pct_series)
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
    daily_returns = close.pct_change()

    vol_20 = _annualized_vol(daily_returns, 20)
    vol_60 = _annualized_vol(daily_returns, 60)
    bb_width_recent = float(bb_width.tail(10).mean()) if bb_width.tail(10).notna().any() else None
    bb_width_prior = float(bb_width.tail(40).head(30).mean()) if bb_width.tail(40).notna().any() else None
    contraction = None
    if bb_width_recent is not None and bb_width_prior:
        contraction = "contracting" if bb_width_recent < bb_width_prior * 0.85 else (
            "expanding" if bb_width_recent > bb_width_prior * 1.15 else "stable")

    out.update({
        "volatility_atr14": _last(atr), "volatility_atr_pct": atr_pct,
        "volatility_hist_20d": vol_20, "volatility_hist_60d": vol_60,
        "volatility_bb_width": _last(bb_width),
        "volatility_regime": _classify_volatility(atr_pct, atr_pct_series),
        "volatility_state": contraction,
    })

    # ------------------------------------------------------- liquidity
    dollar_volume = close * volume
    avg_dollar_vol_20 = dollar_volume.rolling(20).mean()
    avg_vol_20 = volume.rolling(20).mean()
    avg_vol_50 = volume.rolling(50).mean()
    avg_vol_20_v, avg_vol_50_v = _last(avg_vol_20), _last(avg_vol_50)
    last_volume = _last(volume)
    rel_volume = (last_volume / avg_vol_20_v) if last_volume and avg_vol_20_v else None

    out.update({
        "liquidity_avg_volume_20d": avg_vol_20_v, "liquidity_avg_volume_50d": avg_vol_50_v,
        "liquidity_avg_dollar_volume_20d": _last(avg_dollar_vol_20),
        "liquidity_relative_volume": rel_volume,
        "liquidity_volume_trend": (avg_vol_20_v / avg_vol_50_v - 1) if avg_vol_20_v and avg_vol_50_v else None,
        "liquidity_volume_spike": bool(rel_volume and rel_volume > 2.0),
    })

    # -------------------------------------------------- price structure
    window_52w = min(len(close), TRADING_DAYS_YEAR)
    recent = df.tail(window_52w)
    high_52w = float(recent["high"].max())
    low_52w = float(recent["low"].min())
    dist_from_high = (price - high_52w) / high_52w if price and high_52w else None
    dist_from_low = (price - low_52w) / low_52w if price and low_52w else None
    max_dd = _max_drawdown(recent["close"])

    out.update({
        "price_52w_high": high_52w, "price_52w_low": low_52w,
        "price_dist_from_52w_high": dist_from_high, "price_dist_from_52w_low": dist_from_low,
        "price_drawdown_from_high": max_dd,
        "price_structure": _classify_price_structure(dist_from_high, dist_from_low, rel_volume),
    })

    # -------------------------------------------------------------- risk
    returns_1y = daily_returns.tail(TRADING_DAYS_YEAR).dropna()
    ann_return = float(returns_1y.mean() * TRADING_DAYS_YEAR) if len(returns_1y) > 20 else None
    ann_vol = _annualized_vol(daily_returns, TRADING_DAYS_YEAR)
    downside = returns_1y[returns_1y < 0]
    downside_vol = float(downside.std() * np.sqrt(TRADING_DAYS_YEAR)) if len(downside) > 5 else None
    sharpe = (ann_return / ann_vol) if ann_return is not None and ann_vol else None
    sortino = (ann_return / downside_vol) if ann_return is not None and downside_vol else None

    beta = None
    if benchmark_df is not None:
        merged = pd.merge(
            df[["timestamps", "close"]].rename(columns={"close": "stock"}),
            benchmark_df[["timestamps", "close"]].rename(columns={"close": "bench"}),
            on="timestamps", how="inner",
        )
        if len(merged) > 30:
            stock_ret = merged["stock"].pct_change().dropna()
            bench_ret = merged["bench"].pct_change().dropna()
            n = min(len(stock_ret), len(bench_ret))
            if n > 30:
                stock_ret, bench_ret = stock_ret.tail(n), bench_ret.tail(n)
                bench_var = float(bench_ret.var())
                if bench_var:
                    beta = float(np.cov(stock_ret.values, bench_ret.values)[0, 1] / bench_var)

    out.update({
        "risk_max_drawdown_1y": _max_drawdown(close.tail(TRADING_DAYS_YEAR)),
        "risk_annualized_return": ann_return, "risk_annualized_vol": ann_vol,
        "risk_downside_vol": downside_vol,
        "risk_sharpe": sharpe, "risk_sortino": sortino, "risk_beta": beta,
    })

    # --------------------------------------------------- relative strength
    if benchmark_df is not None:
        bench_close = benchmark_df.sort_values("timestamps").reset_index(drop=True)["close"]
        rs = {}
        for label, days in HORIZONS.items():
            stock_r = _pct_return(close, days)
            bench_r = _pct_return(bench_close, days)
            rs[label] = (stock_r - bench_r) if stock_r is not None and bench_r is not None else None
        available = [v for v in rs.values() if v is not None]
        rs_blend = float(np.mean(available)) if available else None
        out.update({f"rs_{k}": v for k, v in rs.items()})
        out["rs_blend"] = rs_blend
        out["rs_classification"] = _classify_rs(rs_blend)
    else:
        for label in HORIZONS:
            out[f"rs_{label}"] = None
        out["rs_blend"] = None
        out["rs_classification"] = "Unknown"

    return out
