"""Time-ordered walk-forward validation for fixed-horizon forecasts.

Each (origin, horizon) contributes exactly one endpoint observation. When a
window cap is used, the latest eligible origins are selected, not the earliest
ones in the available history.
"""
import numpy as np
import pandas as pd


class WalkForwardValidator:
    def __init__(self, window_type="expanding", min_train_size=252,
                 max_train_size=None, step_size=30,
                 horizons=(1, 3, 5, 7, 14, 30), max_windows=None):
        if window_type not in ("expanding", "rolling"):
            raise ValueError("window_type must be 'expanding' or 'rolling'")
        if int(min_train_size) < 2:
            raise ValueError("min_train_size must be at least 2")
        if int(step_size) < 1:
            raise ValueError("step_size must be at least 1")
        if not horizons or any(int(h) < 1 for h in horizons):
            raise ValueError("horizons must contain positive integers")
        if max_windows is not None and int(max_windows) < 1:
            raise ValueError("max_windows must be positive or None")
        if window_type == "rolling" and max_train_size is not None and int(max_train_size) < 2:
            raise ValueError("max_train_size must be at least 2")

        self.window_type = window_type
        self.min_train_size = int(min_train_size)
        self.max_train_size = int(max_train_size or min_train_size)
        self.step_size = int(step_size)
        self.horizons = tuple(sorted(set(int(h) for h in horizons)))
        self.max_windows = int(max_windows) if max_windows is not None else None

    def split_indices(self, n_rows):
        """Yield (train_start, train_end) pairs, with train_end exclusive."""
        max_horizon = max(self.horizons)
        starts = list(range(self.min_train_size, n_rows - max_horizon + 1, self.step_size))
        if self.max_windows is not None and len(starts) > self.max_windows:
            starts = starts[-self.max_windows:]
        for start in starts:
            train_start = 0 if self.window_type == "expanding" else max(0, start - self.max_train_size)
            yield train_start, start

    def run(self, df, predict_fn, price_col="close", verbose=True):
        """Return one row per origin and horizon, with daily bars for the hold.

        ``actual``/``predicted`` are the close exactly h bars after origin.
        The simulated entry is next-bar open. ``holding_dates`` and
        ``holding_closes`` let the portfolio simulator mark positions to market
        between entry and endpoint rather than observing only endpoint risk.
        """
        if "timestamps" not in df.columns or price_col not in df.columns:
            raise ValueError(f"data must contain timestamps and {price_col!r}")
        df = (df.copy().sort_values("timestamps", kind="stable")
              .drop_duplicates("timestamps", keep="last").reset_index(drop=True))
        results = {h: [] for h in self.horizons}
        splits = list(self.split_indices(len(df)))

        for i, (train_start, train_end) in enumerate(splits):
            train_df = df.iloc[train_start:train_end]
            if train_df.empty:
                continue
            split_date = train_df.iloc[-1]["timestamps"]
            if verbose:
                print(f"[walk-forward] window {i+1}/{len(splits)} "
                      f"(train rows {train_start}:{train_end}, as of {split_date.date()})")

            for h in self.horizons:
                if train_end + h > len(df):
                    continue
                actual_window = df.iloc[train_end:train_end + h]
                try:
                    preds = np.asarray(list(predict_fn(train_df, h)), dtype=float).reshape(-1)
                except Exception as e:
                    if verbose:
                        print(f"  horizon {h}: predict_fn failed ({e}); skipping this window")
                    continue
                if len(preds) < h or not np.isfinite(preds[h - 1]) or preds[h - 1] <= 0:
                    if verbose:
                        print(f"  horizon {h}: missing/invalid endpoint forecast; skipping")
                    continue

                endpoint = actual_window.iloc[-1]
                first_bar = actual_window.iloc[0]
                origin_close = float(train_df.iloc[-1][price_col])
                actual_close = float(endpoint[price_col])
                entry_price = float(first_bar.get("open", np.nan))
                if not (np.isfinite(origin_close) and origin_close > 0 and
                        np.isfinite(actual_close) and actual_close > 0 and
                        np.isfinite(entry_price) and entry_price > 0):
                    if verbose:
                        print(f"  horizon {h}: invalid origin/actual/fill price; skipping")
                    continue
                results[h].append({
                    "split_date": split_date,
                    "date": endpoint["timestamps"],
                    "horizon": int(h),
                    "lead_time": int(h),
                    "actual": actual_close,
                    "predicted": float(preds[h - 1]),
                    "prev_actual": origin_close,
                    "actual_return": actual_close / origin_close - 1.0,
                    "predicted_return": float(preds[h - 1]) / origin_close - 1.0,
                    "entry_date": first_bar["timestamps"],
                    "entry_price": entry_price,
                    "holding_dates": actual_window["timestamps"].tolist(),
                    "holding_closes": actual_window[price_col].astype(float).tolist(),
                })
        return {h: pd.DataFrame(rows) for h, rows in results.items()}
