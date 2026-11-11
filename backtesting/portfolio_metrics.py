"""Portfolio performance metrics for daily, mark-to-market equity curves."""
import numpy as np
import pandas as pd


def _returns_from_equity(equity_df):
    if equity_df.empty or len(equity_df) < 2:
        return np.array([])
    ordered = equity_df.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    eq = pd.to_numeric(ordered["equity"], errors="coerce").to_numpy(dtype=float)
    eq = eq[np.isfinite(eq) & (eq >= 0)]
    if len(eq) < 2 or np.any(eq[:-1] <= 0):
        return np.array([])
    return eq[1:] / eq[:-1] - 1.0


def total_return(equity_df, starting_capital=10000.0):
    if equity_df.empty or starting_capital <= 0:
        return 0.0
    return float(equity_df.sort_values("date").drop_duplicates("date", keep="last")["equity"].iloc[-1] / starting_capital - 1.0)


def cagr(equity_df, starting_capital=10000.0):
    if equity_df.empty or len(equity_df) < 2 or starting_capital <= 0:
        return np.nan
    ordered = equity_df.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    n_days = (pd.Timestamp(ordered["date"].iloc[-1]) - pd.Timestamp(ordered["date"].iloc[0])).days
    if n_days <= 0:
        return np.nan
    final = float(ordered["equity"].iloc[-1]) / starting_capital
    if final <= 0:
        return -1.0
    return float(final ** (365.25 / n_days) - 1.0)


def annual_return(equity_df, starting_capital=10000.0):
    return cagr(equity_df, starting_capital)


def annualized_volatility(equity_df, periods_per_year=252):
    returns = _returns_from_equity(equity_df)
    if len(returns) < 2 or periods_per_year <= 0:
        return np.nan
    return float(np.std(returns, ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(equity_df, risk_free=0.0, periods_per_year=252):
    returns = _returns_from_equity(equity_df)
    if len(returns) < 2 or periods_per_year <= 0:
        return np.nan
    rf_period = risk_free / periods_per_year
    excess = returns - rf_period
    sd = np.std(excess, ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return np.nan
    return float(np.mean(excess) / sd * np.sqrt(periods_per_year))


def sortino_ratio(equity_df, risk_free=0.0, periods_per_year=252):
    """Annualized excess return divided by RMS downside deviation vs MAR."""
    returns = _returns_from_equity(equity_df)
    if len(returns) < 2 or periods_per_year <= 0:
        return np.nan
    excess = returns - risk_free / periods_per_year
    downside = np.minimum(excess, 0.0)
    downside_deviation = np.sqrt(np.mean(downside ** 2))
    if not np.isfinite(downside_deviation) or downside_deviation == 0:
        return np.nan
    return float(np.mean(excess) / downside_deviation * np.sqrt(periods_per_year))


def max_drawdown(equity_df, starting_capital=10000.0):
    if equity_df.empty:
        return np.nan
    values = pd.to_numeric(equity_df.sort_values("date", kind="stable")["equity"], errors="coerce")
    values = values[np.isfinite(values)].to_numpy(dtype=float)
    if not len(values):
        return np.nan
    if starting_capital is not None and np.isfinite(starting_capital) and starting_capital > 0:
        values = np.r_[float(starting_capital), values]
    running_max = np.maximum.accumulate(values)
    return float(np.min(values / running_max - 1.0))


def calmar_ratio(equity_df, starting_capital=10000.0):
    annual = annual_return(equity_df, starting_capital)
    drawdown = max_drawdown(equity_df, starting_capital)
    if not np.isfinite(annual) or not np.isfinite(drawdown) or drawdown == 0:
        return np.nan
    return float(annual / abs(drawdown))


def win_rate(trades_df):
    if trades_df.empty:
        return np.nan
    return float((trades_df["pnl_return"] > 0).mean() * 100)


def profit_factor(trades_df):
    if trades_df.empty:
        return np.nan
    gains = trades_df.loc[trades_df["pnl_return"] > 0, "pnl_return"].sum()
    losses = -trades_df.loc[trades_df["pnl_return"] < 0, "pnl_return"].sum()
    return np.nan if losses == 0 else float(gains / losses)


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
    return float(trades_df["holding_period_days"].mean()) if not trades_df.empty else np.nan


def exposure(trades_df, total_periods):
    """Share of evaluated origins that produced an executed position."""
    if not total_periods:
        return np.nan
    return float(len(trades_df) / total_periods * 100)


def recovery_factor(equity_df, starting_capital=10000.0):
    drawdown = max_drawdown(equity_df, starting_capital)
    if not np.isfinite(drawdown) or drawdown == 0:
        return np.nan
    return float(total_return(equity_df, starting_capital) / abs(drawdown))


def ulcer_index(equity_df, starting_capital=10000.0):
    if equity_df.empty:
        return np.nan
    values = pd.to_numeric(equity_df.sort_values("date", kind="stable")["equity"], errors="coerce")
    values = values[np.isfinite(values)].to_numpy(dtype=float)
    if not len(values):
        return np.nan
    if starting_capital is not None and np.isfinite(starting_capital) and starting_capital > 0:
        values = np.r_[float(starting_capital), values]
    running_max = np.maximum.accumulate(values)
    drawdown_pct = (values / running_max - 1.0) * 100.0
    return float(np.sqrt(np.mean(drawdown_pct ** 2)))


def compute_all(trades_df, equity_df, total_periods=None,
                starting_capital=10000.0, periods_per_year=252):
    drawdown = max_drawdown(equity_df, starting_capital)
    annual = annual_return(equity_df, starting_capital)
    avg_gain = average_gain(trades_df)
    avg_loss = average_loss(trades_df)
    return {
        "total_return_pct": total_return(equity_df, starting_capital) * 100.0,
        "cagr_pct": annual * 100.0 if np.isfinite(annual) else np.nan,
        "annual_return_pct": annual * 100.0 if np.isfinite(annual) else np.nan,
        "annualized_volatility_pct": annualized_volatility(equity_df, periods_per_year) * 100.0,
        "sharpe_ratio": sharpe_ratio(equity_df, periods_per_year=periods_per_year),
        "sortino_ratio": sortino_ratio(equity_df, periods_per_year=periods_per_year),
        "calmar_ratio": calmar_ratio(equity_df, starting_capital),
        "max_drawdown_pct": drawdown * 100.0 if np.isfinite(drawdown) else np.nan,
        "win_rate_pct": win_rate(trades_df),
        "profit_factor": profit_factor(trades_df),
        "average_gain_pct": avg_gain * 100.0 if np.isfinite(avg_gain) else np.nan,
        "average_loss_pct": avg_loss * 100.0 if np.isfinite(avg_loss) else np.nan,
        "num_trades": num_trades(trades_df),
        "average_holding_period_days": average_holding_period(trades_df),
        "exposure_pct": exposure(trades_df, total_periods) if total_periods else np.nan,
        "recovery_factor": recovery_factor(equity_df, starting_capital),
        "ulcer_index": ulcer_index(equity_df, starting_capital),
    }
