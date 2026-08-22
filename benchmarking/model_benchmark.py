#!/usr/bin/env python
"""
Compares Kronos-mini vs. Kronos-small vs. Kronos-base on:
  - inference latency (median, ms) and model load time
  - memory (peak RSS, and peak GPU memory if CUDA is available)
  - forecast quality (MAE, RMSE, MAPE, directional accuracy) via the
    existing backtesting/ walk-forward framework, across a representative
    ticker universe and multiple horizons -- not a single cherry-picked
    example.

Each model gets a completely fresh Python process for both the latency
probe and the backtest run. This is deliberate, not a shortcut: Kronos
model/tokenizer selection happens via KRONOS_MODEL_ID / KRONOS_TOKENIZER_ID
read once at import time (assistant/config.py) and then locked in by
model_loader.py's process-wide singleton (see that file's docstring). The
only clean way to compare three different weight sets is three separate
processes, each configured for one model via environment variables --
exactly how you'd actually run the app with a different model chosen.

This script builds the comparison; it deliberately does NOT recommend a
model for you at the end -- read PROVIDERS.md's sibling doc, the "Kronos
model recommendation" section of the final report, after you've run this
against your own hardware and ticker universe, since the right choice
depends on both.

Usage:
    # Full comparison: latency/memory + backtest quality, default universe
    python benchmarking/model_benchmark.py

    # Just the fast part while iterating on this script
    python benchmarking/model_benchmark.py --skip-backtest

    # Only mini vs. small, fewer tickers/windows, faster iteration
    python benchmarking/model_benchmark.py --models mini small \\
        --tickers AAPL MSFT --max-windows 5

Output:
    benchmark_results/<model>/latency.json        (from latency_probe.py)
    benchmark_results/<model>/...                  (full run_backtest.py output)
    benchmark_results/model_comparison.csv
    benchmark_results/model_comparison.md          (the table, ready to paste into a report)
"""
import argparse
import json
import os
import subprocess
import sys
import time

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# From README.md's model table -- context length differs for mini (it uses
# a different tokenizer, Kronos-Tokenizer-2k, trained for a 2048-token
# context vs. 512 for small/base's Kronos-Tokenizer-base). Getting this
# wrong doesn't error loudly -- it just quietly caps how much history the
# model can actually use -- so it's hardcoded here from the documented
# values rather than left as a CLI flag someone could mismatch.
MODEL_SPECS = {
    "mini": {
        "model_id": "NeoQuasar/Kronos-mini",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-2k",
        "max_context": 2048,
        "params_millions": 4.1,
    },
    "small": {
        "model_id": "NeoQuasar/Kronos-small",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
        "params_millions": 24.7,
    },
    "base": {
        "model_id": "NeoQuasar/Kronos-base",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
        "params_millions": 102.3,
    },
}

# Same rationale as BACKTEST_README.md's default universe: don't judge
# model quality from one stock. Kept smaller than the full README example
# universe by default so a first run finishes in reasonable time; pass
# --tickers to widen it once the harness itself is confirmed working.
DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "SPY", "BTC-USD"]
DEFAULT_HORIZONS = [1, 5, 14, 30]


def _env_for_model(spec):
    env = os.environ.copy()
    env["KRONOS_MODEL_ID"] = spec["model_id"]
    env["KRONOS_TOKENIZER_ID"] = spec["tokenizer_id"]
    env["KRONOS_MAX_CONTEXT"] = str(spec["max_context"])
    return env


def run_latency_probe(model_name, spec, args, out_dir):
    print(f"\n[{model_name}] Measuring load time, inference latency, memory...")
    cmd = [
        sys.executable, os.path.join(REPO_ROOT, "benchmarking", "latency_probe.py"),
        "--ticker", args.latency_ticker,
        "--pred-len", str(args.latency_pred_len),
        "--n-calls", str(args.latency_calls),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=_env_for_model(spec),
                             capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[{model_name}] latency probe FAILED:\n{result.stderr}", file=sys.stderr)
        return None

    # latency_probe.py prints exactly one JSON line; be tolerant of any
    # warning/log noise a model-loading library might print to stdout
    # around it by taking the last line that parses as JSON.
    payload = None
    for line in result.stdout.strip().splitlines()[::-1]:
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if payload is None:
        print(f"[{model_name}] couldn't parse latency probe output:\n{result.stdout}", file=sys.stderr)
        return None

    with open(os.path.join(out_dir, "latency.json"), "w") as f:
        json.dump(payload, f, indent=2)
    return payload


def run_backtest_for_model(model_name, spec, args, out_dir):
    print(f"\n[{model_name}] Running walk-forward backtest across {args.tickers} "
          f"(horizons={args.horizons})... this is the slow part.")
    cmd = [
        sys.executable, os.path.join(REPO_ROOT, "run_backtest.py"),
        "--tickers", *args.tickers,
        "--horizons", *[str(h) for h in args.horizons],
        "--output-dir", out_dir,
        "--no-arima",  # keep the model-comparison loop itself fast; ARIMA/other
                        # classical benchmarks are for backtesting/'s own reports,
                        # not needed to compare Kronos variants against each other
    ]
    if args.max_windows:
        cmd += ["--max-windows", str(args.max_windows)]
    start = time.time()
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=_env_for_model(spec))
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"[{model_name}] backtest FAILED (exit {result.returncode})", file=sys.stderr)
        return None, elapsed
    return _load_backtest_metrics(out_dir), elapsed


