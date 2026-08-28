"""
Paper-trading simulation: a demo brokerage account funded with fake money
(like a Pluang/broker "demo mode"), so you can actually "buy" a ticker at
today's real price, let the position sit, and later see whether Kronos's
forecast from the day you bought it actually played out -- forward,
against real future prices, not a historical backtest window.

This is deliberately a different kind of validation than
backtesting/walk_forward.py: that framework re-plays many historical
windows to estimate Kronos's track record statistically. This module
tracks ONE live decision at a time, going forward from today, the way an
actual user deciding whether to trust a forecast would experience it.
Both are useful; neither replaces the other.

Storage follows the exact pattern assistant/watchlist.py and
assistant/screener/history.py already use: a simple per-user JSON blob
through assistant.storage (atomic writes, automatic backup/recovery).

No real money, brokerage account, or order ever touches this module --
"buy"/"sell" only ever debit/credit a number in a JSON file, at whatever
price assistant.fundamentals.get_live_price() (or the last close, as a
fallback) reports for that ticker right now.
"""
import threading
import time
import uuid

import pandas as pd

from . import storage, data_fetcher, fundamentals, forecaster
from .data_fetcher import TickerNotFoundError
from .ticker_utils import validate_ticker
from .config import SIMULATION_PATH, SIMULATION_STARTING_CASH, SIMULATION_FORECAST_HORIZON

_lock = threading.Lock()

# Below this magnitude, a forecast's implied direction is treated as
# "flat" rather than bullish/bearish when grading -- same threshold
# assistant/tools.py's get_kronos_forecast() uses for its own trend
# label, kept consistent so "what Kronos predicted" means the same thing
# here as everywhere else in the app.
FLAT_THRESHOLD_PCT = 0.5


class SimulationError(Exception):
    """User-facing errors: insufficient funds, no such position, bad
    ticker, etc. -- distinct from a bug, so callers can show the message
    directly instead of a generic failure."""
    pass


def _load():
    return storage.load_json(SIMULATION_PATH)


def _save(data):
    storage.save_json(SIMULATION_PATH, data)


def _new_portfolio():
    return {
        "starting_cash": SIMULATION_STARTING_CASH,
        "cash": SIMULATION_STARTING_CASH,
        "created_at": time.time(),
        "positions": [],       # open positions
        "closed_trades": [],   # sold positions (full sale history)
    }


def _current_price(ticker):
    """Best available "right now" price for a demo fill: live quote if
    available, otherwise the last close from history (covers tickers
    get_live_price() doesn't have full quote data for, and keeps this
    working even if that call fails for some transient reason)."""
    try:
        quote = fundamentals.get_live_price(ticker)
        if quote and quote.get("price"):
            return float(quote["price"])
    except Exception:
        pass
    hist_df = data_fetcher.fetch_history(ticker, lookback_days=5)
    return float(hist_df["close"].iloc[-1])


def _snapshot_forecast(ticker, hist_df):
    """Run a real Kronos forecast (benefits from assistant.forecast_cache
    like every other forecast in the app) and record just what's needed
    to grade it later: the predicted price at the horizon, the implied
    trend, and the calendar date that horizon actually lands on."""
    fc = forecaster.run_forecast(hist_df, pred_len=SIMULATION_FORECAST_HORIZON, n_runs=1)
    entry_price = float(hist_df["close"].iloc[-1])
    forecast_price = float(fc["pred_df"]["close"].iloc[-1])
    expected_return_pct = (forecast_price - entry_price) / entry_price * 100
    target_date = fc["pred_df"]["timestamps"].iloc[-1]
    return {
        "horizon_days": SIMULATION_FORECAST_HORIZON,
        "made_at_price": round(entry_price, 4),
        "forecast_price": round(forecast_price, 4),
        "expected_return_pct": round(expected_return_pct, 2),
        "trend": ("bullish" if expected_return_pct > FLAT_THRESHOLD_PCT
                   else "bearish" if expected_return_pct < -FLAT_THRESHOLD_PCT else "flat"),
        "target_date": target_date.isoformat(),
    }


