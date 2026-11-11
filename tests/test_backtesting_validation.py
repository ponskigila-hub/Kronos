import numpy as np
import pandas as pd

from backtesting.portfolio_metrics import compute_all, max_drawdown, sortino_ratio
from backtesting.metrics import direction_accuracy, information_coefficient
from backtesting.trading_simulator import TradingSimulator
from backtesting.walk_forward import WalkForwardValidator


def _bars(n=20):
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


def test_walk_forward_returns_endpoint_and_holding_path_after_next_open():
    df = _bars()
    validator = WalkForwardValidator(min_train_size=5, step_size=3, horizons=(2, 4))
    got = validator.run(df, lambda train, h: [999] * h, verbose=False)
    assert len(got[2]) == 4
    row = got[2].iloc[0]
    assert row["actual"] == df.iloc[6]["close"]
    assert row["predicted"] == 999
    assert row["entry_price"] == df.iloc[5]["open"]
    assert row["prev_actual"] == df.iloc[4]["close"]
    assert row["holding_dates"] == df.iloc[5:7]["timestamps"].tolist()
    assert row["holding_closes"] == df.iloc[5:7]["close"].tolist()


def test_max_windows_keeps_most_recent_eligible_origins():
    validator = WalkForwardValidator(min_train_size=10, step_size=5,
                                     horizons=(3,), max_windows=3)
    assert list(validator.split_indices(100)) == [(0, 85), (0, 90), (0, 95)]


def test_validator_rejects_invalid_configuration_and_bad_forecast():
    try:
        WalkForwardValidator(step_size=0)
        assert False, "zero step must fail"
    except ValueError:
        pass
    df = _bars()
    got = WalkForwardValidator(min_train_size=5, step_size=5,
                               horizons=(1,)).run(df, lambda train, h: [np.nan], verbose=False)
    assert got[1].empty


def _trade_row(split, entry, exit_, closes, dates, pred=110, actual=None, open_=100):
    actual = closes[-1] if actual is None else actual
    return {
        "split_date": pd.Timestamp(split), "entry_date": pd.Timestamp(entry),
        "date": pd.Timestamp(exit_), "prev_actual": 100.0, "entry_price": float(open_),
        "predicted": float(pred), "actual": float(actual),
        "holding_dates": [pd.Timestamp(d) for d in dates],
        "holding_closes": [float(x) for x in closes],
    }


def test_signal_return_is_measured_from_next_open_fill_not_origin_close():
    row = pd.DataFrame([{
        "split_date": pd.Timestamp("2024-01-01"),
        "entry_date": pd.Timestamp("2024-01-02"),
        "date": pd.Timestamp("2024-01-02"),
        "prev_actual": 100.0,
        "entry_price": 105.0,
        "predicted": 102.0,
        "actual": 100.0,
        "holding_dates": [pd.Timestamp("2024-01-02")],
        "holding_closes": [100.0],
    }])
    trades, _ = TradingSimulator(transaction_cost=0, threshold=0.01).run(row, 1000)
    assert trades.iloc[0]["direction"] == "short"
    assert np.isclose(trades.iloc[0]["forecast_return_from_origin"], 0.02)
    assert np.isclose(trades.iloc[0]["predicted_return"], 102 / 105 - 1)


def test_simulator_marks_daily_path_including_intra_trade_drawdown():
    row = _trade_row("2024-01-01", "2024-01-02", "2024-01-04",
                     [110, 80, 120], pd.bdate_range("2024-01-02", periods=3), actual=120)
    calendar = pd.DataFrame({"timestamps": pd.bdate_range("2024-01-01", periods=4)})
    trades, equity = TradingSimulator(transaction_cost=0).run(
        pd.DataFrame([row]), starting_capital=100, calendar_df=calendar)
    assert len(trades) == 1
    assert np.allclose(equity["equity"], [100, 110, 80, 120])
    assert np.isclose(max_drawdown(equity, 100), 80 / 110 - 1)


