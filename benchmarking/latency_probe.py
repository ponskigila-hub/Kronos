#!/usr/bin/env python
"""
Measures model-load time, per-call inference latency, and peak memory for
ONE Kronos model variant, then prints a single JSON line to stdout.

Run as its own subprocess (see benchmarking/model_benchmark.py) rather
than imported and called in a loop for three models in the same process,
because assistant/model_loader.py is a deliberate process-wide singleton
(see its own docstring: "loads exactly once... reuses it for every
subsequent forecast request"). That's the right design for the running
app -- a single process should never juggle three loaded models -- but it
means a clean apples-to-apples benchmark of mini vs. small vs. base needs
one fresh process per model, not three `get_predictor()` calls in a row
that would just return the same cached instance after the first.

Usage (normally invoked by model_benchmark.py, not run directly):
    KRONOS_MODEL_ID=NeoQuasar/Kronos-mini \\
    KRONOS_TOKENIZER_ID=NeoQuasar/Kronos-Tokenizer-2k \\
    KRONOS_MAX_CONTEXT=2048 \\
    python benchmarking/latency_probe.py --ticker AAPL --pred-len 14 --n-calls 5
"""
import argparse
import json
import os
import resource
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _peak_rss_mb():
    # ru_maxrss is KB on Linux, bytes on macOS -- normalize to MB assuming
    # Linux, which is what DEPLOYMENT.md targets for the actual deployment
    # this benchmark informs.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--pred-len", type=int, default=14)
    parser.add_argument("--lookback", type=int, default=400)
    parser.add_argument("--n-calls", type=int, default=5,
                         help="Forecast calls to time after the cache-busting warmup call; latency is reported as the median.")
    args = parser.parse_args()

    from assistant import model_loader, forecaster, data_fetcher, forecast_cache
    from assistant.config import KRONOS_MODEL_ID

    load_start = time.perf_counter()
    model_loader.get_predictor()
    load_seconds = time.perf_counter() - load_start

    hist_df = data_fetcher.fetch_history(args.ticker, lookback_days=args.lookback)

    gpu_available = False
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass

    call_times = []
    for i in range(args.n_calls):
        # Each call must bypass the prediction cache (assistant/forecast_cache.py)
        # to measure real inference time, not a cache hit -- clear it before
        # every timed call so this probe reflects actual model compute, which
        # is the number that matters for a mini/small/base comparison.
        forecast_cache.clear()
        start = time.perf_counter()
        forecaster.run_forecast(hist_df, pred_len=args.pred_len, n_runs=1)
        call_times.append(time.perf_counter() - start)

    call_times.sort()
    median_latency_ms = round(call_times[len(call_times) // 2] * 1000, 1)

    gpu_peak_mb = None
    if gpu_available:
        try:
            import torch
            gpu_peak_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1)
        except Exception:
            pass

    result = {
        "model_id": KRONOS_MODEL_ID,
        "ticker": args.ticker,
        "pred_len": args.pred_len,
        "n_calls": args.n_calls,
        "model_load_seconds": round(load_seconds, 2),
        "median_inference_ms": median_latency_ms,
        "all_inference_ms": [round(t * 1000, 1) for t in call_times],
        "peak_rss_mb": _peak_rss_mb(),
        "gpu_available": gpu_available,
        "gpu_peak_mb": gpu_peak_mb,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
