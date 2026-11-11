"""Convert endpoint forecasts into a non-overlapping, mark-to-market simulation."""
import numpy as np
import pandas as pd


class TradingSimulator:
    def __init__(self, strategy="long_short", threshold=0.0, transaction_cost=0.0005):
        """Assume next-open entry and endpoint-close exit.

        ``transaction_cost`` is a one-way fractional cost per side. The simple
        simulator uses fixed starting notional, does not model borrow/margin,
        market impact, dividends or partial fills, and skips overlapping
        forecast-origin trades rather than pretending all use the same cash.
        """
        if strategy not in ("long_only", "short_only", "long_short"):
            raise ValueError("strategy must be long_only, short_only, or long_short")
        if not np.isfinite(threshold) or threshold < 0:
            raise ValueError("threshold must be a finite non-negative fraction")
        if not np.isfinite(transaction_cost) or transaction_cost < 0 or transaction_cost >= 1:
            raise ValueError("transaction_cost must be in [0, 1)")
        self.strategy = strategy
        self.threshold = float(threshold)
        self.transaction_cost = float(transaction_cost)

    def generate_signals(self, predicted_returns):
        predicted_returns = np.asarray(predicted_returns, dtype=float)
        signals = np.where(predicted_returns > self.threshold, 1,
                    np.where(predicted_returns < -self.threshold, -1, 0))
        if self.strategy == "long_only":
            signals = np.where(signals < 0, 0, signals)
        elif self.strategy == "short_only":
            signals = np.where(signals > 0, 0, signals)
        return signals

    @staticmethod
    def _list_value(value):
        return list(value) if isinstance(value, (list, tuple, np.ndarray, pd.Series)) else None

    def run(self, horizon_df, starting_capital=10000.0, force_signal=None,
            calendar_df=None):
        """Simulate with daily equity marks and one position at a time.

        If forecast origins overlap an already-open trade, the newer trade is
        skipped until the prior trade exits. The same rule applies to the
        forced-signal benchmark, keeping its eligible intervals comparable.
        ``calendar_df`` should be the full OHLCV history used to build the
        forecast rows; it supplies exact market dates, including flat-cash
        dates between evaluated origins.
        """
        if force_signal not in (None, -1, 0, 1):
            raise ValueError("force_signal must be None, -1, 0, or 1")
        if not np.isfinite(starting_capital) or starting_capital <= 0:
            raise ValueError("starting_capital must be positive and finite")
        if horizon_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        rows = horizon_df.sort_values("split_date", kind="stable")
        eval_start = pd.Timestamp(rows["split_date"].min())
        eval_end = pd.Timestamp(rows["date"].max())
        if calendar_df is not None and "timestamps" in calendar_df:
            cal = pd.to_datetime(calendar_df["timestamps"], errors="coerce").dropna().drop_duplicates().sort_values()
            cal = cal[(cal >= eval_start) & (cal <= eval_end)]
            dates = [pd.Timestamp(x) for x in cal.tolist()]
        else:
            dates = list(pd.bdate_range(eval_start, eval_end))
        path_dates = set()
        for _, row in rows.iterrows():
            path = self._list_value(row.get("holding_dates"))
            if path:
                path_dates.update(pd.Timestamp(d) for d in path)
        dates = sorted(set(dates) | path_dates | {eval_start, eval_end})

        marks = {eval_start: float(starting_capital)}
        capital = float(starting_capital)
        last_exit_date = None
        trades = []
        overlap_skipped = 0

        for _, row in rows.iterrows():
            origin_close = float(row.get("prev_actual", np.nan))
            entry_price = float(row.get("entry_price", np.nan))
            exit_price = float(row.get("actual", np.nan))
            predicted = float(row.get("predicted", np.nan))
            entry_date = pd.Timestamp(row.get("entry_date", row["split_date"]))
            exit_date = pd.Timestamp(row["date"])
            if pd.isna(entry_date) or pd.isna(exit_date) or entry_date > exit_date:
                continue
            if not (np.isfinite(origin_close) and origin_close > 0 and
                    np.isfinite(entry_price) and entry_price > 0 and
                    np.isfinite(exit_price) and exit_price > 0 and
                    np.isfinite(predicted) and predicted > 0):
                continue

            predicted_origin_return = predicted / origin_close - 1.0
            predicted_trade_return = predicted / entry_price - 1.0
            signal = int(force_signal if force_signal is not None
                         else self.generate_signals([predicted_trade_return])[0])
            if signal == 0:
                continue
            if last_exit_date is not None and entry_date <= last_exit_date:
                overlap_skipped += 1
                continue
            if capital <= 0:
                break

            raw_dates = self._list_value(row.get("holding_dates"))
            raw_closes = self._list_value(row.get("holding_closes"))
            if raw_dates is not None and raw_closes is not None and len(raw_dates) == len(raw_closes) and len(raw_dates):
                path = [(pd.Timestamp(d), float(c)) for d, c in zip(raw_dates, raw_closes)]
                path_times = [point[0] for point in path]
                if (path[0][0] != entry_date or path_times != sorted(set(path_times)) or
                        path[-1][0] != exit_date or
                        not np.isclose(path[-1][1], exit_price, rtol=1e-6, atol=1e-8)):
                    continue
            else:
                # Compatibility for older saved forecast rows; new walk-forward
                # runs always supply the full holding path.
                path = [(exit_date, exit_price)]
            if any(not np.isfinite(close) or close <= 0 for _, close in path):
                continue

            capital_before = capital
            entry_fee = self.transaction_cost
            entry_equity = capital_before * (1.0 - entry_fee)
            path_equity = entry_equity
            bankrupt = False
            for mark_date, close in path:
                gross_return = signal * (close / entry_price - 1.0)
                if bankrupt or 1.0 + gross_return <= 0:
                    path_equity = 0.0
                    bankrupt = True
                else:
                    path_equity = entry_equity * (1.0 + gross_return)
                if mark_date == exit_date:
                    path_equity *= (1.0 - self.transaction_cost)
                marks[mark_date] = path_equity
            capital = path_equity
            last_exit_date = exit_date
            realized_return = exit_price / entry_price - 1.0
            net_return = capital / capital_before - 1.0
            trades.append({
                "entry_date": entry_date,
                "exit_date": exit_date,
                "direction": "long" if signal == 1 else "short",
                "entry_price": entry_price,
                "exit_price": exit_price,
                "predicted_return": predicted_trade_return,
                "forecast_return_from_origin": predicted_origin_return,
                "realized_return": realized_return,
                "pnl_return": net_return,
                "capital_after": capital,
                "holding_period_days": (exit_date - entry_date).days,
            })

        # Carry cash equity over all no-position bars so daily risk metrics do
        # not mistake a sparse trade-event series for daily observations.
        equity = []
        current = float(starting_capital)
        for date in dates:
            if date in marks:
                current = marks[date]
            equity.append({"date": date, "equity": current})
        trades_df = pd.DataFrame(trades)
        trades_df.attrs["overlap_skipped"] = overlap_skipped
        return trades_df, pd.DataFrame(equity)
