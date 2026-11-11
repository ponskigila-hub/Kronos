import numpy as np
import pandas as pd

from assistant.screener import engine, scoring
from assistant.screener import universe as universe_mod


def test_regime_adjusted_weights_requires_200_bars_and_normalizes():
    base = dict(scoring.DEFAULT_WEIGHTS)
    short = pd.DataFrame({"close": np.full(199, 100.0)})
    unchanged, label = scoring.regime_adjusted_weights(base, short)
    assert label == "unknown"
    assert unchanged == base

    bear = pd.DataFrame({"close": [100.0] * 199 + [90.0]})
    adjusted, label = scoring.regime_adjusted_weights(base, bear)
    assert label == "bear"
    assert abs(sum(adjusted.values()) - 1.0) < 1e-12
    assert adjusted["risk"] > base["risk"]
    assert adjusted["liquidity"] > base["liquidity"]
    assert adjusted["volatility"] > base["volatility"]
    assert adjusted["trend"] < base["trend"]
    assert adjusted["momentum"] < base["momentum"]


def _patch_engine(monkeypatch):
    benchmark = pd.DataFrame({"close": [100.0] * 199 + [90.0]})
    candidate = pd.DataFrame({"close": [10.0] * 200})
    monkeypatch.setattr(universe_mod, "resolve_universe", lambda *a, **k: ["ABC"])
    monkeypatch.setattr(engine.data_mod, "fetch_universe",
                        lambda tickers, **kwargs: ({"ABC": candidate, "SPY": benchmark}, {}))
    monkeypatch.setattr(engine.presets_mod, "get",
                        lambda key: {"weights": None, "force_kronos": False})
    monkeypatch.setattr(engine.metrics_mod, "compute_metrics", lambda *a, **k: {
        "price": 10.0, "liquidity_avg_dollar_volume_20d": 10_000_000.0,
    })
    monkeypatch.setattr(engine.presets_mod, "apply_preset_filters", lambda *a, **k: (True, []))
    monkeypatch.setattr(engine.filters_mod, "evaluate_all", lambda *a, **k: (True, []))
    monkeypatch.setattr(engine.scoring_mod, "compute_category_scores", lambda *a, **k: {
        "trend": 50.0, "momentum": 50.0, "relative_strength": 50.0,
        "volatility": 50.0, "liquidity": 50.0, "risk": 50.0, "kronos": None,
    })
    monkeypatch.setattr(engine.reasons_mod, "build_reasons", lambda *a, **k: {
        "strengths": [], "risks": [],
    })


def _run(**kwargs):
    return engine.run_screen(
        universe_key="custom", preset_key=kwargs.pop("preset_key", "none"),
        min_avg_dollar_volume=0, min_history_days=1, benchmark="SPY",
        lookback_days=200, preselection_count=1, final_count=1,
        enable_kronos=False, **kwargs,
    )


def test_auto_adjustment_applies_only_to_default_none_preset(monkeypatch):
    _patch_engine(monkeypatch)
    automatic = _run(weights=None)
    assert automatic["config_used"]["benchmark_regime"] == "bear"
    assert automatic["config_used"]["regime_adjustment_applied"] is True
    assert automatic["config_used"]["weights"]["risk"] > scoring.DEFAULT_WEIGHTS["risk"]

    custom = dict(scoring.DEFAULT_WEIGHTS)
    custom["trend"] = 0.4
    custom_result = _run(weights=custom)
    assert custom_result["config_used"]["regime_adjustment_applied"] is False
    assert custom_result["config_used"]["weights"] == custom

    preset_result = _run(weights=None, preset_key="trend")
    assert preset_result["config_used"]["regime_adjustment_applied"] is False
