"""
Requirement #11: multi-asset support without changing code -- just pass a
different ticker list. BacktestRunner ties every other module together into
one call: fetch data -> walk-forward Kronos + benchmarks -> metrics ->
trading simulation -> portfolio metrics -> residual analysis -> regime
splits -> plots -> a comparison report, per asset.
"""
import json
import os

import pandas as pd

from . import metrics, portfolio_metrics, residual_analysis, regimes, visualization
from .benchmarks import get_benchmark_suite
from .data_loaders import YahooFinanceLoader
from .kronos_adapter import make_kronos_predict_fn
from .trading_simulator import TradingSimulator
from .walk_forward import WalkForwardValidator


class BacktestRunner:
    def __init__(self, tickers, horizons=(1, 3, 5, 7, 14, 30),
                 window_type="expanding", min_train_size=252, step_size=30,
                 max_windows=None, data_loader=None, output_dir="backtest_results",
                 include_benchmarks=True, kronos_params=None,
                 trading_strategy="long_short", trading_threshold=0.0,
                 starting_capital=10000.0):
        self.tickers = tickers if isinstance(tickers, (list, tuple)) else [tickers]
        self.horizons = tuple(horizons)
        self.validator = WalkForwardValidator(
            window_type=window_type, min_train_size=min_train_size,
            step_size=step_size, horizons=self.horizons, max_windows=max_windows,
        )
        self.data_loader = data_loader or YahooFinanceLoader()
        self.output_dir = output_dir
        self.include_benchmarks = include_benchmarks
        self.kronos_params = kronos_params or {}
        self.simulator = TradingSimulator(strategy=trading_strategy, threshold=trading_threshold)
        self.starting_capital = starting_capital
        os.makedirs(self.output_dir, exist_ok=True)

    def run(self):
        summary = {}
        for ticker in self.tickers:
            print(f"\n{'='*60}\nBacktesting {ticker}\n{'='*60}")
            summary[ticker] = self._run_single(ticker)
        self._save_comparison_table(summary)
        return summary

    def _run_single(self, ticker):
        asset_dir = os.path.join(self.output_dir, ticker.replace("/", "_"))
        os.makedirs(asset_dir, exist_ok=True)

        df = self.data_loader.load(ticker, lookback_days=None) if not hasattr(self.data_loader, "load") \
            else self.data_loader.load(ticker)

        models = {"Kronos": make_kronos_predict_fn(**self.kronos_params)}
        if self.include_benchmarks:
            models.update(get_benchmark_suite())

        results = {}
        for model_name, predict_fn in models.items():
            print(f"\n-- Running walk-forward for {model_name} on {ticker} --")
            horizon_results = self.validator.run(df, predict_fn)
            results[model_name] = horizon_results

        # ------------------------------------------------------------
        # Metrics per model per horizon
        # ------------------------------------------------------------
        metrics_table = []
        for model_name, horizon_results in results.items():
            for h, hdf in horizon_results.items():
                if hdf.empty:
                    continue
                m = metrics.compute_all_metrics(hdf)
                m.update({"model": model_name, "horizon": h})
                metrics_table.append(m)
        metrics_df = pd.DataFrame(metrics_table)
        metrics_df.to_csv(os.path.join(asset_dir, "metrics_by_model_horizon.csv"), index=False)

        # ------------------------------------------------------------
        # Trading simulation + portfolio metrics (Kronos only, per horizon)
        # ------------------------------------------------------------
        portfolio_table = []
        kronos_results = results["Kronos"]
        for h, hdf in kronos_results.items():
            if hdf.empty:
                continue
            trades_df, equity_df = self.simulator.run(hdf, self.starting_capital)
            n_splits = hdf["split_date"].nunique()
            periods_per_year = max(1, round(252 / max(h, 1)))
            pm = portfolio_metrics.compute_all(
                trades_df, equity_df, total_periods=n_splits,
                starting_capital=self.starting_capital, periods_per_year=periods_per_year,
            )
            pm["horizon"] = h
            portfolio_table.append(pm)

            if not equity_df.empty:
                visualization.plot_equity_curve(
                    equity_df, f"{ticker} -- Equity Curve (horizon={h}d)",
                    os.path.join(asset_dir, f"equity_h{h}.png"), self.starting_capital)
                visualization.plot_drawdown(
                    equity_df, f"{ticker} -- Drawdown (horizon={h}d)",
                    os.path.join(asset_dir, f"drawdown_h{h}.png"))
                visualization.plot_monthly_returns_heatmap(
                    equity_df, f"{ticker} -- Monthly Returns (horizon={h}d)",
                    os.path.join(asset_dir, f"monthly_returns_h{h}.png"))

        portfolio_df = pd.DataFrame(portfolio_table)
        portfolio_df.to_csv(os.path.join(asset_dir, "portfolio_metrics_by_horizon.csv"), index=False)

        # ------------------------------------------------------------
        # Diagnostics + plots for Kronos specifically
        # ------------------------------------------------------------
        residuals_table = []
        kronos_metrics_by_horizon = {}
        for h, hdf in kronos_results.items():
            if hdf.empty:
                continue
            kronos_metrics_by_horizon[h] = metrics.compute_all_metrics(hdf)
            res = residual_analysis.analyze_residuals(hdf)
            res["horizon"] = h
            residuals_table.append(res)

            visualization.plot_actual_vs_predicted(
                hdf, f"{ticker} -- Actual vs Predicted (horizon={h}d)",
                os.path.join(asset_dir, f"actual_vs_pred_h{h}.png"))
            visualization.plot_prediction_error(
                hdf, f"{ticker} -- Prediction Error (horizon={h}d)",
                os.path.join(asset_dir, f"pred_error_h{h}.png"))
            visualization.plot_residual_distribution(
                hdf, f"{ticker} -- Residual Distribution (horizon={h}d)",
                os.path.join(asset_dir, f"residual_dist_h{h}.png"))
            visualization.plot_qq(
                hdf, f"{ticker} -- QQ Plot (horizon={h}d)",
                os.path.join(asset_dir, f"qq_h{h}.png"))
            visualization.plot_residual_autocorrelation(
                hdf, f"{ticker} -- Residual Autocorrelation (horizon={h}d)",
                os.path.join(asset_dir, f"residual_acf_h{h}.png"))
            visualization.plot_direction_confusion_matrix(
                hdf, f"{ticker} -- Direction Confusion Matrix (horizon={h}d)",
                os.path.join(asset_dir, f"direction_confusion_h{h}.png"))

            if len(hdf) >= 10:
                visualization.plot_rolling_metric(
                    hdf, lambda d: metrics.mae(d["actual"], d["predicted"]),
                    window=min(10, len(hdf)),
                    title=f"{ticker} -- Rolling MAE (horizon={h}d)", ylabel="MAE",
                    save_path=os.path.join(asset_dir, f"rolling_mae_h{h}.png"))
                visualization.plot_rolling_metric(
                    hdf, lambda d: metrics.direction_accuracy(d["actual"], d["predicted"], d["prev_actual"]),
                    window=min(10, len(hdf)),
                    title=f"{ticker} -- Rolling Direction Accuracy (horizon={h}d)", ylabel="% correct",
                    save_path=os.path.join(asset_dir, f"rolling_direction_acc_h{h}.png"))

        pd.DataFrame(residuals_table).to_csv(os.path.join(asset_dir, "residual_diagnostics.csv"), index=False)

        if kronos_metrics_by_horizon:
            for metric_name in ["rmse", "mae", "direction_accuracy"]:
                visualization.plot_horizon_comparison(
                    kronos_metrics_by_horizon, metric_name,
                    f"{ticker} -- {metric_name} vs Forecast Horizon",
                    os.path.join(asset_dir, f"horizon_comparison_{metric_name}.png"))

        # ------------------------------------------------------------
        # Market regime split (using the longest horizon available)
        # ------------------------------------------------------------
        regime_df = regimes.classify_regimes(df)
        main_horizon = max(self.horizons)
        if not kronos_results.get(main_horizon, pd.DataFrame()).empty:
            regime_groups = regimes.split_by_regime(kronos_results[main_horizon], regime_df, "trend_regime")
            regime_metrics = {label: metrics.compute_all_metrics(g) for label, g in regime_groups.items() if len(g)}
            with open(os.path.join(asset_dir, "regime_metrics.json"), "w") as f:
                json.dump(regime_metrics, f, indent=2, default=str)
        else:
            regime_metrics = {}

        return {
            "metrics_df": metrics_df,
            "portfolio_df": portfolio_df,
            "regime_metrics": regime_metrics,
            "asset_dir": asset_dir,
        }

    def _save_comparison_table(self, summary):
        rows = []
        for ticker, result in summary.items():
            mdf = result["metrics_df"]
            if mdf.empty:
                continue
            best_per_horizon = mdf.loc[mdf.groupby("horizon")["rmse"].idxmin()]
            for _, row in best_per_horizon.iterrows():
                rows.append({"ticker": ticker, "horizon": row["horizon"],
                             "best_model": row["model"], "rmse": row["rmse"],
                             "direction_accuracy": row["direction_accuracy"]})
        comparison_df = pd.DataFrame(rows)
        comparison_df.to_csv(os.path.join(self.output_dir, "cross_asset_comparison.csv"), index=False)
        print(f"\nSaved cross-asset comparison to "
              f"{os.path.join(self.output_dir, 'cross_asset_comparison.csv')}")


