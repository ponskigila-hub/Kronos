"""Time-ordered walk-forward validation for fixed-horizon forecasts.

Each (origin, horizon) contributes exactly one observation: the forecast at
lead=h compared with the close h bars ahead. Intermediate forecast-path
points are not counted as independent observations.
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
        """Return endpoint-only rows: one per split and horizon.

        ``actual`` and ``predicted`` refer to the close exactly h bars after
        ``split_date``. ``entry_price`` is the next bar's open, the earliest
        assumed executable price after a signal formed at the origin close.
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
                preds = list(preds)
                if len(preds) < h:
                    if verbose:
                        print(f"  horizon {h}: returned {len(preds)} forecasts, expected {h}; skipping")
                    continue
                endpoint = actual_window.iloc[-1]
                first_bar = actual_window.iloc[0]
                origin_close = float(train_df.iloc[-1][price_col])
                results[h].append({
                    "split_date": split_date,
                    "date": endpoint["timestamps"],
                    "horizon": int(h),
                    "lead_time": int(h),
                    "actual": float(endpoint[price_col]),
                    "predicted": float(preds[h - 1]),
                    "prev_actual": origin_close,
                    "actual_return": (float(endpoint[price_col]) / origin_close) - 1.0,
                    "predicted_return": (float(preds[h - 1]) / origin_close) - 1.0,
                    "entry_date": first_bar["timestamps"],
                    "entry_price": float(first_bar.get("open", origin_close)),
                })

        return {h: pd.DataFrame(rows) for h, rows in results.items()}
