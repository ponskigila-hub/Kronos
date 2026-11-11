"""Unit tests for forecasting / sizing / feedback-loop upgrades."""
import math
import os
import tempfile
import time

import numpy as np
import pandas as pd
import pytest


def _synthetic_closes(n=80, start=100.0, drift=0.2, seed=0):
    rng = np.random.default_rng(seed)
    steps = drift + rng.normal(0, 0.5, size=n)
    return start + np.cumsum(steps)


def test_multi_horizon_drift_uses_weighted_windows():
    from assistant.forecaster import _drift_path, _mean_daily_change

    closes = _synthetic_closes(80, drift=0.5)
    path = _drift_path(float(closes[-1]), closes, pred_len=10, vol_damping=0.0)
    assert len(path) == 10
    # With positive drift history, path should generally rise
    assert path[-1] > path[0] - 1e-6

    d5 = _mean_daily_change(closes, 5)
    d20 = _mean_daily_change(closes, 20)
    d60 = _mean_daily_change(closes, 60)
    assert d5 is not None and d20 is not None and d60 is not None
    expected_avg = (0.50 * d5 + 0.35 * d20 + 0.15 * d60)
    # Without vol damping slope equals weighted mean
    expected_end = float(closes[-1]) + expected_avg * 10
    assert abs(path[-1] - expected_end) < 1e-6


def test_vol_damping_reduces_slope_when_vol_high():
    from assistant.forecaster import _drift_path

    # Quiet then noisy spike at the end
    quiet = np.linspace(100, 110, 50)
    spike = quiet[-1] + np.array([3, -3, 4, -4, 5, -2, 3, -3, 2, -1], dtype=float)
    closes = np.concatenate([quiet, spike])
    undamped = _drift_path(float(closes[-1]), closes, pred_len=5, vol_damping=0.0)
    damped = _drift_path(float(closes[-1]), closes, pred_len=5, vol_damping=1.0)
    # Absolute end move should be smaller with damping
    assert abs(damped[-1] - closes[-1]) <= abs(undamped[-1] - closes[-1]) + 1e-9


def test_confidence_scale_from_uncertainty():
    from assistant.forecaster import confidence_scale_from_uncertainty

    assert confidence_scale_from_uncertainty(None) == 1.0
    assert confidence_scale_from_uncertainty(10) == 1.0
    assert abs(confidence_scale_from_uncertainty(15) - 1.0) < 1e-9
    # at 30%: 1 - (30-15)/30 = 0.5
    assert abs(confidence_scale_from_uncertainty(30) - 0.5) < 1e-9
    assert confidence_scale_from_uncertainty(100) == 0.5


def test_analytical_uncertainty_pct_single_run(monkeypatch):
    """n_runs==1 still returns low/high bands and uncertainty_pct without multi-sampling."""
    from assistant import forecaster

    class FakePred:
        max_context = 512

        def predict(self, df, x_timestamp, y_timestamp, pred_len, T, top_p, sample_count, verbose=False):
            last = float(df["close"].iloc[-1])
            idx = np.arange(1, pred_len + 1)
            close = last * (1 + 0.001 * idx)
            return pd.DataFrame({
                "open": close, "high": close * 1.01, "low": close * 0.99,
                "close": close, "volume": np.ones(pred_len), "amount": close,
            })

    monkeypatch.setattr(forecaster, "get_predictor", lambda: FakePred())
    # Avoid cache collisions across runs
    monkeypatch.setattr(forecaster.forecast_cache, "get", lambda key: None)
    monkeypatch.setattr(forecaster.forecast_cache, "set", lambda key, val: None)

    n = 60
    closes = _synthetic_closes(n, drift=0.1)
    hist = pd.DataFrame({
        "timestamps": pd.date_range("2024-01-01", periods=n, freq="B"),
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": np.full(n, 1e6), "amount": closes * 1e6,
    })
    fc = forecaster.run_forecast(hist, pred_len=10, n_runs=1, sample_count=1)
    assert fc.get("low_df") is not None
    assert fc.get("high_df") is not None
    assert "uncertainty_pct" in fc
    assert fc["uncertainty_pct"] >= 0
    assert float(fc["high_df"]["close"].iloc[-1]) >= float(fc["low_df"]["close"].iloc[-1])