def _grade_forecast(ticker, forecast, entry_date_iso):
    """
    If the forecast's target date has arrived, look up the actual close
    on (or nearest available trading day at/after) that date and compare
    it to what was predicted -- same "actual future price at the
    horizon" methodology backtesting/walk_forward.py uses, rather than
    just grabbing whatever the live price happens to be whenever someone
    next opens the app. Returns None if the target date hasn't arrived
    yet (nothing to grade), so callers can tell "not due yet" apart from
    "graded".
    """
    target_date = pd.Timestamp(forecast["target_date"])
    if pd.Timestamp.now(tz=target_date.tz) < target_date:
        return None

    try:
        # Enough lookback to comfortably span from entry to target date
        # regardless of horizon length.
        hist_df = data_fetcher.fetch_history(ticker, lookback_days=SIMULATION_FORECAST_HORIZON + 30)
    except TickerNotFoundError:
        return None

    on_or_after = hist_df[hist_df["timestamps"] >= target_date.tz_localize(None)]
    if on_or_after.empty:
        # Target date is in the future relative to the data we have (e.g.
        # provider lag) -- not gradeable yet even though the calendar
        # date has technically passed.
        return None
    actual_row = on_or_after.iloc[0]
    actual_price = float(actual_row["close"])
    made_at_price = forecast["made_at_price"]
    actual_return_pct = (actual_price - made_at_price) / made_at_price * 100
    predicted_return_pct = forecast["expected_return_pct"]

    actual_trend = ("bullish" if actual_return_pct > FLAT_THRESHOLD_PCT
                     else "bearish" if actual_return_pct < -FLAT_THRESHOLD_PCT else "flat")

    return {
        "graded_at": time.time(),
        "actual_date": actual_row["timestamps"].isoformat(),
        "actual_price": round(actual_price, 4),
        "actual_return_pct": round(actual_return_pct, 2),
        "predicted_return_pct": predicted_return_pct,
        "direction_correct": actual_trend == forecast["trend"],
        "forecast_error_pct": round(abs(actual_return_pct - predicted_return_pct), 2),
    }


def get_portfolio(user_id, mark_to_market=True):
    """
    The user's demo portfolio, with open positions annotated with a live
    unrealized P&L and (once due) a forecast grade -- computed fresh on
    read rather than a background job, since checking is cheap (one price
    lookup per open position) and this is explicitly meant to be checked
    on demand ("let it sit there and see").
    """
    with _lock:
        data = _load()
        portfolio = data.get(str(user_id)) or _new_portfolio()

    if mark_to_market and portfolio["positions"]:
        changed = False
        for pos in portfolio["positions"]:
            try:
                pos["current_price"] = round(_current_price(pos["ticker"]), 4)
            except Exception:
                pos["current_price"] = None
            if pos.get("current_price") is not None:
                pos["unrealized_pnl"] = round(
                    (pos["current_price"] - pos["entry_price"]) * pos["shares"], 2)
                pos["unrealized_pnl_pct"] = round(
                    (pos["current_price"] - pos["entry_price"]) / pos["entry_price"] * 100, 2)
            if pos.get("forecast") and not pos.get("graded"):
                try:
                    grade = _grade_forecast(pos["ticker"], pos["forecast"], pos["entry_date"])
                except Exception:
                    grade = None
                if grade is not None:
                    pos["graded"] = grade
                    changed = True
        if changed:
            with _lock:
                data = _load()
                if str(user_id) in data:
                    data[str(user_id)]["positions"] = portfolio["positions"]
                    _save(data)

    positions_value = sum(
        (p.get("current_price") or p["entry_price"]) * p["shares"] for p in portfolio["positions"]
    )
    portfolio["positions_value"] = round(positions_value, 2)
    portfolio["total_value"] = round(portfolio["cash"] + positions_value, 2)
    portfolio["total_return_pct"] = round(
        (portfolio["total_value"] - portfolio["starting_cash"]) / portfolio["starting_cash"] * 100, 2
    ) if portfolio["starting_cash"] else 0.0

    closed = portfolio["closed_trades"]
    portfolio["closed_trade_count"] = len(closed)
    wins = [t for t in closed if t.get("realized_pnl", 0) > 0]
    portfolio["win_rate_pct"] = round(len(wins) / len(closed) * 100, 1) if closed else None
    graded = [t.get("graded") for t in portfolio["positions"] + closed if t.get("graded")]
    correct = [g for g in graded if g.get("direction_correct")]
    portfolio["forecast_accuracy_pct"] = round(len(correct) / len(graded) * 100, 1) if graded else None

    return portfolio


