import json
import os

import pandas as pd

from assistant import db, forecaster, position_plan, storage
from assistant.context_signal import widen_forecast_bands
from assistant.screener import scoring


def test_uncertainty_metadata_and_scale_contract():
    low = pd.DataFrame({"close": [95.0, 80.0]})
    high = pd.DataFrame({"close": [105.0, 120.0]})
    assert forecaster.uncertainty_pct_from_bands(low, high, 100.0) == 40.0
    assert forecaster.confidence_scale_from_uncertainty(None) == 1.0
    assert forecaster.confidence_scale_from_uncertainty(15.0) == 1.0
    assert forecaster.confidence_scale_from_uncertainty(30.0) == 0.5
    assert forecaster.confidence_scale_from_uncertainty(100.0) == 0.5
    assert forecaster.confidence_scale_from_uncertainty(float("nan")) == 1.0


def test_context_band_widening_preserves_point_forecast_and_updates_width():
    pred = pd.DataFrame({"close": [101.0, 102.0]})
    low = pd.DataFrame({"close": [99.0, 98.0]})
    high = pd.DataFrame({"close": [103.0, 106.0]})
    base = {
        "pred_df": pred.copy(), "low_df": low, "high_df": high,
        "uncertainty_reference_close": 100.0,
        "uncertainty_pct": forecaster.uncertainty_pct_from_bands(low, high, 100.0),
    }
    widened = widen_forecast_bands(base, 1.5)
    assert widened["pred_df"]["close"].tolist() == pred["close"].tolist()
    assert widened["uncertainty_pct"] == 12.0
    assert widened["uncertainty_pct"] > base["uncertainty_pct"]


def test_position_risk_budget_scales_without_changing_entry_math():
    normal = position_plan._risk_size(100_000, 1.0, 10.0, 10.0)
    wide = position_plan._risk_size(100_000, 1.0, 10.0, 30.0)
    assert normal["shares"] == 100
    assert normal["effective_risk_pct"] == 1.0
    assert wide["shares"] == 50
    assert wide["risk_dollars"] == 500.0
    assert wide["requested_risk_dollars"] == 1000.0
    assert wide["effective_risk_pct"] == 0.5
    assert wide["uncertainty_pct"] == 30.0


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "kronos.sqlite3"))
    monkeypatch.setattr(db, "_initialized", False)
    db.init_db(migrate_json=False)


def test_ticker_reliability_is_position_idempotent_user_and_horizon_scoped(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    assert db.record_forecast_grade("p1", "u1", "aapl", 14, .01, .02, True, 1.0, 100.0)
    assert not db.record_forecast_grade("p1", "u1", "AAPL", 14, .01, -.03, False, 4.0, 101.0)
    assert db.record_forecast_grade("p2", "u1", "AAPL", 14, .01, -.02, False, 3.0, 102.0)
    assert db.record_forecast_grade("p3", "u1", "AAPL", 30, .02, .01, True, 1.0, 103.0)
    assert db.record_forecast_grade("p4", "u2", "AAPL", 14, .01, .03, True, 2.0, 104.0)

    u1_14 = db.get_ticker_reliability("aapl", horizon_days=14, user_id="u1")
    assert u1_14["graded_count"] == 2
    assert u1_14["directional_accuracy"] == 50.0
    assert u1_14["avg_error_pct"] == 2.0
    assert db.get_ticker_reliability("AAPL", horizon_days=14, user_id="u2")["graded_count"] == 1
    assert db.get_ticker_reliability("AAPL", horizon_days=90, user_id="u1") is None


def test_reliability_weighting_has_threshold_shrinkage_and_kronos_gate():
    base = dict(scoring.DEFAULT_WEIGHTS)
    below, _ = scoring.composite_score(
        {"trend": 50, "risk": 50, "kronos": 90}, weights=base,
        reliability={"graded_count": 9, "directional_accuracy": 0.0},
    )
    unchanged, used_base = scoring.composite_score(
        {"trend": 50, "risk": 50, "kronos": 90}, weights=base, reliability=None,
    )
    assert below == unchanged
    assert used_base["kronos"] == base["kronos"]

    poor = scoring.adjust_weights_for_reliability(
        base, {"graded_count": 20, "directional_accuracy": 30.0},
    )
    good = scoring.adjust_weights_for_reliability(
        base, {"graded_count": 20, "directional_accuracy": 80.0},
    )
    assert abs(sum(poor.values()) - 1.0) < 1e-9
    assert abs(sum(good.values()) - 1.0) < 1e-9
    assert poor["kronos"] < base["kronos"]
    assert good["kronos"] > base["kronos"]

    # Old reliability cannot change a score when this screen did not run Kronos.
    categories = {"trend": 70, "risk": 40, "kronos": None}
    _, used_without_kronos = scoring.composite_score(
        categories, weights=base,
        reliability={"graded_count": 100, "directional_accuracy": 10.0},
    )
    assert used_without_kronos == scoring.normalize_weights(base, exclude={"kronos"})


def test_storage_reads_sqlite_first_and_writes_json_mirror(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    path = str(tmp_path / "watchlists.json")
    monkeypatch.setattr(storage, "BACKUP_DIR", str(tmp_path / "backups"))
    os.makedirs(storage.BACKUP_DIR)
    db.kv_set(path, {"source": "sqlite"})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"source": "file"}, f)

    assert storage.load_json(path) == {"source": "sqlite"}
    storage.save_json(path, {"source": "updated"})
    assert db.kv_get(path) == {"source": "updated"}
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"source": "updated"}
    assert storage.list_backups(path)


def test_storage_promotes_legacy_json_to_sqlite(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    path = str(tmp_path / "legacy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"legacy": True}, f)
    assert storage.load_json(path) == {"legacy": True}
    assert db.kv_get(path) == {"legacy": True}


def test_startup_migration_imports_existing_json_documents(tmp_path, monkeypatch):
    data_dir = tmp_path / "assistant_data"
    data_dir.mkdir()
    legacy_path = data_dir / "watchlists.json"
    legacy_path.write_text('{"migrated": true}', encoding="utf-8")
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "kronos.sqlite3"))
    monkeypatch.setattr(db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_initialized", False)

    db.init_db(migrate_json=True)
    assert db.kv_get(str(legacy_path)) == {"migrated": True}
