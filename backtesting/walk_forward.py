"""
Requirement #1 + #2: walk-forward validation with expanding or rolling
windows, a configurable step size, and multiple forecast horizons evaluated
in the same pass.
"""
import pandas as pd


class WalkForwardValidator:
    def __init__(self, window_type="expanding", min_train_size=252,
                 max_train_size=None, step_size=30,
                 horizons=(1, 3, 5, 7, 14, 30), max_windows=None):
        """
        window_type: "expanding" (train set grows every step, always starts
                     at index 0) or "rolling" (fixed-size train window that
                     slides forward).
        min_train_size: minimum number of bars before the first split.
        max_train_size: for "rolling" windows, the fixed train window size
                        (defaults to min_train_size if unset).
        step_size: how many bars to advance between walk-forward splits.
        horizons: tuple of forecast horizons (in trading days) to evaluate.
        max_windows: cap the number of walk-forward steps (useful to keep
                     compute-heavy models like Kronos-base tractable during
                     experimentation -- leave None for a full run).
        """
        assert window_type in ("expanding", "rolling")
        self.window_type = window_type
        self.min_train_size = min_train_size
        self.max_train_size = max_train_size or min_train_size
        self.step_size = step_size
        self.horizons = tuple(sorted(horizons))
        self.max_windows = max_windows

    def split_indices(self, n_rows):
        """Yield (train_start, train_end) index pairs. Test data for each
        horizon is simply df[train_end : train_end+horizon]."""
        max_horizon = max(self.horizons)
        start = self.min_train_size
        n_windows = 0
        while start + max_horizon <= n_rows:
            if self.window_type == "expanding":
                train_start = 0
            else:
                train_start = max(0, start - self.max_train_size)
            yield train_start, start
            n_windows += 1
            if self.max_windows and n_windows >= self.max_windows:
                return
            start += self.step_size

    def run(self, df, predict_fn, price_col="close", verbose=True):
        """
        df: full historical DataFrame with a 'timestamps' column plus OHLCV,
            sorted ascending by time.
        predict_fn: callable(train_df, horizon) -> array-like of predicted
                    close prices, length == horizon. Both
                    backtesting.kronos_adapter.make_kronos_predict_fn(...)
                    and every function in backtesting.benchmarks share this
                    signature.

        Returns: {horizon: DataFrame[split_date, date, actual, predicted]}
        """
        df = df.reset_index(drop=True)
        results = {h: [] for h in self.horizons}
        splits = list(self.split_indices(len(df)))

        for i, (train_start, train_end) in enumerate(splits):
            train_df = df.iloc[train_start:train_end]
            split_date = train_df.iloc[-1]["timestamps"]
            if verbose:
                print(f"[walk-forward] window {i+1}/{len(splits)} "
                      f"(train rows {train_start}:{train_end}, as of {split_date.date()})")

            for h in self.horizons:
                if train_end + h > len(df):
                    continue
                actual_window = df.iloc[train_end:train_end + h]
                try:
                    preds = predict_fn(train_df, h)
                except Exception as e:
                    if verbose:
                        print(f"  horizon {h}: predict_fn failed ({e}); skipping this window")
                    continue
                preds = list(preds)[:h]
                for j in range(len(preds)):
                    results[h].append({
                        "split_date": split_date,
                        "date": actual_window.iloc[j]["timestamps"],
                        "actual": float(actual_window.iloc[j][price_col]),
                        "predicted": float(preds[j]),
                        "prev_actual": float(train_df.iloc[-1][price_col]) if j == 0
                                        else float(actual_window.iloc[j - 1][price_col]),
                    })

        return {h: pd.DataFrame(rows) for h, rows in results.items()}
