#!/usr/bin/env python
"""
CLI entry point for the backtesting framework.

Examples:
    # Single asset, default horizons, full history
    python run_backtest.py --tickers AAPL

    # Multi-asset (requirement #11 -- same code, different list)
    python run_backtest.py --tickers AAPL MSFT NVDA TSLA SPY BTC-USD ETH-USD

    # Rolling window instead of expanding, custom horizons
    python run_backtest.py --tickers AAPL --window-type rolling --train-size 300 \\
        --horizons 1 5 14 30

    # Cap the number of walk-forward windows while experimenting (Kronos-base
    # is slow -- don't run a full multi-year walk-forward until you've
    # sanity-checked the setup on a handful of windows first)
    python run_backtest.py --tickers AAPL --max-windows 5

    # On a laptop with no GPU and 8GB RAM or less: skip the slow ARIMA
    # benchmark, cap CPU threads so the rest of the system stays usable,
    # and keep windows modest -- one flag sets sensible defaults for all of it
    python run_backtest.py --tickers AAPL --low-resource

Results land in --output-dir (default: backtest_results/), one subfolder per
ticker with all metrics CSVs, portfolio metrics, residual diagnostics, and
every plot from the visualization suite, plus a cross_asset_comparison.csv
at the top level.
"""
import argparse
import os
import sys

# CPU thread limiting must be applied before `backtesting`/`assistant` are
# imported anywhere (assistant.config reads KRONOS_CPU_THREADS from the
# environment at import time) -- so we do a minimal pre-scan of argv for
# --low-resource / --cpu-threads here, before the main import below.
if "--low-resource" in sys.argv and "--cpu-threads" not in sys.argv:
    os.environ.setdefault("KRONOS_CPU_THREADS", "4")
elif "--cpu-threads" in sys.argv:
    idx = sys.argv.index("--cpu-threads")
    if idx + 1 < len(sys.argv):
        os.environ["KRONOS_CPU_THREADS"] = sys.argv[idx + 1]

from backtesting.runner import BacktestRunner  # noqa: E402  (see comment above)


def main():
    parser = argparse.ArgumentParser(description="Kronos backtesting framework")
    parser.add_argument("--tickers", nargs="+", required=True,
                         help="e.g. --tickers AAPL MSFT NVDA TSLA SPY BTC-USD ETH-USD")
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 3, 5, 7, 14, 30])
    parser.add_argument("--window-type", choices=["expanding", "rolling"], default="expanding")
    parser.add_argument("--train-size", type=int, default=252,
                         help="minimum training window size in trading days")
    parser.add_argument("--step-size", type=int, default=30,
                         help="how many days to advance between walk-forward splits")
    parser.add_argument("--max-windows", type=int, default=None,
                         help="cap the number of walk-forward steps (recommended while experimenting)")
    parser.add_argument("--no-benchmarks", action="store_true",
                         help="skip naive/moving-average/linear-regression/ARIMA comparisons")
    parser.add_argument("--no-arima", action="store_true",
                         help="keep the fast benchmarks but skip ARIMA specifically (it's the slowest one)")
    parser.add_argument("--low-resource", action="store_true",
                         help="preset for laptops with no GPU / <=8GB RAM: skips ARIMA, caps CPU "
                              "threads to 4 (override with --cpu-threads), and if you didn't pass "
                              "--max-windows, caps it at 15 so a run finishes in a reasonable time")
    parser.add_argument("--cpu-threads", type=int, default=None,
                         help="limit PyTorch CPU threads (no effect if a GPU is used). "
                              "--low-resource sets this to 4 unless you override it here")
    parser.add_argument("--strategy", choices=["long_only", "short_only", "long_short"],
                         default="long_short")
    parser.add_argument("--threshold", type=float, default=0.0,
                         help="minimum predicted return to act on (e.g. 0.01 = 1%%)")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--output-dir", default="backtest_results")
    parser.add_argument("--kronos-T", type=float, default=None,
                         help="sampling temperature (default: config.DEFAULT_KRONOS_T, currently 0.7 -- "
                              "lower = more stable/less noisy forecasts, 1.0 = most exploratory)")
    parser.add_argument("--kronos-top-p", type=float, default=0.9)
    parser.add_argument("--kronos-n-runs", type=int, default=1,
                         help="sampling runs per forecast for a confidence band (slower if >1)")
    args = parser.parse_args()

    if args.low_resource:
        if args.max_windows is None:
            args.max_windows = 15
        args.no_arima = True
        print(f"[--low-resource] max_windows<=15, ARIMA skipped, CPU threads capped at "
              f"{os.environ.get('KRONOS_CPU_THREADS', '4')}. Override any of these with their own flags.")

    runner = BacktestRunner(
        tickers=args.tickers,
        horizons=tuple(args.horizons),
        window_type=args.window_type,
        min_train_size=args.train_size,
        step_size=args.step_size,
        max_windows=args.max_windows,
        include_benchmarks=not args.no_benchmarks,
        include_arima=not args.no_arima,
        kronos_params={"T": args.kronos_T, "top_p": args.kronos_top_p, "n_runs": args.kronos_n_runs},
        trading_strategy=args.strategy,
        trading_threshold=args.threshold,
        starting_capital=args.capital,
        output_dir=args.output_dir,
    )
    runner.run()


if __name__ == "__main__":
    main()
