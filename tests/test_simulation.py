"""
Tests for assistant/simulation.py -- fully mocked price/history/forecast
sources (no network, no model, no real filesystem), covering: buying
(cash deduction, forecast snapshot, insufficient funds), selling
(realized P&L, FIFO matching, partial sells), mark-to-market on read,
and forecast grading (not-yet-due vs. graded, direction-correct logic).
"""
import time

import pandas as pd
import pytest

from assistant import simulation


def _fake_hist(n=30, last_close=100.0):
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="B"),
        "open": [last_close] * n, "high": [last_close + 1] * n,
        "low": [last_close - 1] * n, "close": [last_close] * n,
        "volume": [1000] * n, "amount": [100000.0] * n,
    })


class _FakeStorage:
    """In-memory stand-in for simulation._load/_save -- avoids touching
    assistant.storage/the real filesystem at all (same reasoning as the
    screener history tests)."""
    def __init__(self):
        self.data = {}


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    fake = _FakeStorage()

    def fake_save(data):
        fake.data = data

    monkeypatch.setattr(simulation, "_load", lambda: fake.data)
    monkeypatch.setattr(simulation, "_save", fake_save)
    monkeypatch.setattr(simulation, "validate_ticker", lambda t: (True, t.upper()))
    monkeypatch.setattr(simulation, "SIMULATION_STARTING_CASH", 10000.0)
    monkeypatch.setattr(simulation, "SIMULATION_FORECAST_HORIZON", 14)
    yield fake


def _mock_price_and_forecast(monkeypatch, price=100.0, forecast_price=110.0, hist_n=30):
    monkeypatch.setattr(simulation, "_current_price", lambda ticker: price)
    monkeypatch.setattr(simulation.data_fetcher, "fetch_history",
                         lambda ticker, lookback_days=None: _fake_hist(hist_n, price))

    def fake_run_forecast(hist_df, pred_len, n_runs=1):
        last_date = hist_df["timestamps"].max()
        future_dates = pd.date_range(start=last_date + pd.offsets.BDay(1), periods=pred_len, freq="B")
        return {
            "pred_df": pd.DataFrame({"timestamps": future_dates, "close": [forecast_price] * pred_len}),
        }
    monkeypatch.setattr(simulation.forecaster, "run_forecast", fake_run_forecast)