def quick_backtest(ticker, horizons=None, max_windows=None, min_train_size=None,
                    step_size=None, include_benchmarks=True, kronos_params=None,
                    trading_strategy="long_short", trading_threshold=0.0,
                    starting_capital=10000.0, output_dir=None):
    """
    A fast, chat-friendly backtest for a single ticker: a handful of
    walk-forward windows over a couple of horizons, Kronos vs. the naive and
    linear-regression benchmarks (ARIMA is skipped here -- it's the slowest
    benchmark and not worth the wait for an inline chat reply), one equity
    curve chart, and a short text summary.

    Used by assistant.core_assistant.StockAssistant's "backtest" intent.
    For a thorough, full-history, all-benchmarks run, use
    backtesting.runner.BacktestRunner / run_backtest.py instead.

    Returns:
        {
          "text": str,                  human-readable summary
          "metrics_df": DataFrame,      per-model per-horizon metrics
          "portfolio_metrics": dict,    for the longest evaluated horizon
          "image_path": str | None,     equity curve PNG
        }
    """
    from assistant import config as assistant_config

    horizons = tuple(horizons or assistant_config.BACKTEST_QUICK_HORIZONS)
    max_windows = max_windows or assistant_config.BACKTEST_QUICK_MAX_WINDOWS
    min_train_size = min_train_size or assistant_config.BACKTEST_QUICK_MIN_TRAIN_SIZE
    step_size = step_size or assistant_config.BACKTEST_QUICK_STEP_SIZE
    output_dir = output_dir or os.path.join(assistant_config.BACKTEST_DIR, ticker.upper())
    os.makedirs(output_dir, exist_ok=True)

    df = YahooFinanceLoader().load(ticker)
    validator = WalkForwardValidator(
        window_type="expanding", min_train_size=min_train_size,
        step_size=step_size, horizons=horizons, max_windows=max_windows,
    )

    models = {"Kronos": make_kronos_predict_fn(**(kronos_params or {}))}
    if include_benchmarks:
        full_suite = get_benchmark_suite(include_arima=False)
        # keep it to two fast, informative baselines for a quick chat reply
        for name in ["Naive (last close)", "Linear Regression"]:
            if name in full_suite:
                models[name] = full_suite[name]

    metrics_rows = []
    kronos_results = None
    for model_name, predict_fn in models.items():
        horizon_results = validator.run(df, predict_fn, verbose=False)
        if model_name == "Kronos":
            kronos_results = horizon_results
        for h, hdf in horizon_results.items():
            if hdf.empty:
                continue
            m = metrics.compute_all_metrics(hdf)
            m.update({"model": model_name, "horizon": h})
            metrics_rows.append(m)
    metrics_df = pd.DataFrame(metrics_rows)

    # Trading simulation + equity chart on the longest horizon evaluated
    main_horizon = max(horizons)
    portfolio = {}
    image_path = None
    if kronos_results and not kronos_results.get(main_horizon, pd.DataFrame()).empty:
        hdf = kronos_results[main_horizon]
        sim = TradingSimulator(strategy=trading_strategy, threshold=trading_threshold)
        trades_df, equity_df = sim.run(hdf, starting_capital)
        n_splits = hdf["split_date"].nunique()
        periods_per_year = max(1, round(252 / max(main_horizon, 1)))
        portfolio = portfolio_metrics.compute_all(
            trades_df, equity_df, total_periods=n_splits,
            starting_capital=starting_capital, periods_per_year=periods_per_year,
        )
        if not equity_df.empty:
            image_path = visualization.plot_equity_curve(
                equity_df, f"{ticker} -- Backtest Equity Curve (horizon={main_horizon}d, "
                           f"{n_splits} windows)",
                os.path.join(output_dir, "equity_curve.png"), starting_capital,
            )

    text = _format_quick_backtest_text(ticker, metrics_df, portfolio, horizons, max_windows)
    return {"text": text, "metrics_df": metrics_df, "portfolio_metrics": portfolio, "image_path": image_path}


