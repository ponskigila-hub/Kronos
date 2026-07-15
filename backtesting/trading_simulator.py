"""
Requirement #4: turn predictions into trading signals and simulate the P&L.

Simple, transparent, single-asset simulator: one position at a time, full
capital per trade, optional transaction cost, held for the same length as
the forecast horizon (i.e. enter after each walk-forward split, exit at the
end of that horizon). This mirrors how the walk-forward predictions line up
with realized prices, and keeps the simulation honest -- no look-ahead bias.
"""
import numpy as np
import pandas as pd


class TradingSimulator:
    def __init__(self, strategy="long_short", threshold=0.0, transaction_cost=0.0005):
        """
        strategy: "long_only", "short_only", or "long_short"
        threshold: minimum predicted return (fraction, e.g. 0.01 = 1%) to
                   act on -- predictions inside [-threshold, threshold] are HOLD
        transaction_cost: round-trip cost as a fraction of trade value
                           (applied on both entry and exit)
        """
        assert strategy in ("long_only", "short_only", "long_short")
        self.strategy = strategy
        self.threshold = threshold
        self.transaction_cost = transaction_cost

    def generate_signals(self, predicted_returns):
        predicted_returns = np.asarray(predicted_returns, dtype=float)
        signals = np.where(predicted_returns > self.threshold, 1,
                    np.where(predicted_returns < -self.threshold, -1, 0))
        if self.strategy == "long_only":
            signals = np.where(signals < 0, 0, signals)
        elif self.strategy == "short_only":
            signals = np.where(signals > 0, 0, signals)
        return signals

    def run(self, horizon_df, starting_capital=10000.0):
        """
        horizon_df: the per-horizon DataFrame from WalkForwardValidator.run(),
        with one row per (split_date, date) — i.e. one row per predicted day.
        We simulate one trade per walk-forward split: enter at `prev_actual`
        on the split date, exit at the final `actual` of that horizon window.

        Returns (trades_df, equity_df).
        """
        if horizon_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        # One row per split: the last predicted day of each split_date group
        # is the exit point; the first prev_actual is the entry price.
        trades = []
        capital = starting_capital
        equity_curve = [{"date": None, "equity": capital}]

        for split_date, group in horizon_df.groupby("split_date"):
            group = group.sort_values("date")
            entry_price = float(group.iloc[0]["prev_actual"])
            exit_price_actual = float(group.iloc[-1]["actual"])
            exit_price_predicted = float(group.iloc[-1]["predicted"])

            predicted_return = (exit_price_predicted - entry_price) / entry_price
            signal = int(self.generate_signals([predicted_return])[0])

            if signal == 0:
                equity_curve.append({"date": group.iloc[-1]["date"], "equity": capital})
                continue

            realized_return = (exit_price_actual - entry_price) / entry_price
            pnl_return = signal * realized_return - 2 * self.transaction_cost
            capital *= (1 + pnl_return)

            trades.append({
                "entry_date": split_date,
                "exit_date": group.iloc[-1]["date"],
                "direction": "long" if signal == 1 else "short",
                "entry_price": entry_price,
                "exit_price": exit_price_actual,
                "predicted_return": predicted_return,
                "realized_return": realized_return,
                "pnl_return": pnl_return,
                "capital_after": capital,
                "holding_period_days": (group.iloc[-1]["date"] - split_date).days,
            })
            equity_curve.append({"date": group.iloc[-1]["date"], "equity": capital})

        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve).dropna(subset=["date"]).reset_index(drop=True)
        return trades_df, equity_df