def _load_backtest_metrics(out_dir):
    """
    Average the per-asset metrics_by_model_horizon.csv files (Kronos rows
    only -- the backtest also computes classical benchmarks for its own
    reports, which aren't relevant to a mini/small/base comparison) into
    one row: mean MAE/RMSE/MAPE/directional accuracy across every ticker
    and horizon that was tested, so one bad/easy ticker doesn't dominate
    the headline number.
    """
    rows = []
    for entry in os.listdir(out_dir):
        metrics_path = os.path.join(out_dir, entry, "metrics_by_model_horizon.csv")
        if os.path.isfile(metrics_path):
            df = pd.read_csv(metrics_path)
            df = df[df["model"] == "Kronos"]
            df["ticker"] = entry
            rows.append(df)
    if not rows:
        return None
    combined = pd.concat(rows, ignore_index=True)
    return {
        "mae": round(combined["mae"].mean(), 4),
        "rmse": round(combined["rmse"].mean(), 4),
        "mape": round(combined["mape"].mean(), 4) if "mape" in combined else None,
        "direction_accuracy": round(combined["direction_accuracy"].mean(), 2),
        "n_predictions": int(combined["n_predictions"].sum()),
        "tickers_covered": sorted(combined["ticker"].unique().tolist()),
    }


def _to_markdown_table(df: pd.DataFrame) -> str:
    """Tiny manual Markdown table writer -- avoids adding `tabulate` as a
    new dependency (pandas.DataFrame.to_markdown requires it) just for
    this one report."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        cells = ["" if pd.isna(v) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", choices=list(MODEL_SPECS), default=list(MODEL_SPECS))
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--horizons", nargs="+", type=int, default=DEFAULT_HORIZONS)
    parser.add_argument("--max-windows", type=int, default=None,
                         help="Cap walk-forward windows per ticker -- start small (e.g. 5) to sanity-check before a full run, especially for Kronos-base on CPU.")
    parser.add_argument("--latency-ticker", default="AAPL")
    parser.add_argument("--latency-pred-len", type=int, default=14)
    parser.add_argument("--latency-calls", type=int, default=5)
    parser.add_argument("--skip-latency", action="store_true")
    parser.add_argument("--skip-backtest", action="store_true")
    parser.add_argument("--output-dir", default="benchmark_results")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rows = []

    for model_name in args.models:
        spec = MODEL_SPECS[model_name]
        model_dir = os.path.join(args.output_dir, model_name)
        os.makedirs(model_dir, exist_ok=True)

        latency = None if args.skip_latency else run_latency_probe(model_name, spec, args, model_dir)
        quality, backtest_seconds = (None, None) if args.skip_backtest else \
            run_backtest_for_model(model_name, spec, args, model_dir)

        rows.append({
            "model": f"Kronos-{model_name}",
            "params_millions": spec["params_millions"],
            "max_context": spec["max_context"],
            "model_load_seconds": latency["model_load_seconds"] if latency else None,
            "median_inference_ms": latency["median_inference_ms"] if latency else None,
            "peak_rss_mb": latency["peak_rss_mb"] if latency else None,
            "gpu_peak_mb": latency["gpu_peak_mb"] if latency else None,
            "mae": quality["mae"] if quality else None,
            "rmse": quality["rmse"] if quality else None,
            "mape": quality["mape"] if quality else None,
            "direction_accuracy_pct": quality["direction_accuracy"] if quality else None,
            "n_predictions": quality["n_predictions"] if quality else None,
            "backtest_seconds": round(backtest_seconds, 1) if backtest_seconds else None,
        })

    comparison_df = pd.DataFrame(rows)
    csv_path = os.path.join(args.output_dir, "model_comparison.csv")
    comparison_df.to_csv(csv_path, index=False)

    md_path = os.path.join(args.output_dir, "model_comparison.md")
    with open(md_path, "w") as f:
        f.write("# Kronos model comparison\n\n")
        f.write(f"Tickers: {', '.join(args.tickers)}  \n")
        f.write(f"Horizons: {', '.join(str(h) for h in args.horizons)}  \n\n")
        f.write(_to_markdown_table(comparison_df))
        f.write("\n")

    print(f"\n{'='*70}\nDone. Wrote:\n  {csv_path}\n  {md_path}\n{'='*70}\n")
    print(comparison_df.to_string(index=False))


if __name__ == "__main__":
    main()