def _format_quick_backtest_text(ticker, metrics_df, portfolio, horizons, max_windows):
    if metrics_df.empty:
        return (f"Couldn't run a backtest for {ticker} -- not enough history for "
                f"{max_windows} walk-forward windows at these horizons. Try a "
                f"smaller horizon or a longer-listed ticker.")

    lines = [f"Backtest for {ticker} -- {max_windows} walk-forward windows, "
             f"horizons {list(horizons)} days (expanding window):"]

    kronos_df = metrics_df[metrics_df["model"] == "Kronos"].sort_values("horizon")
    for _, row in kronos_df.iterrows():
        lines.append(
            f"  h={int(row['horizon'])}d: RMSE={row['rmse']:.2f}, MAE={row['mae']:.2f}, "
            f"direction accuracy={row['direction_accuracy']:.1f}%, "
            f"IC={row['information_coefficient']:.2f}" if row['information_coefficient'] == row['information_coefficient']
            else f"  h={int(row['horizon'])}d: RMSE={row['rmse']:.2f}, MAE={row['mae']:.2f}, "
                 f"direction accuracy={row['direction_accuracy']:.1f}%"
        )

    # quick comparison vs baselines at the longest horizon
    main_h = max(horizons)
    at_main_h = metrics_df[metrics_df["horizon"] == main_h].sort_values("rmse")
    if len(at_main_h) > 1:
        ranking = ", ".join(f"{r['model']} (RMSE={r['rmse']:.2f})" for _, r in at_main_h.iterrows())
        lines.append(f"At {main_h}d horizon, ranked by RMSE (lower is better): {ranking}")

    if portfolio:
        lines.append(
            f"Simulated trading at {main_h}d horizon: total return "
            f"{portfolio.get('total_return_pct', float('nan')):.1f}%, "
            f"Sharpe {portfolio.get('sharpe_ratio', float('nan')):.2f}, "
            f"win rate {portfolio.get('win_rate_pct', float('nan')):.1f}%, "
            f"max drawdown {portfolio.get('max_drawdown_pct', float('nan')):.1f}%, "
            f"{int(portfolio.get('num_trades', 0))} trades."
        )

    lines.append("This is a quick in-chat check (few windows, few benchmarks). "
                  "For a full report with plots and diagnostics, run "
                  "`python run_backtest.py --tickers " + ticker + "`.")
    return "\n".join(lines)
