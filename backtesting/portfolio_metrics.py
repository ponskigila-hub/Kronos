"""
Requirement #5: full portfolio performance metric suite, computed from the
trades/equity curve produced by backtesting.trading_simulator.TradingSimulator.
"""
import numpy as np
import pandas as pd


def _returns_from_equity(equity_df):
    if len(equity_df) < 2:
        return np.array([])
    eq = equity_df["equity"].values
    return eq[1:] / eq[:-1] - 1


def total_return(equity_df, starting_capital=10000.0):
    if equity_df.empty:
        return 0.0
    return float(equity_df["equity"].iloc[-1] / starting_capital - 1)


def cagr(equity_df, starting_capital=10000.0):
    if equity_df.empty or len(equity_df) < 2:
        return np.nan
    n_days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
    if n_days <= 0:
        return np.nan
    years = n_days / 365.25
    final = equity_df["equity"].iloc[-1] / starting_capital
    if final <= 0:
        return -1.0
    return float(final ** (1 / years) - 1)


def annual_return(equity_df, starting_capital=10000.0):
    return cagr(equity_df, starting_capital)


def annualized_volatility(equity_df, periods_per_year=12):
    """periods_per_year should roughly match how many trades/periods occur
    per year in the equity curve (e.g. ~12 for 30-day-horizon trades,
    ~252 for daily rebalancing) -- pass the right value for your horizon."""
    rets = _returns_from_equity(equity_df)
    if len(rets) < 2:
        return np.nan
    return float(np.std(rets, ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(equity_df, risk_free=0.0, periods_per_year=12):
    rets = _returns_from_equity(equity_df)
    if len(rets) < 2 or np.std(rets, ddof=1) == 0:
        return np.nan
    excess = rets - risk_free / periods_per_year
    return float(np.mean(excess) / np.std(rets, ddof=1) * np.sqrt(periods_per_year))


def sortino_ratio(equity_df, risk_free=0.0, periods_per_year=12):
    rets = _returns_from_equity(equity_df)
    if len(rets) < 2:
        return np.nan
    downside = rets[rets < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else np.nan
    if not downside_std or np.isnan(downside_std) or downside_std == 0:
        return np.nan
    excess = rets - risk_free / periods_per_year
    return float(np.mean(excess) / downside_std * np.sqrt(periods_per_year))


def max_drawdown(equity_df):
    if equity_df.empty:
        return np.nan
    eq = equity_df["equity"].values
    running_max = np.maximum.accumulate(eq)
    drawdowns = eq / running_max - 1
    return float(drawdowns.min())


def calmar_ratio(equity_df, starting_capital=10000.0):
    ar = annual_return(equity_df, starting_capital)
    mdd = max_drawdown(equity_df)
    if not mdd or np.isnan(mdd) or mdd == 0 or np.isnan(ar):
        return np.nan
    return float(ar / abs(mdd))


def win_rate(trades_df):
    if trades_df.empty:
        return np.nan
    return float((trades_df["pnl_return"] > 0).mean() * 100)


def profit_factor(trades_df):
    if trades_df.empty:
        return np.nan
    gains = trades_df.loc[trades_df["pnl_return"] > 0, "pnl_return"].sum()
    losses = -trades_df.loc[trades_df["pnl_return"] < 0, "pnl_return"].sum()
    if losses == 0:
        return np.nan
    return float(gains / losses)


def average_gain(trades_df):
    if trades_df.empty:
        return np.nan
    winners = trades_df.loc[trades_df["pnl_return"] > 0, "pnl_return"]
    return float(winners.mean()) if len(winners) else np.nan


def average_loss(trades_df):
    if trades_df.empty:
        return np.nan
    losers = trades_df.loc[trades_df["pnl_return"] < 0, "pnl_return"]
    return float(losers.mean()) if len(losers) else np.nan


def num_trades(trades_df):
    return int(len(trades_df))


def average_holding_period(trades_df):
    if trades_df.empty:
        return np.nan
    return float(trades_df["holding_period_days"].mean())


def exposure(trades_df, total_periods):
    """Fraction of walk-forward windows where a position was actually taken
    (vs. HOLD). `total_periods` = number of walk-forward splits evaluated."""
    if not total_periods:
        return np.nan
    return float(len(trades_df) / total_periods * 100)


def recovery_factor(equity_df, starting_capital=10000.0):
    tr = total_return(equity_df, starting_capital)
    mdd = max_drawdown(equity_df)
    if not mdd or np.isnan(mdd) or mdd == 0:
        return np.nan
    return float(tr / abs(mdd))


def ulcer_index(equity_df):
    if equity_df.empty:
        return np.nan
    eq = equity_df["equity"].values
    running_max = np.maximum.accumulate(eq)
    drawdown_pct = (eq / running_max - 1) * 100
    return float(np.sqrt(np.mean(drawdown_pct ** 2)))


def compute_all(trades_df, equity_df, total_periods=None, starting_capital=10000.0, periods_per_year=12):
    return {
        "total_return_pct": total_return(equity_df, starting_capital) * 100,
        "cagr_pct": cagr(equity_df, starting_capital) * 100 if not np.isnan(cagr(equity_df, starting_capital)) else np.nan,
        "annual_return_pct": annual_return(equity_df, starting_capital) * 100,
        "annualized_volatility_pct": annualized_volatility(equity_df, periods_per_year) * 100,
        "sharpe_ratio": sharpe_ratio(equity_df, periods_per_year=periods_per_year),
        "sortino_ratio": sortino_ratio(equity_df, periods_per_year=periods_per_year),
        "calmar_ratio": calmar_ratio(equity_df, starting_capital),
        "max_drawdown_pct": max_drawdown(equity_df) * 100 if not np.isnan(max_drawdown(equity_df)) else np.nan,
        "win_rate_pct": win_rate(trades_df),
        "profit_factor": profit_factor(trades_df),
        "average_gain_pct": average_gain(trades_df) * 100 if not np.isnan(average_gain(trades_df)) else np.nan,
        "average_loss_pct": average_loss(trades_df) * 100 if not np.isnan(average_loss(trades_df)) else np.nan,
        "num_trades": num_trades(trades_df),
        "average_holding_period_days": average_holding_period(trades_df),
        "exposure_pct": exposure(trades_df, total_periods) if total_periods else np.nan,
        "recovery_factor": recovery_factor(equity_df, starting_capital),
        "ulcer_index": ulcer_index(equity_df),
    }
