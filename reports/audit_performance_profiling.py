#!/usr/bin/env python3
"""
Kronos Performance Profiling
Measures actual latency and throughput across all major operations.
"""
import sys
import time
sys.path.insert(0, '.')

from assistant import data_fetcher, news, forecaster, indicators
from assistant.nlp import parse_intent
from assistant.copilot import answer as copilot_answer
from assistant.config import DEFAULT_LOOKBACK_DAYS, DEFAULT_PRED_LEN

print("=" * 70)
print("KRONOS PERFORMANCE PROFILING")
print("=" * 70)
print()

results = {}

# --- DATA LAYER ---
print("--- Data Layer Performance ---")
ticker = "AAPL"

# Cold fetch (no cache)
print("1. Data Fetcher (cold cache):")
start = time.perf_counter()
try:
    df = data_fetcher.fetch_history(ticker, DEFAULT_LOOKBACK_DAYS)
    elapsed = time.perf_counter() - start
    rows = len(df) if df is not None else 0
    print(f"   ✓ fetch_history(AAPL): {elapsed:.3f}s ({rows} rows)")
    results["data_fetcher_cold"] = elapsed
except Exception as e:
    print(f"   ✗ Error: {e}")
    results["data_fetcher_cold"] = None

# Warm fetch (cached)
print("2. Data Fetcher (warm cache - second call):")
start = time.perf_counter()
try:
    df = data_fetcher.fetch_history(ticker, DEFAULT_LOOKBACK_DAYS)
    elapsed = time.perf_counter() - start
    print(f"   ✓ fetch_history(AAPL): {elapsed:.3f}s (cached)")
    results["data_fetcher_warm"] = elapsed
except Exception as e:
    print(f"   ✗ Error: {e}")
    results["data_fetcher_warm"] = None

print()

# --- NLP PARSING ---
print("--- NLP Intent Routing ---")
test_inputs = [
    "forecast AAPL",
    "is MSFT a good buy",
    "compare NVDA and AMD",
]
times = []
for text in test_inputs:
    start = time.perf_counter()
    result = parse_intent(text)
    elapsed = time.perf_counter() - start
    times.append(elapsed)
    print(f"  '{text}': {elapsed*1000:.2f}ms → {result['intent']}")

avg_nlp = sum(times) / len(times)
results["nlp_avg"] = avg_nlp
print(f"  Average: {avg_nlp*1000:.2f}ms")

print()

# --- KRONOS MODEL INFERENCE ---
print("--- Kronos Model Inference (Cold) ---")
start = time.perf_counter()
try:
    forecast_df = forecaster.forecast_history(
        ticker,
        lookback_days=DEFAULT_LOOKBACK_DAYS,
        pred_len=DEFAULT_PRED_LEN,
        sample_runs=1
    )
    elapsed = time.perf_counter() - start
    print(f"✓ Model inference: {elapsed:.2f}s")
    results["model_inference_cold"] = elapsed
except Exception as e:
    print(f"✗ Error: {e}")
    results["model_inference_cold"] = None

print()

# --- NEWS FETCHING ---
print("--- News Fetching ---")
print("1. Cold fetch:")
start = time.perf_counter()
try:
    items, summary = news.get_news(ticker, limit=5)
    elapsed = time.perf_counter() - start
    print(f"   ✓ get_news(AAPL): {elapsed:.3f}s ({len(items)} items)")
    results["news_cold"] = elapsed
except Exception as e:
    print(f"   ✗ Error: {e}")
    results["news_cold"] = None

print("2. Warm fetch (second call):")
start = time.perf_counter()
try:
    items, summary = news.get_news(ticker, limit=5)
    elapsed = time.perf_counter() - start
    print(f"   ✓ get_news(AAPL): {elapsed:.3f}s (cached)")
    results["news_warm"] = elapsed
except Exception as e:
    print(f"   ✗ Error: {e}")
    results["news_warm"] = None

print()

# --- TECHNICAL INDICATORS ---
print("--- Technical Indicators ---")
start = time.perf_counter()
try:
    ind_result = indicators.get_indicators(ticker)
    elapsed = time.perf_counter() - start
    print(f"✓ get_indicators(AAPL): {elapsed:.3f}s")
    results["indicators"] = elapsed
except Exception as e:
    print(f"✗ Error: {e}")
    results["indicators"] = None

print()

# --- SUMMARY ---
print("=" * 70)
print("PERFORMANCE SUMMARY")
print("=" * 70)

perf_table = [
    ("Operation", "Cold (s)", "Warm (s)", "Notes"),
    ("-" * 40, "-" * 10, "-" * 10, "-" * 30),
]

if results.get("data_fetcher_cold"):
    perf_table.append((
        "Data Fetcher (yfinance)",
        f"{results['data_fetcher_cold']:.3f}",
        f"{results['data_fetcher_warm']:.3f}",
        "yfinance API call + cache"
    ))

if results.get("nlp_avg"):
    perf_table.append((
        "NLP Intent Parsing",
        f"{results['nlp_avg']*1000:.2f}ms",
        f"{results['nlp_avg']*1000:.2f}ms",
        "Regex-based, no ML"
    ))

if results.get("model_inference_cold"):
    perf_table.append((
        "Kronos Model Inference",
        f"{results['model_inference_cold']:.2f}",
        "N/A (no cache)",
        f"CPU-bound, model load + prediction"
    ))

if results.get("news_cold"):
    perf_table.append((
        "News Fetching (yfinance)",
        f"{results['news_cold']:.3f}",
        f"{results['news_warm']:.3f}",
        "yfinance news API"
    ))

if results.get("indicators"):
    perf_table.append((
        "Technical Indicators",
        f"{results['indicators']:.3f}",
        "N/A",
        "TA-Lib computation"
    ))

# Print formatted table
for row in perf_table:
    print(f"{row[0]:<40} {row[1]:>10} {row[2]:>10}   {row[3]}")

print()
print("NOTES:")
print("- Cold = first call, no cache")
print("- Warm = second call, uses cache if available")
print("- NLP is fast (regex-based, no network)")
print("- Model inference is the slowest operation (CPU/GPU-bound)")
print("- Network calls can vary based on internet speed")
