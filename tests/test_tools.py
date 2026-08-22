"""
Tests for assistant/tools.py -- verifies each tool returns a compact,
JSON-safe dict (never a DataFrame) and that failures degrade to
{"error": ...} instead of raising, using fully mocked underlying modules
(no network, no model, no real backtest).
"""
import pandas as pd
import pytest

from assistant import tools
from assistant.data_fetcher import TickerNotFoundError


def _fake_hist(n=10):
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.0 + i for i in range(n)], "volume": [1000] * n,
        "amount": [100000.0] * n,
    })


def test_get_kronos_forecast_returns_compact_dict(monkeypatch):
    monkeypatch.setattr(tools.data_fetcher, "fetch_history", lambda t: _fake_hist())
    monkeypatch.setattr(tools.forecaster, "run_forecast", lambda hist_df, pred_len, n_runs:
                         {"pred_df": pd.DataFrame({"close": [120.0]}), "lookback_used": 10})

    result = tools.get_kronos_forecast("AAPL", horizon=14)
    assert result["ticker"] == "AAPL"
    assert result["forecast_horizon_days"] == 14
    assert result["trend"] == "bullish"
    assert "error" not in result
    assert not isinstance(result.get("current_price"), pd.DataFrame)


def test_get_kronos_forecast_bearish_trend(monkeypatch):
    monkeypatch.setattr(tools.data_fetcher, "fetch_history", lambda t: _fake_hist())
    monkeypatch.setattr(tools.forecaster, "run_forecast", lambda hist_df, pred_len, n_runs:
                         {"pred_df": pd.DataFrame({"close": [90.0]}), "lookback_used": 10})
    result = tools.get_kronos_forecast("AAPL")
    assert result["trend"] == "bearish"


def test_get_kronos_forecast_handles_ticker_not_found(monkeypatch):
    def fail(t):
        raise TickerNotFoundError(f"'{t}' not found")
    monkeypatch.setattr(tools.data_fetcher, "fetch_history", fail)
    result = tools.get_kronos_forecast("BADTICKER")
    assert "error" in result
    assert "BADTICKER" in result["error"]


def test_get_kronos_forecast_handles_unexpected_exception(monkeypatch):
    def boom(t):
        raise RuntimeError("network exploded")
    monkeypatch.setattr(tools.data_fetcher, "fetch_history", boom)
    result = tools.get_kronos_forecast("AAPL")
    assert "error" in result
    assert "get_kronos_forecast failed" in result["error"]


def test_get_technical_indicators_shape(monkeypatch):
    ind_df = pd.DataFrame({"close": [100.0]})
    monkeypatch.setattr(tools.data_fetcher, "fetch_history", lambda t: _fake_hist())
    monkeypatch.setattr(tools.indicators, "compute_indicators", lambda hist_df: ind_df)
    monkeypatch.setattr(tools.indicators, "summarize_latest", lambda df: {
        "close": 105.0, "rsi_14": 62.0, "macd": 1.2, "macd_signal": 0.8,
        "sma_20": 100.0, "sma_50": 95.0, "bb_upper": 110.0, "bb_lower": 90.0,
        "atr_14": 2.0, "volume": 5000, "volume_sma_20": 4000,
    })
    result = tools.get_technical_indicators("AAPL")
    assert result["macd_signal"] == "positive"
    assert result["above_sma_20"] is True
    assert result["volume_above_20d_average"] is True


def test_get_news_sentiment_shape(monkeypatch):
    items = [{"title": "AAPL beats earnings"}, {"title": "Analysts upgrade AAPL"}]
    summary = {"label": "mostly positive", "avg_score": 0.4}
    monkeypatch.setattr(tools.news, "get_news", lambda t, limit=5: (items, summary))
    result = tools.get_news_sentiment("AAPL", limit=5)
    assert result["sentiment_label"] == "mostly positive"
    assert result["headline_count"] == 2
    assert result["headlines"] == ["AAPL beats earnings", "Analysts upgrade AAPL"]


def test_get_fundamentals_passthrough(monkeypatch):
    monkeypatch.setattr(tools.fundamentals, "get_fundamentals", lambda t: {"ticker": t.upper(), "pe_ratio": 30.0})
    result = tools.get_fundamentals("aapl")
    assert result == {"ticker": "AAPL", "pe_ratio": 30.0}


def test_compare_stocks_picks_stronger(monkeypatch):
    def fake_forecast(ticker, horizon=14):
        return {"ticker": ticker.upper(), "expected_return_pct": 5.0 if ticker == "AAPL" else 1.0}
    monkeypatch.setattr(tools, "get_kronos_forecast", fake_forecast)
    result = tools.compare_stocks("AAPL", "MSFT")
    assert result["stronger_forecast"] == "AAPL"


def test_compare_stocks_propagates_error(monkeypatch):
    def fake_forecast(ticker, horizon=14):
        if ticker == "BAD":
            return {"error": "not found"}
        return {"ticker": ticker.upper(), "expected_return_pct": 1.0}
    monkeypatch.setattr(tools, "get_kronos_forecast", fake_forecast)
    result = tools.compare_stocks("BAD", "MSFT")
    assert "error" in result
    assert "BAD" in result["error"]


def test_tool_registry_has_all_expected_tools():
    expected = {
        "get_kronos_forecast", "get_technical_indicators",
        "get_prediction_performance", "get_news_sentiment",
        "get_fundamentals", "compare_stocks",
    }
    assert set(tools.TOOL_REGISTRY.keys()) == expected
    for fn in tools.TOOL_REGISTRY.values():
        assert callable(fn)
