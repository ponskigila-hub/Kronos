"""
JSON-friendly facade over the vendored day-trade tools.

Web / chat call these functions; they never touch Claude and never place
broker orders. Heavy network work (Yahoo charts) is expected — callers should
run them in background jobs when used from Flask.
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any, Optional

# Local modules (same package)
from . import entry as entry_mod
from . import exit_plan as exit_mod
from . import scan as scan_mod
from . import size as size_mod


# Default liquid universe for quick scans (page-friendly; not thousands of names)
DEFAULT_SCAN_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO",
    "JPM", "BAC", "XOM", "CVX", "UNH", "LLY", "V", "MA", "COST", "WMT",
    "CRM", "ORCL", "ADBE", "INTC", "QCOM", "MU", "AMAT", "NOW", "SNOW", "PLTR",
    "COIN", "SQ", "SHOP", "UBER", "ABNB", "DIS", "BA", "CAT", "GS", "SPY",
]


class DayTradeError(Exception):
    """User-facing day-trade error."""


def _json_safe(obj: Any) -> Any:
    """Make nested structures JSON-serializable (drop private keys, datetimes)."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    # Decimal from exit planner
    try:
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return float(obj)
    except Exception:
        pass
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).startswith("_"):
                continue
            try:
                out[str(k)] = _json_safe(v)
            except Exception:
                out[str(k)] = str(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# Entry timer
# ---------------------------------------------------------------------------
def check_entry(
    ticker: str,
    setup: str = "orb",
    interval: str = "5m",
    or_minutes: int = 15,
    level: Optional[float] = None,
    min_volume_x: Optional[float] = None,
) -> dict:
    """
    Check whether an entry has triggered for ticker (opening-range breakout
    or a level close-through). Returns status: triggered | waiting | expired | no-data.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise DayTradeError("Enter a ticker.")
    setup = (setup or "orb").lower()
    if setup not in ("orb", "level"):
        raise DayTradeError("Setup must be 'orb' or 'level'.")
    if setup == "level" and level is None:
        raise DayTradeError("Level setup needs a price level.")

    try:
        chart = entry_mod.get_chart(ticker, interval)
    except Exception as e:
        raise DayTradeError(f"Could not load chart for {ticker}: {e}") from e

    now = entry_mod.utc_now()
    try:
        res = entry_mod.evaluate(
            chart,
            now,
            setup=setup,
            or_minutes=int(or_minutes),
            interval=interval,
            level=float(level) if level is not None else None,
            min_volume_x=float(min_volume_x) if min_volume_x is not None else None,
        )
    except entry_mod.EntryError as e:
        raise DayTradeError(str(e)) from e
    except Exception as e:
        raise DayTradeError(f"Entry check failed: {e}") from e

    return _json_safe(res)


# ---------------------------------------------------------------------------
# Exit planner
# ---------------------------------------------------------------------------
def plan_exit(
    ticker: str,
    entry_price: float,
    stop_rule: str = "or_low",
    stop_param: Optional[float] = None,
    target_rule: str = "r",
    target_param: float = 2.0,
    or_high: Optional[float] = None,
    or_low: Optional[float] = None,
    shares: Optional[float] = None,
) -> dict:
    """
    Compute stop / target from entry and rules (OR low, ATR, %, fixed price, R-multiple).
    Does not place orders.
    """
    ticker = (ticker or "").strip().upper()
    try:
        entry_price = float(entry_price)
    except (TypeError, ValueError) as e:
        raise DayTradeError("Entry price must be a number.") from e
    if entry_price <= 0:
        raise DayTradeError("Entry price must be positive.")

    # If OR levels missing, try to infer from today's chart
    if (or_high is None or or_low is None) and stop_rule in ("or_low", "or_high"):
        try:
            chart = entry_mod.get_chart(ticker, "5m")
            now = entry_mod.utc_now()
            er = entry_mod.evaluate(chart, now, setup="orb", or_minutes=15, interval="5m")
            oran = er.get("opening_range") or {}
            or_high = or_high if or_high is not None else oran.get("high")
            or_low = or_low if or_low is not None else oran.get("low")
        except Exception:
            pass

    try:
        plan = exit_mod.compute(
            entry_price,
            stop_rule,
            stop_param,
            target_rule,
            target_param,
            or_high=or_high,
            or_low=or_low,
            shares=shares,
        )
    except Exception as e:
        # exit_plan may raise various errors
        raise DayTradeError(f"Exit plan failed: {e}") from e

    plan = dict(plan) if isinstance(plan, dict) else {"raw": plan}
    plan["ticker"] = ticker
    plan["entry_price"] = entry_price
    return _json_safe(plan)


# ---------------------------------------------------------------------------
# Daily pattern scanner (limited universe — web-friendly)
# ---------------------------------------------------------------------------
def scan_daily_setups(
    symbols: Optional[list] = None,
    min_price: float = 5.0,
    min_volume: float = 0,
    setups_filter: Optional[list] = None,
) -> dict:
    """
    Scan daily charts for classic setups: new_high_20, bull_flag, reclaim_ma20,
    oversold, oversold_bounce. Uses a modest default universe so a web request
    finishes in reasonable time.
    """
    symbols = [s.strip().upper() for s in (symbols or DEFAULT_SCAN_UNIVERSE) if s and s.strip()]
    symbols = list(dict.fromkeys(symbols))  # dedupe, keep order
    if len(symbols) > 60:
        symbols = symbols[:60]

    now_utc = datetime.datetime.utcnow().replace(microsecond=0)
    hits = []
    errors = []

    data, failed = {}, {}
    try:
        data, failed = scan_mod.fetch_spark(symbols, "3mo", "1d", pause=0.12)
    except Exception as e:
        raise DayTradeError(f"Daily scan fetch failed: {e}") from e
    for sym, err in (failed or {}).items():
        errors.append(f"{sym}: {err}")

    try:
        rows, counts, last_date = scan_mod.scan_daily(data, symbols, now_utc, min_price, min_volume)
    except Exception as e:
        raise DayTradeError(f"Daily scan failed: {e}") from e

    for row in rows or []:
        setups = row.get("setups") or []
        if isinstance(setups, str):
            setups = [setups]
        if setups_filter:
            setups = [s for s in setups if s in setups_filter]
        if not setups:
            continue
        hits.append({
            "symbol": row.get("symbol"),
            "setups": setups,
            "close": row.get("price") or row.get("close"),
            "volume": row.get("volume"),
            "rsi": row.get("rsi"),
            "close_date": row.get("close_date"),
        })

    return _json_safe({
        "mode": "daily",
        "scanned": len(symbols),
        "counts": counts,
        "last_date": last_date.isoformat() if last_date else None,
        "hits": hits,
        "errors": errors,
        "as_of": now_utc.isoformat() + "Z",
        "note": "Scan matches chart rules only — not a buy list. No orders are placed.",
    })


def scan_orb_quick(
    symbols: Optional[list] = None,
    or_minutes: int = 15,
    min_price: float = 5.0,
) -> dict:
    """
    Opening-range breakout scan on a small liquid universe using 5-minute bars.
    Stage-1 spark filter + limited confirm. Best during US regular hours.
    """
    symbols = [s.strip().upper() for s in (symbols or DEFAULT_SCAN_UNIVERSE[:25]) if s and s.strip()]
    symbols = list(dict.fromkeys(symbols))[:30]
    now_utc = datetime.datetime.utcnow().replace(microsecond=0)

    try:
        window = scan_mod.orb_window(now_utc, at=None, or_minutes=or_minutes, until=None)
    except Exception as e:
        raise DayTradeError(f"Could not determine ORB window: {e}") from e

    # window may be a tuple (day, cutoff, ...) — handle flexibly
    day = None
    cutoff = None
    if isinstance(window, (list, tuple)) and len(window) >= 2:
        day, cutoff = window[0], window[1]
    elif isinstance(window, dict):
        day = window.get("day")
        cutoff = window.get("cutoff")

    hits = []
    errors = []
    try:
        stage1, failed = scan_mod.fetch_spark(symbols, "1d", "5m", pause=0.15)
        for sym, err in (failed or {}).items():
            errors.append(f"{sym}: {err}")
    except Exception as e:
        raise DayTradeError(f"ORB stage-1 fetch failed: {e}") from e

    try:
        if day is not None and cutoff is not None:
            rows = scan_mod.scan_orb(
                stage1, symbols, day, cutoff, or_minutes,
                min_price=min_price, min_volume=0, confirm=None,
            )
        else:
            # Fallback: evaluate entry per symbol
            rows = []
            for sym in symbols:
                try:
                    r = check_entry(sym, setup="orb", interval="5m", or_minutes=or_minutes)
                    if r.get("status") == "triggered":
                        rows.append(r)
                except Exception as ex:
                    errors.append(f"{sym}: {ex}")
            return _json_safe({
                "mode": "orb",
                "scanned": len(symbols),
                "hits": rows,
                "errors": errors,
                "as_of": now_utc.isoformat() + "Z",
                "note": "ORB via per-symbol entry check (window helper unavailable).",
            })
    except Exception as e:
        # Fallback path
        rows = []
        for sym in symbols[:15]:
            try:
                r = check_entry(sym, setup="orb", interval="5m", or_minutes=or_minutes)
                if r.get("status") == "triggered":
                    rows.append(r)
            except Exception as ex:
                errors.append(f"{sym}: {ex}")
        return _json_safe({
            "mode": "orb",
            "scanned": len(symbols),
            "hits": rows,
            "errors": errors + [str(e)],
            "as_of": now_utc.isoformat() + "Z",
            "note": "ORB fallback via entry checks.",
        })

    for row in rows or []:
        hits.append(_json_safe(row if isinstance(row, dict) else {"raw": row}))

    return _json_safe({
        "mode": "orb",
        "scanned": len(symbols),
        "hits": hits,
        "errors": errors,
        "as_of": now_utc.isoformat() + "Z",
        "note": "Opening-range breakouts only. Not a buy recommendation.",
    })


# ---------------------------------------------------------------------------
# Position sizing (budget)
# ---------------------------------------------------------------------------
def suggest_size(
    account_equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
) -> dict:
    """Shares to buy so that a stop-out loses ~risk_pct of equity."""
    try:
        account_equity = float(account_equity)
        risk_pct = float(risk_pct)
        entry = float(entry)
        stop = float(stop)
    except (TypeError, ValueError) as e:
        raise DayTradeError("All sizing inputs must be numbers.") from e
    if account_equity <= 0 or entry <= 0:
        raise DayTradeError("Equity and entry must be positive.")
    risk_per_share = abs(entry - stop)
    if risk_per_share < 1e-9:
        raise DayTradeError("Stop is too close to entry.")
    risk_dollars = account_equity * (risk_pct / 100.0)
    shares = int(risk_dollars // risk_per_share)
    cost = shares * entry
    return {
        "shares": shares,
        "cost": round(cost, 2),
        "risk_dollars": round(risk_dollars, 2),
        "risk_per_share": round(risk_per_share, 4),
        "risk_pct": risk_pct,
        "entry": entry,
        "stop": stop,
        "note": "Risk-based size only. Does not place an order.",
    }


def pipeline_ticket(ticker: str, equity: float = 100000, risk_pct: float = 0.5) -> dict:
    """
    End-to-end day-trade ticket for one symbol:
      entry check (ORB) → if triggered/waiting, build exit plan → size position.
    """
    ticker = (ticker or "").strip().upper()
    entry_res = check_entry(ticker, setup="orb", interval="5m", or_minutes=15)
    oran = entry_res.get("opening_range") or {}
    or_high = oran.get("high")
    or_low = oran.get("low")

    # Infer a working entry price
    trigger = entry_res.get("trigger") or {}
    last = entry_res.get("last") or {}
    entry_price = (
        trigger.get("price")
        or last.get("close")
        or last.get("price")
        or or_high
    )
    out = {
        "ticker": ticker,
        "entry_check": entry_res,
        "exit_plan": None,
        "size": None,
    }
    if entry_price and or_low:
        try:
            out["exit_plan"] = plan_exit(
                ticker,
                float(entry_price),
                stop_rule="or_low",
                target_rule="r",
                target_param=2.0,
                or_high=or_high,
                or_low=or_low,
            )
            stop = (out["exit_plan"] or {}).get("stop") or or_low
            out["size"] = suggest_size(equity, risk_pct, float(entry_price), float(stop))
        except DayTradeError as e:
            out["exit_error"] = str(e)
    return _json_safe(out)