def test_simulator_skips_overlapping_positions_and_keeps_cash_flat():
    dates = pd.bdate_range("2024-01-01", periods=7)
    first = _trade_row(dates[0], dates[1], dates[3], [101, 102, 103], dates[1:4])
    overlapping = _trade_row(dates[1], dates[2], dates[4], [102, 103, 104], dates[2:5])
    after_exit = _trade_row(dates[3], dates[4], dates[6], [103, 104, 105], dates[4:7])
    calendar = pd.DataFrame({"timestamps": dates})
    trades, equity = TradingSimulator(transaction_cost=0).run(
        pd.DataFrame([first, overlapping, after_exit]), 100, calendar_df=calendar)
    assert len(trades) == 2
    assert trades.attrs["overlap_skipped"] == 1
    assert equity["date"].tolist() == list(dates)
    assert equity["equity"].iloc[0] == 100  # initial capital at evaluation origin
    assert np.isclose(equity["equity"].iloc[1], 101)  # entry-day close mark


def test_costs_are_charged_on_both_sides_and_baseline_uses_same_fill_logic():
    dates = pd.bdate_range("2024-01-01", periods=3)
    row = _trade_row(dates[0], dates[1], dates[2], [110, 110], dates[1:], actual=110)
    sim = TradingSimulator(transaction_cost=0.001)
    trades, equity = sim.run(pd.DataFrame([row]), 1000,
                             calendar_df=pd.DataFrame({"timestamps": dates}))
    baseline, baseline_equity = sim.run(pd.DataFrame([row]), 1000, force_signal=1,
                                        calendar_df=pd.DataFrame({"timestamps": dates}))
    expected = 1000 * (1 - 0.001) * 1.1 * (1 - 0.001)
    assert np.isclose(equity["equity"].iloc[-1], expected)
    assert np.isclose(trades.iloc[0]["pnl_return"], expected / 1000 - 1)
    assert np.allclose(equity["equity"], baseline_equity["equity"])
    assert trades.iloc[0]["direction"] == baseline.iloc[0]["direction"] == "long"


def test_short_equity_cannot_recover_after_total_loss_without_margin_model():
    dates = pd.bdate_range("2024-03-01", periods=3)
    row = _trade_row(dates[0], dates[1], dates[2], [250, 150], dates[1:],
                     pred=90, actual=150)
    _, equity = TradingSimulator(transaction_cost=0).run(
        pd.DataFrame([row]), 100,
        calendar_df=pd.DataFrame({"timestamps": dates}))
    assert equity["equity"].iloc[-1] == 0


def test_drawdown_includes_starting_capital_and_sortino_uses_rms_downside():
    equity = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=3),
                           "equity": [80.0, 90.0, 110.0]})
    assert np.isclose(max_drawdown(equity, starting_capital=100), -0.2)
    sortino_data = pd.DataFrame({"date": pd.bdate_range("2024-02-01", periods=4),
                                 "equity": [100.0, 110.0, 100.0, 120.0]})
    daily = np.array([0.10, 100.0 / 110.0 - 1.0, 0.20])
    expected_sortino = daily.mean() / np.sqrt(np.mean(np.minimum(daily, 0.0) ** 2)) * np.sqrt(252)
    assert np.isclose(sortino_ratio(sortino_data, periods_per_year=252), expected_sortino)
    metrics = compute_all(pd.DataFrame(), equity, starting_capital=100,
                          periods_per_year=252)
    assert np.isclose(metrics["total_return_pct"], 10.0)
    assert np.isclose(metrics["max_drawdown_pct"], -20.0)


def test_direction_and_ic_drop_invalid_rows_without_shifting_reference_prices():
    actual = np.array([110.0, 90.0, 120.0])
    predicted = np.array([120.0, 80.0, 130.0])
    previous = np.array([np.nan, 100.0, 0.0])
    assert direction_accuracy(actual, predicted, previous) == 100.0
    assert np.isnan(information_coefficient(actual, predicted, previous))
