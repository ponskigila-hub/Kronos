from assistant import db


def test_forecast_grade_is_idempotent_and_summarizable(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "grades.sqlite"))
    monkeypatch.setattr(db, "_initialized", False)

    inserted = db.record_forecast_grade(
        "position-1", "user-1", "aapl", 14, 0.05, 0.08, True, 3.0, graded_at=123.0,
    )
    duplicate = db.record_forecast_grade(
        "position-1", "user-1", "AAPL", 14, 0.05, -0.08, False, 13.0, graded_at=124.0,
    )
    assert inserted is True
    assert duplicate is False

    all_summary = db.get_forecast_grade_summary()
    assert all_summary["count"] == 1
    assert all_summary["direction_accuracy_pct"] == 100.0
    assert all_summary["mean_absolute_error_pct"] == 3.0
    assert all_summary["mean_predicted_return"] == 0.05
    assert all_summary["mean_actual_return"] == 0.08
    assert db.get_forecast_grade_summary("MSFT")["count"] == 0
