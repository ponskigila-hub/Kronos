"""
Tests for benchmarking/model_benchmark.py's pure logic -- CSV aggregation
and Markdown table formatting -- with no subprocess, model, or network
calls involved. Running the actual mini/small/base comparison requires
downloading real weights and real market data, which this sandbox can't
do; these tests just confirm the harness's own aggregation code is
correct so its numbers can be trusted once you do run it.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from benchmarking.model_benchmark import _load_backtest_metrics, _to_markdown_table


def test_load_backtest_metrics_averages_across_tickers_and_horizons(tmp_path):
    # Simulate what run_backtest.py would have written for two tickers.
    for ticker, mae_values in [("AAPL", [1.0, 2.0]), ("MSFT", [3.0, 4.0])]:
        asset_dir = tmp_path / ticker
        asset_dir.mkdir()
        df = pd.DataFrame({
            "model": ["Kronos", "Kronos", "ARIMA"],
            "horizon": [1, 5, 1],
            "mae": mae_values + [99.0],  # ARIMA row should be excluded
            "rmse": [v * 2 for v in mae_values] + [199.0],
            "mape": [v * 0.1 for v in mae_values] + [9.9],
            "direction_accuracy": [55.0, 60.0, 10.0],
            "n_predictions": [100, 100, 100],
        })
        df.to_csv(asset_dir / "metrics_by_model_horizon.csv", index=False)

    result = _load_backtest_metrics(str(tmp_path))
    assert result is not None
    # Only the 4 "Kronos" rows should be averaged (1,2,3,4) -> mean 2.5
    assert result["mae"] == 2.5
    assert result["n_predictions"] == 400
    assert result["tickers_covered"] == ["AAPL", "MSFT"]


def test_load_backtest_metrics_returns_none_when_no_data(tmp_path):
    assert _load_backtest_metrics(str(tmp_path)) is None


def test_to_markdown_table_roundtrip():
    df = pd.DataFrame({"model": ["Kronos-mini", "Kronos-base"], "mae": [1.23, None]})
    md = _to_markdown_table(df)
    lines = md.strip().splitlines()
    assert lines[0] == "| model | mae |"
    assert lines[1] == "|---|---|"
    assert "Kronos-mini" in lines[2]
    assert "1.23" in lines[2]
    assert lines[3].endswith("|  |")  # NaN renders as an empty cell, not "nan"