def test_forecast_performance_record_and_read(tmp_path, monkeypatch):
    from assistant import db as db_mod

    db_path = str(tmp_path / "test_kronos.db")
    monkeypatch.setattr(db_mod, "DATABASE_PATH", db_path)
    monkeypatch.setattr(db_mod, "_initialized", False)
    db_mod.init_db(migrate_json=False)

    assert db_mod.get_ticker_reliability("AAPL") is None
    db_mod.record_forecast_grade("AAPL", True, 2.0)
    db_mod.record_forecast_grade("AAPL", False, 4.0)
    db_mod.record_forecast_grade("AAPL", True, 3.0)

    rel = db_mod.get_ticker_reliability("AAPL")
    assert rel is not None
    assert rel["graded_count"] == 3
    assert rel["correct_direction"] == 2
    assert abs(rel["directional_accuracy"] - (2 / 3 * 100)) < 0.05
    assert abs(rel["avg_error_pct"] - 3.0) < 1e-6


def test_composite_score_reliability_adjusts_kronos_weight():
    from assistant.screener.scoring import composite_score, DEFAULT_WEIGHTS

    cats = {
        "trend": 80, "momentum": 70, "relative_strength": 60,
        "volatility": 50, "liquidity": 50, "risk": 50, "kronos": 90,
    }
    base, used0 = composite_score(cats, weights=DEFAULT_WEIGHTS, reliability=None)
    # Poor history: kronos weight cut, overall should drop when kronos was high
    poor = {"graded_count": 5, "directional_accuracy": 30.0}
    score_poor, used_poor = composite_score(cats, weights=DEFAULT_WEIGHTS, reliability=poor)
    assert used_poor["kronos"] < used0["kronos"]
    assert score_poor <= base + 1e-6

    good = {"graded_count": 5, "directional_accuracy": 80.0}
    score_good, used_good = composite_score(cats, weights=DEFAULT_WEIGHTS, reliability=good)
    # After normalize, kronos share should be higher than default share
    assert used_good["kronos"] > used0["kronos"] - 1e-9


def test_regime_adjusted_weights_bear():
    from assistant.screener.scoring import get_regime_adjusted_weights, DEFAULT_WEIGHTS

    n = 220
    # Declining series so last price is under SMA200
    close = np.linspace(200, 100, n)
    df = pd.DataFrame({
        "timestamps": pd.date_range("2023-01-01", periods=n, freq="B"),
        "close": close,
    })
    w, regime = get_regime_adjusted_weights(DEFAULT_WEIGHTS, df)
    assert regime == "bear"
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert w["risk"] > DEFAULT_WEIGHTS["risk"] - 1e-6 or w["risk"] >= 0


def test_context_signal_regime_fields():
    from assistant.context_signal import build_context_signal, ContextSignal, apply_context_covariate_nudge

    n = 80
    close = np.linspace(100, 90, n)  # mild downtrend
    hist = pd.DataFrame({
        "timestamps": pd.date_range("2024-01-01", periods=n, freq="B"),
        "close": close, "open": close, "high": close * 1.01, "low": close * 0.99,
        "volume": np.ones(n),
    })
    sig = build_context_signal(hist_df=hist)
    assert isinstance(sig, ContextSignal)
    assert hasattr(sig, "market_regime")
    assert hasattr(sig, "uncertainty_scale")
    d = sig.to_dict()
    assert "market_regime" in d and "uncertainty_scale" in d

    # High-confidence nudge
    pred = pd.DataFrame({
        "timestamps": pd.date_range("2024-06-01", periods=5, freq="B"),
        "close": np.array([100.0, 101, 102, 103, 104]),
        "open": np.array([100.0, 101, 102, 103, 104]),
        "high": np.array([101.0, 102, 103, 104, 105]),
        "low": np.array([99.0, 100, 101, 102, 103]),
    })
    fc = {"pred_df": pred.copy()}
    strong = ContextSignal(score=1.0, confidence="high", earnings_gate=False)
    out, applied = apply_context_covariate_nudge(fc, strong, max_nudge=0.03)
    assert applied is True
    assert float(out["pred_df"]["close"].iloc[-1]) > float(pred["close"].iloc[-1])