def test_buy_deducts_cash_and_creates_position(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    position = simulation.buy("user1", "AAPL", dollars=1000.0)

    assert position["ticker"] == "AAPL"
    assert position["shares"] == pytest.approx(10.0)
    assert position["entry_price"] == 100.0
    assert position["cost_basis"] == 1000.0

    portfolio = simulation.get_portfolio("user1", mark_to_market=False)
    assert portfolio["cash"] == pytest.approx(9000.0)
    assert len(portfolio["positions"]) == 1


def test_buy_records_forecast_snapshot(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0, forecast_price=110.0)
    position = simulation.buy("user1", "AAPL", dollars=1000.0)

    fc = position["forecast"]
    assert fc["made_at_price"] == 100.0
    assert fc["forecast_price"] == 110.0
    assert fc["expected_return_pct"] == 10.0
    assert fc["trend"] == "bullish"
    assert fc["horizon_days"] == 14


def test_buy_by_shares_instead_of_dollars(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=50.0)
    position = simulation.buy("user1", "MSFT", shares=4)
    assert position["shares"] == 4
    assert position["cost_basis"] == 200.0


def test_buy_rejects_insufficient_funds(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    with pytest.raises(simulation.SimulationError, match="Not enough demo cash"):
        simulation.buy("user1", "AAPL", dollars=999999.0)


def test_buy_rejects_zero_amount(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    with pytest.raises(simulation.SimulationError):
        simulation.buy("user1", "AAPL", dollars=0)


def test_buy_requires_dollars_or_shares(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    with pytest.raises(simulation.SimulationError):
        simulation.buy("user1", "AAPL")


def test_sell_full_position_realizes_pnl(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)  # 10 shares @ 100

    monkeypatch.setattr(simulation, "_current_price", lambda ticker: 120.0)
    closed = simulation.sell("user1", "AAPL")

    assert len(closed) == 1
    assert closed[0]["realized_pnl"] == pytest.approx(200.0)  # (120-100)*10
    assert closed[0]["realized_pnl_pct"] == pytest.approx(20.0)

    portfolio = simulation.get_portfolio("user1", mark_to_market=False)
    assert portfolio["positions"] == []
    assert portfolio["cash"] == pytest.approx(9000.0 + 1200.0)  # remaining cash + proceeds
    assert len(portfolio["closed_trades"]) == 1


def test_sell_partial_position(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)  # 10 shares

    monkeypatch.setattr(simulation, "_current_price", lambda ticker: 110.0)
    closed = simulation.sell("user1", "AAPL", shares=4)

    assert closed[0]["shares"] == 4
    portfolio = simulation.get_portfolio("user1", mark_to_market=False)
    assert len(portfolio["positions"]) == 1
    assert portfolio["positions"][0]["shares"] == pytest.approx(6.0)


def test_sell_with_no_open_position_raises(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    with pytest.raises(simulation.SimulationError, match="No open"):
        simulation.sell("user1", "AAPL")


def test_sell_more_than_owned_raises(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)  # 10 shares
    with pytest.raises(simulation.SimulationError, match="available to sell"):
        simulation.sell("user1", "AAPL", shares=999)


def test_sell_is_fifo_across_two_buys(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    first = simulation.buy("user1", "AAPL", dollars=500.0)  # 5 shares
    _mock_price_and_forecast(monkeypatch, price=200.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)  # 5 more shares @ 200

    monkeypatch.setattr(simulation, "_current_price", lambda ticker: 250.0)
    closed = simulation.sell("user1", "AAPL", shares=5)
    # Should have sold from the FIRST (cheaper, entry_price=100) lot first.
    assert closed[0]["entry_price"] == 100.0


def test_mark_to_market_computes_unrealized_pnl(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)

    monkeypatch.setattr(simulation, "_current_price", lambda ticker: 130.0)
    portfolio = simulation.get_portfolio("user1", mark_to_market=True)

    pos = portfolio["positions"][0]
    assert pos["current_price"] == 130.0
    assert pos["unrealized_pnl"] == pytest.approx(300.0)  # (130-100)*10
    assert pos["unrealized_pnl_pct"] == pytest.approx(30.0)
    assert portfolio["total_value"] == pytest.approx(9000.0 + 1300.0)


def test_grading_not_due_yet_returns_none(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0, forecast_price=110.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)  # target date ~14 business days out

    portfolio = simulation.get_portfolio("user1", mark_to_market=True)
    assert portfolio["positions"][0]["graded"] is None


def test_grading_correct_direction(monkeypatch):
    monkeypatch.setattr(simulation, "_current_price", lambda ticker: 100.0)
    hist_df = _fake_hist(30, 100.0)
    monkeypatch.setattr(simulation.data_fetcher, "fetch_history",
                         lambda ticker, lookback_days=None: hist_df)

    # A forecast whose target date is already in the past relative to
    # "now", so get_portfolio's mark-to-market grades it immediately.
    past_target = pd.Timestamp.now() - pd.Timedelta(days=5)

    def fake_run_forecast(hist_df, pred_len, n_runs=1):
        return {"pred_df": pd.DataFrame({
            "timestamps": [past_target], "close": [110.0],
        })}
    monkeypatch.setattr(simulation.forecaster, "run_forecast", fake_run_forecast)

    simulation.buy("user1", "AAPL", dollars=1000.0)

    # The "actual" price at/after the target date, from history -- make
    # the real outcome also bullish (up from 100 -> 115) so direction
    # should grade as correct.
    future_hist = pd.concat([
        hist_df,
        pd.DataFrame({"timestamps": [past_target + pd.Timedelta(days=1)],
                      "open": [115.0], "high": [116.0], "low": [114.0],
                      "close": [115.0], "volume": [1000], "amount": [100000.0]}),
    ], ignore_index=True)
    monkeypatch.setattr(simulation.data_fetcher, "fetch_history",
                         lambda ticker, lookback_days=None: future_hist)

    portfolio = simulation.get_portfolio("user1", mark_to_market=True)
    grade = portfolio["positions"][0]["graded"]
    assert grade is not None
    assert grade["direction_correct"] is True
    assert grade["actual_return_pct"] == pytest.approx(15.0)


def test_reset_portfolio_restores_starting_cash(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)
    simulation.reset_portfolio("user1")
    portfolio = simulation.get_portfolio("user1", mark_to_market=False)
    assert portfolio["cash"] == 10000.0
    assert portfolio["positions"] == []
    assert portfolio["closed_trades"] == []


def test_portfolios_are_isolated_per_user(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)
    p2 = simulation.get_portfolio("user2", mark_to_market=False)
    assert p2["cash"] == 10000.0
    assert p2["positions"] == []


def test_win_rate_and_forecast_accuracy_summary(monkeypatch):
    _mock_price_and_forecast(monkeypatch, price=100.0)
    simulation.buy("user1", "AAPL", dollars=1000.0)
    monkeypatch.setattr(simulation, "_current_price", lambda ticker: 150.0)
    simulation.sell("user1", "AAPL")  # winning trade

    portfolio = simulation.get_portfolio("user1", mark_to_market=False)
    assert portfolio["closed_trade_count"] == 1
    assert portfolio["win_rate_pct"] == 100.0
