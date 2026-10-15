"""Convert endpoint forecasts into a simply timed, single-asset paper backtest."""
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
        if strategy not in ("long_only", "short_only", "long_short"):
            raise ValueError("strategy must be long_only, short_only, or long_short")
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
        """Enter next bar's open and exit at the endpoint close.

        The signal is calculated from the endpoint forecast versus the close
        known at the origin. This avoids assuming a fill at that same close.
        This remains simplified: no borrow fee, market impact, stops or
        overlapping positions are modelled.
        """
        if horizon_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        trades = []
        capital = float(starting_capital)
        equity_curve = []

        for _, row in horizon_df.sort_values("split_date").iterrows():
            origin_close = float(row["prev_actual"])
            entry_price = float(row.get("entry_price", origin_close))
            exit_price_actual = float(row["actual"])
            exit_price_predicted = float(row["predicted"])
            if origin_close <= 0 or entry_price <= 0:
                continue
            predicted_return = (exit_price_predicted - origin_close) / origin_close
            signal = int(self.generate_signals([predicted_return])[0])

            if signal == 0:
                equity_curve.append({"date": row["date"], "equity": capital})
                continue

            realized_return = (exit_price_actual - entry_price) / entry_price
            pnl_return = signal * realized_return - 2 * self.transaction_cost
            capital *= (1 + pnl_return)

            entry_date = row.get("entry_date", row["split_date"])
            trades.append({
                "entry_date": entry_date,
                "exit_date": row["date"],
                "direction": "long" if signal == 1 else "short",
                "entry_price": entry_price,
                "exit_price": exit_price_actual,
                "predicted_return": predicted_return,
                "realized_return": realized_return,
                "pnl_return": pnl_return,
                "capital_after": capital,
                "holding_period_days": (row["date"] - entry_date).days,
            })
            equity_curve.append({"date": row["date"], "equity": capital})

        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve).reset_index(drop=True)
        return trades_df, equity_df
