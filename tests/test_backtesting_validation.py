import numpy as np
import pandas as pd

from backtesting.significance import compare_models_dm, diebold_mariano_test, holm_adjust
from backtesting.trading_simulator import TradingSimulator
from backtesting.walk_forward import WalkForwardValidator


def _bars(n=14):
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = np.arange(100.0, 100.0 + n)
    return pd.DataFrame({
        "timestamps": dates,
        "open": close + 0.25,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.full(n, 1000),
    })


def test_walk_forward_returns_one_endpoint_row_per_origin():
    df = _bars()
    validator = WalkForwardValidator(min_train_size=5, step_size=3, horizons=(2, 4))
    got = validator.run(df, lambda train, h: [999] * h, verbose=False)
    assert len(got[2]) == 2
    assert len(got[4]) == 2
    row = got[2].iloc[0]
    assert row["actual"] == df.iloc[6]["close"]
    assert row["predicted"] == 999
    assert row["entry_price"] == df.iloc[5]["open"]
    assert row["prev_actual"] == df.iloc[4]["close"]


def test_simulator_enters_after_signal_at_next_open():
    row = pd.DataFrame([{
        "split_date": pd.Timestamp("2024-01-01"),
        "entry_date": pd.Timestamp("2024-01-02"),
        "date": pd.Timestamp("2024-01-03"),
        "prev_actual": 100.0,
        "entry_price": 102.0,
        "predicted": 110.0,
        "actual": 108.0,
    }])
    trades, equity = TradingSimulator(transaction_cost=0).run(row, 1000)
    assert len(trades) == 1
    assert trades.iloc[0]["entry_price"] == 102
    assert np.isclose(trades.iloc[0]["realized_return"], 108 / 102 - 1)
    assert np.isclose(equity.iloc[-1]["equity"], 1000 * (108 / 102))


def test_dm_declines_to_claim_significance_with_too_few_origins():
    out = diebold_mariano_test(np.arange(12.0), np.arange(12.0) + 1, min_origins=20)
    assert np.isnan(out["p_value"])
    assert out["n_origins"] == 12
    assert "insufficient" in out["note"]


def test_dm_aligns_by_origin_and_holm_adjusts_family():
    dates = pd.bdate_range("2024-01-01", periods=25)
    a = pd.DataFrame({"split_date": dates, "date": dates, "actual": np.arange(25.0) + 10,
                      "predicted": np.arange(25.0) + 10})
    b = a.copy()
    b["predicted"] += np.linspace(1, 3, len(b))
    out = compare_models_dm(a, b, h=5, step_size=30)
    assert out["n_origins"] == 25
    assert out["better_model"] == "A"
    adjusted = holm_adjust([0.01, 0.04, np.nan])
    assert np.allclose(adjusted[:2], [0.02, 0.04])
    assert np.isnan(adjusted[2])
