"""Transparent, user-specified peer valuation; not an intrinsic-value model.

The module intentionally returns relative multiples and scenario ranges rather
than a single fair-value target. Provider data are secondary and may be stale
or incomplete. The calculations are deterministic and easy to test offline.
"""
from datetime import datetime, timezone
import math
import re
import numpy as np


_TICKER_RE = re.compile(r"^[A-Z0-9.^=-]{1,15}$")
_MIN_PEERS_PER_METHOD = 3


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value):
    value = _number(value)
    return value if value is not None and value > 0 else None


def _to_profile(symbol, raw):
    """Keep only required, non-personal fields from the provider response."""
    price = _positive(raw.get("currentPrice")) or _positive(raw.get("regularMarketPrice"))
    market_time = raw.get("regularMarketTime")
    if isinstance(market_time, (int, float)):
        try:
            market_time = datetime.fromtimestamp(market_time, tz=timezone.utc).isoformat(timespec="seconds")
        except (ValueError, OSError, OverflowError):
            market_time = None
    profile = {
        "ticker": symbol,
        "name": raw.get("longName") or raw.get("shortName") or symbol,
        "price": price,
        "currency": raw.get("currency"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "market_cap": _positive(raw.get("marketCap")),
        "trailing_pe": _positive(raw.get("trailingPE")),
        "forward_pe": _positive(raw.get("forwardPE")),
        "price_to_sales": _positive(raw.get("priceToSalesTrailing12Months")),
        "price_to_book": _positive(raw.get("priceToBook")),
        "ev_to_ebitda": _positive(raw.get("enterpriseToEbitda")),
        "forward_eps": _positive(raw.get("forwardEps")),
        "revenue_per_share": _positive(raw.get("revenuePerShare")),
        "book_value_per_share": _positive(raw.get("bookValue")),
        "ebitda": _positive(raw.get("trailingEbitda")),
        "shares_outstanding": _positive(raw.get("sharesOutstanding")),
        "total_debt": _number(raw.get("totalDebt")),
        "total_cash": _number(raw.get("totalCash")),
        "revenue_growth": _number(raw.get("revenueGrowth")),
        "earnings_growth": _number(raw.get("earningsGrowth")),
        "profit_margin": _number(raw.get("profitMargins")),
        "free_cash_flow": _number(raw.get("freeCashflow")),
        "regular_market_time": market_time,
    }
    if profile["revenue_per_share"] is None:
        revenue = _positive(raw.get("totalRevenue"))
        shares = profile["shares_outstanding"]
        if revenue is not None and shares:
            profile["revenue_per_share"] = revenue / shares
    return profile


def _build_method(name, formula, target_input, peer_key, peers, pricing_fn, target_multiple=None):
    usable = [(peer, peer[peer_key]) for peer in peers if _positive(peer.get(peer_key)) is not None]
    if target_input is None or len(usable) < _MIN_PEERS_PER_METHOD:
        return None
    ratios = sorted(value for _, value in usable)
    q25, median, q75 = [float(x) for x in np.quantile(ratios, [0.25, 0.5, 0.75])]
    implied = [pricing_fn(mult) for mult in (q25, median, q75)]
    return {
        "name": name,
        "formula": formula,
        "company_multiple": target_multiple,
        "peer_median_multiple": median,
        "peer_q25_multiple": q25,
        "peer_q75_multiple": q75,
        "peer_count": len(usable),
        "peer_symbols": [peer["ticker"] for peer, _ in usable],
        "implied_low": implied[0],
        "implied_mid": implied[1],
        "implied_high": implied[2],
    }


def analyze_profiles(ticker, peer_tickers, target, peer_profiles):
    """Compute a valuation summary from normalized profiles (offline-testable)."""
    price = _positive(target.get("price"))
    if price is None:
        raise ValueError("No usable current share price was returned for the target ticker.")
    peers = [p for p in peer_profiles if p and p.get("ticker") != ticker]
    warnings = [
        "Relative-comparison output only: it is not a DCF, intrinsic fair value, or a buy/sell signal.",
        "Peer list is user-selected; peer comparability is not independently established.",
        "Yahoo Finance summary data are secondary, may be delayed/incomplete, and statement publication dates are not verified point-in-time here.",
    ]
    if len(peers) < _MIN_PEERS_PER_METHOD:
        warnings.append("At least three peers with a valid multiple are required for each valuation method; some or all methods may be omitted.")

    methods = []
    forward_eps = _positive(target.get("forward_eps"))
    if forward_eps:
        method = _build_method(
            "Forward P/E", "Target forward EPS × peer forward P/E",
            forward_eps, "forward_pe", peers,
            lambda multiple: forward_eps * multiple,
            target.get("forward_pe"),
        )
        if method:
            methods.append(method)

    revenue_ps = _positive(target.get("revenue_per_share"))
    if revenue_ps:
        method = _build_method(
            "Price / Sales", "Target trailing revenue per share × peer P/S",
            revenue_ps, "price_to_sales", peers,
            lambda multiple: revenue_ps * multiple,
            target.get("price_to_sales"),
        )
        if method:
            methods.append(method)

    book_ps = _positive(target.get("book_value_per_share"))
    if book_ps:
        method = _build_method(
            "Price / Book", "Target book value per share × peer P/B",
            book_ps, "price_to_book", peers,
            lambda multiple: book_ps * multiple,
            target.get("price_to_book"),
        )
        if method:
            methods.append(method)

    ebitda = _positive(target.get("ebitda"))
    shares = _positive(target.get("shares_outstanding"))
    debt, cash = _number(target.get("total_debt")), _number(target.get("total_cash"))
    if ebitda and shares and debt is not None and cash is not None:
        net_debt = debt - cash
        method = _build_method(
            "EV / EBITDA", "(Peer EV/EBITDA × target EBITDA − target net debt) ÷ diluted shares",
            ebitda, "ev_to_ebitda", peers,
            lambda multiple: ((multiple * ebitda - net_debt) / shares)
            if (multiple * ebitda - net_debt) > 0 else None,
            target.get("ev_to_ebitda"),
        )
        if method:
            methods.append(method)

    for method in methods:
        for key in ("implied_low", "implied_mid", "implied_high"):
            value = _positive(method.get(key))
            method[key] = round(value, 4) if value is not None else None
        mid = method.get("implied_mid")
        method["upside_vs_price_pct"] = round((mid / price - 1) * 100, 2) if mid else None

    method_mids = [m["implied_mid"] for m in methods if m.get("implied_mid")]
    summary = None
    if len(method_mids) >= 2:
        relative_mid = float(np.median(method_mids))
        relative_upside = (relative_mid / price - 1) * 100
        if relative_upside >= 15:
            label = "Potential relative discount vs selected peers"
        elif relative_upside <= -15:
            label = "Potential relative premium vs selected peers"
        else:
            label = "Near the selected-peer reference range"
        summary = {
            "method_count": len(method_mids),
            "median_peer_implied_price": round(relative_mid, 4),
            "upside_vs_price_pct": round(relative_upside, 2),
            "label": label,
        }
    else:
        warnings.append("Fewer than two valuation methods passed data-availability checks; no combined peer reference is shown.")

    target_sector = target.get("sector")
    sector_mismatches = [p["ticker"] for p in peers if target_sector and p.get("sector") and p["sector"] != target_sector]
    if sector_mismatches:
        warnings.append("Different Yahoo sector classification from target: " + ", ".join(sector_mismatches) + ". Review peer suitability manually.")
    target_industry = target.get("industry")
    industry_mismatches = [p["ticker"] for p in peers if target_industry and p.get("industry") and p["industry"] != target_industry]
    if industry_mismatches:
        warnings.append("Different Yahoo industry classification from target: " + ", ".join(industry_mismatches) + ". Multiple dispersion may reflect business-model differences.")

    metrics = [
        ("Trailing P/E", target.get("trailing_pe")),
        ("Forward P/E", target.get("forward_pe")),
        ("Price / Sales", target.get("price_to_sales")),
        ("Price / Book", target.get("price_to_book")),
        ("EV / EBITDA", target.get("ev_to_ebitda")),
        ("Revenue growth YoY", target.get("revenue_growth"), "percent"),
        ("Earnings growth YoY", target.get("earnings_growth"), "percent"),
        ("Profit margin", target.get("profit_margin"), "percent"),
        ("Free-cash-flow yield", (target["free_cash_flow"] / target["market_cap"])
         if target.get("free_cash_flow") is not None and target.get("market_cap") else None, "percent"),
    ]
    snapshot = []
    for item in metrics:
        label, value, *unit = item
        if value is not None:
            snapshot.append({"name": label, "value": round(value * 100, 2) if unit and unit[0] == "percent" else round(float(value), 3),
                             "unit": "%" if unit and unit[0] == "percent" else "x"})
    return {
        "ticker": ticker,
        "company_name": target.get("name", ticker),
        "current_price": price,
        "currency": target.get("currency") or "currency not supplied",
        "sector": target.get("sector"),
        "industry": target.get("industry"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "price_as_of": target.get("regular_market_time"),
        "peer_tickers": [p["ticker"] for p in peers],
        "peer_profiles": [{"ticker": p["ticker"], "name": p.get("name"), "sector": p.get("sector"), "industry": p.get("industry")} for p in peers],
        "snapshot_metrics": snapshot,
        "methods": methods,
        "summary": summary,
        "warnings": warnings,
    }


def fetch_relative_valuation(ticker, peer_tickers):
    """Fetch one summary profile per requested ticker and compute peer ranges.

    Calls are sequential to reduce provider rate-limit pressure. All network
    work is intended for the webapp's background job, never its request thread.
    """
    from assistant.ticker_utils import looks_like_ticker
    symbols = [str(x).strip().upper() for x in [ticker, *peer_tickers] if str(x).strip()]
    if len(symbols) < 4 or len(symbols) > 9:
        raise ValueError("Enter one target and between 3 and 8 peer tickers.")
    if any(not _TICKER_RE.fullmatch(s) or not looks_like_ticker(s) for s in symbols):
        raise ValueError("One or more ticker symbols have an invalid format.")
    if len(set(symbols)) != len(symbols):
        raise ValueError("Target and peer tickers must be unique.")
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install project dependencies first: pip install -r requirements.txt") from exc

    profiles, failures = [], []
    target_profile = None
    for idx, symbol in enumerate(symbols):
        try:
            raw = yf.Ticker(symbol).info or {}
            profile = _to_profile(symbol, raw)
            if idx == 0:
                if profile.get("price") is None:
                    raise ValueError("provider returned no current price")
                target_profile = profile
            else:
                if not raw:
                    raise ValueError("provider returned no company data")
                profiles.append(profile)
        except Exception as exc:
            if idx == 0:
                raise ValueError(f"Could not load target {symbol}: {exc}") from exc
            failures.append(f"{symbol}: {exc}")
    result = analyze_profiles(symbols[0], symbols[1:], target_profile, profiles)
    result["unavailable_peers"] = failures
    if failures:
        result["warnings"].append("Some peer profiles could not be fetched: " + "; ".join(failures))
    return result
