import numpy as np
import pandas as pd

from assistant import forecast_cache, forecaster
from assistant.context_signal import build_context_signal, widen_forecast_bands


def _history(n=40):
    closes = 100 * np.exp(np.cumsum(np.resize([0.012, -0.009, 0.004, -0.006], n)))
    return pd.DataFrame({
        "timestamps": pd.date_range("2025-01-01", periods=n, freq="B"),
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": np.full(n, 1000.0),
        "amount": closes * 1000,
    })


def test_single_run_adds_historical_volatility_band_without_moving_forecast(monkeypatch):
    hist = _history()

    class Predictor:
        max_context = 512

        def predict(self, **kwargs):
            return pd.DataFrame({
                "open": [120.0, 121.0, 122.0], "high": [121.0, 122.0, 123.0],
                "low": [119.0, 120.0, 121.0], "close": [120.0, 121.0, 122.0],
                "volume": [1000.0] * 3, "amount": [120000.0, 121000.0, 122000.0],
            })

    forecast_cache.clear()
    monkeypatch.setattr(forecaster, "get_predictor", lambda: Predictor())
    monkeypatch.setattr(forecaster, "FORECAST_DRIFT_BLEND", 0.0)
    result = forecaster.run_forecast(hist, pred_len=3, n_runs=1, anchor_to_last_close=False)

    returns = np.diff(np.log(hist["close"].to_numpy()))[-20:]
    sigma = np.std(returns, ddof=1)
    expected_spread = result["pred_df"]["close"].to_numpy() * 1.28 * sigma * np.sqrt([1, 2, 3])
    np.testing.assert_allclose(result["low_df"]["close"], result["pred_df"]["close"] - expected_spread)
    np.testing.assert_allclose(result["high_df"]["close"], result["pred_df"]["close"] + expected_spread)
    np.testing.assert_allclose(result["pred_df"]["close"], [120.0, 121.0, 122.0])
    assert result["band_source"] == "analytical_vol"


def test_multi_run_band_is_still_sampled(monkeypatch):
    hist = _history()

    class Predictor:
        max_context = 512
        calls = 0

        def predict(self, **kwargs):
            self.calls += 1
            close = 100.0 + self.calls
            return pd.DataFrame({"close": [close, close + 1]})

    predictor = Predictor()
    forecast_cache.clear()
    monkeypatch.setattr(forecaster, "get_predictor", lambda: predictor)
    monkeypatch.setattr(forecaster, "FORECAST_DRIFT_BLEND", 0.0)
    result = forecaster.run_forecast(hist, pred_len=2, n_runs=2, anchor_to_last_close=False)
    assert result["band_source"] == "sampled"
    assert result["low_df"] is not None and result["high_df"] is not None


def test_bear_high_vol_regime_sets_context_and_minimum_band_width():
    # Smooth decline followed by a high-volatility 20-bar segment.
    smooth = np.linspace(110.0, 90.0, 200)
    tail = [90.0]
    for i in range(20):
        tail.append(tail[-1] * (0.90 if i % 2 == 0 else 1.08))
    close = np.asarray(list(smooth) + tail[1:])
    hist = pd.DataFrame({"timestamps": pd.date_range("2024-01-01", periods=len(close), freq="B"),
                         "close": close})
    signal = build_context_signal(hist_df=hist)
    assert signal.market_regime == "bear_high_vol"
    assert signal.to_dict()["market_regime"] == "bear_high_vol"
    assert signal.band_widen_factor >= 1.30
    assert any("Bear/high-volatility" in note for note in signal.notes)


def test_widening_never_changes_central_forecast_path():
    forecast = {
        "pred_df": pd.DataFrame({"close": [100.0, 110.0]}),
        "low_df": pd.DataFrame({"close": [90.0, 95.0]}),
        "high_df": pd.DataFrame({"close": [110.0, 125.0]}),
        "band_source": "analytical_vol",
    }
    widened = widen_forecast_bands(forecast, 1.3)
    np.testing.assert_allclose(widened["pred_df"]["close"], [100.0, 110.0])
    np.testing.assert_allclose(widened["low_df"]["close"], [87.0, 90.5])
    np.testing.assert_allclose(widened["high_df"]["close"], [113.0, 129.5])