def buy(user_id, ticker, dollars=None, shares=None):
    """
    "Buy" `ticker` with fake money at its current price, and snapshot a
    real Kronos forecast made at this same moment so it can be graded
    once its horizon passes. Exactly one of `dollars`/`shares` should be
    given (fractional shares are allowed, like most modern trading apps
    -- including Pluang -- support, since forcing whole shares would make
    small demo positions in expensive stocks awkward for no real reason).
    """
    if not dollars and not shares:
        raise SimulationError("Enter either a dollar amount or a number of shares to buy.")

    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise SimulationError(f"'{ticker}' does not look like a valid ticker.")
    ticker = symbol

    hist_df = data_fetcher.fetch_history(ticker, lookback_days=SIMULATION_FORECAST_HORIZON + 400)
    price = _current_price(ticker)
    if price <= 0:
        raise SimulationError(f"Couldn't get a usable price for '{ticker}'.")

    if shares:
        shares = float(shares)
        cost = shares * price
    else:
        cost = float(dollars)
        shares = cost / price

    if shares <= 0 or cost <= 0:
        raise SimulationError("Buy amount must be greater than zero.")

    with _lock:
        data = _load()
        portfolio = data.get(str(user_id)) or _new_portfolio()
        if cost > portfolio["cash"] + 1e-6:  # small epsilon for float rounding
            raise SimulationError(
                f"Not enough demo cash: this buy costs ${cost:,.2f} but you have "
                f"${portfolio['cash']:,.2f} available."
            )
        portfolio["cash"] = round(portfolio["cash"] - cost, 2)

        position = {
            "id": uuid.uuid4().hex,
            "ticker": ticker,
            "shares": round(shares, 6),
            "entry_price": round(price, 4),
            "entry_date": time.time(),
            "cost_basis": round(cost, 2),
            "forecast": _snapshot_forecast(ticker, hist_df),
            "graded": None,
        }
        portfolio["positions"].append(position)
        data[str(user_id)] = portfolio
        _save(data)

    return position


def sell(user_id, ticker, position_id=None, shares=None):
    """
    "Sell" an open position (or part of it) at the current price. If
    `position_id` isn't given, sells from the oldest open position(s) for
    that ticker first (FIFO), matching how most brokerages -- demo or
    real -- report cost basis by default. If `shares` isn't given, sells
    the entire matched position.
    """
    ticker = ticker.upper()
    price = _current_price(ticker)

    with _lock:
        data = _load()
        portfolio = data.get(str(user_id))
        if not portfolio or not portfolio["positions"]:
            raise SimulationError(f"No open {ticker} position to sell.")

        candidates = [p for p in portfolio["positions"]
                      if p["ticker"] == ticker and (position_id is None or p["id"] == position_id)]
        candidates.sort(key=lambda p: p["entry_date"])  # FIFO
        if not candidates:
            raise SimulationError(f"No open {ticker} position to sell.")

        remaining_to_sell = float(shares) if shares else sum(p["shares"] for p in candidates)
        if remaining_to_sell <= 0:
            raise SimulationError("Sell amount must be greater than zero.")

        closed_trades = []
        for pos in candidates:
            if remaining_to_sell <= 0:
                break
            sell_shares = min(pos["shares"], remaining_to_sell)
            remaining_to_sell -= sell_shares

            proceeds = sell_shares * price
            cost_basis_sold = sell_shares * pos["entry_price"]
            realized_pnl = proceeds - cost_basis_sold

            closed_trades.append({
                **{k: v for k, v in pos.items() if k not in ("shares", "cost_basis")},
                "shares": round(sell_shares, 6),
                "cost_basis": round(cost_basis_sold, 2),
                "exit_price": round(price, 4),
                "exit_date": time.time(),
                "realized_pnl": round(realized_pnl, 2),
                "realized_pnl_pct": round(realized_pnl / cost_basis_sold * 100, 2) if cost_basis_sold else 0.0,
                "holding_days": round((time.time() - pos["entry_date"]) / 86400, 1),
            })
            portfolio["cash"] = round(portfolio["cash"] + proceeds, 2)

            if sell_shares >= pos["shares"] - 1e-9:
                portfolio["positions"].remove(pos)
            else:
                pos["shares"] = round(pos["shares"] - sell_shares, 6)
                pos["cost_basis"] = round(pos["cost_basis"] - cost_basis_sold, 2)

        if remaining_to_sell > 1e-6:
            raise SimulationError(
                f"Only {sum(p['shares'] for p in candidates):.4f} shares of {ticker} available to sell."
            )

        portfolio["closed_trades"] = closed_trades + portfolio["closed_trades"]
        data[str(user_id)] = portfolio
        _save(data)

    return closed_trades


def reset_portfolio(user_id):
    """Wipe this user's demo portfolio and start over with fresh cash."""
    with _lock:
        data = _load()
        data[str(user_id)] = _new_portfolio()
        _save(data)
    return data[str(user_id)]
