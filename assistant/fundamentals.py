"""
Fundamental data, earnings calendar, and analyst price targets -- all free
via yfinance's `Ticker.info` / `Ticker.calendar`, no API key and no Kronos
calls involved. Used both as standalone chat intents ("fundamentals AAPL",
"when does AAPL report earnings") and to enrich forecast explanations (a
forecast that spans an earnings date is inherently less certain).
"""
import datetime

import yfinance as yf

from .ticker_utils import validate_ticker


def _fmt_large(n):
    if n is None:
        return "n/a"
    n = float(n)
    for unit, div in [("T", 1e12), ("B", 1e9), ("M", 1e6)]:
        if abs(n) >= div:
            return f"{n / div:.2f}{unit}"
    return f"{n:.0f}"


def _fmt_pct(n):
    if n is None:
        return "n/a"
    return f"{float(n) * 100:.2f}%"


def _fmt_num(n, decimals=2):
    if n is None:
        return "n/a"
    return f"{float(n):.{decimals}f}"


def get_fundamentals(ticker):
    """
    Returns a dict of key valuation/company stats, or raises ValueError if
    the ticker doesn't exist. Fields are None where yfinance doesn't have
    data for that ticker (common for ETFs, indices, crypto -- which don't
    have a P/E ratio, for instance).
    """
    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise ValueError(f"'{ticker}' does not look like a valid ticker on Yahoo Finance.")

    info = yf.Ticker(symbol).info or {}
    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        # Some tickers (indices, certain ETFs) return a thin info dict --
        # still usable, just mostly None fields below.
        pass

    return {
        "ticker": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }


def format_fundamentals_text(data):
    lines = [f"{data['name']} ({data['ticker']})"]
    if data.get("sector"):
        lines.append(f"Sector: {data['sector']}" + (f" / {data['industry']}" if data.get("industry") else ""))
    lines.append(f"Market cap: {_fmt_large(data.get('market_cap'))}")
    lines.append(f"P/E (trailing / forward): {_fmt_num(data.get('pe_ratio'))} / {_fmt_num(data.get('forward_pe'))}")
    lines.append(f"EPS (trailing / forward): {_fmt_num(data.get('eps'))} / {_fmt_num(data.get('forward_eps'))}")
    lines.append(f"Revenue growth (YoY): {_fmt_pct(data.get('revenue_growth'))}")
    lines.append(f"Profit margin: {_fmt_pct(data.get('profit_margin'))}")
    if data.get("dividend_yield"):
        lines.append(f"Dividend yield: {_fmt_pct(data.get('dividend_yield'))}")
    lines.append(f"Beta: {_fmt_num(data.get('beta'))}")
    if data.get("fifty_two_week_low") and data.get("fifty_two_week_high"):
        lines.append(f"52-week range: {data['fifty_two_week_low']:.2f} - {data['fifty_two_week_high']:.2f}")
    return "\n".join(lines)


def get_earnings_date(ticker):
    """
    Returns the nearest upcoming earnings date as a datetime.date, or None
    if unavailable (many ETFs/indices/crypto don't have one).
    """
    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise ValueError(f"'{ticker}' does not look like a valid ticker on Yahoo Finance.")

    try:
        t = yf.Ticker(symbol)
        dates_df = t.get_earnings_dates(limit=8)
        if dates_df is None or dates_df.empty:
            return None
        today = datetime.datetime.now(dates_df.index.tz) if dates_df.index.tz else datetime.datetime.now()
        upcoming = dates_df[dates_df.index >= today]
        if upcoming.empty:
            return None
        return upcoming.index[-1].date()  # earliest upcoming (index sorted descending by yfinance)
    except Exception:
        return None


def estimate_reporting_quarter(report_date):
    """
    Companies report earnings ~4-6 weeks after a quarter closes, so the
    calendar quarter *of the report date* is usually one quarter ahead of
    the quarter being reported on. This is a heuristic based on a standard
    Jan-Dec fiscal year -- it will be off by one quarter for companies with
    a non-calendar fiscal year (e.g. Apple's fiscal year ends in
    September), so it's labeled "estimated" everywhere it's shown rather
    than treated as an authoritative fiscal-quarter label.
    """
    if report_date is None:
        return None
    month = report_date.month
    year = report_date.year
    if month <= 3:
        return f"Q4 {year - 1} (est.)"
    elif month <= 6:
        return f"Q1 {year} (est.)"
    elif month <= 9:
        return f"Q2 {year} (est.)"
    else:
        return f"Q3 {year} (est.)"


def get_next_earnings_info(ticker):
    """
    Convenience combo used by the watchlist UI: returns
    {"date": datetime.date | None, "quarter": str | None, "days_until": int | None}
    """
    earnings_date = get_earnings_date(ticker)
    if earnings_date is None:
        return {"date": None, "quarter": None, "days_until": None}
    return {
        "date": earnings_date,
        "quarter": estimate_reporting_quarter(earnings_date),
        "days_until": (earnings_date - datetime.date.today()).days,
    }


def _epoch_to_iso(value):
    """yfinance returns market-time fields as either a Unix epoch (int) or
    an ISO string depending on version -- handle both, return None rather
    than raise if the format is unrecognized."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
        else:
            dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.isoformat()
    except (ValueError, OSError, TypeError):
        return None


_SESSION_LABELS = {
    "pre": "Pre-Market",
    "regular": "Market Open",
    "post": "After-Hours",
    "closed": "Market Closed",
}


def get_live_price(ticker):
    """
    Latest available price, aware of which trading session it's from:
    pre-market, regular hours, after-hours, or last close while closed.
    Uses yfinance's `.info` (not `fast_info`) since only `.info` carries
    the pre/post-market fields and `marketState`.

    Note this is Yahoo Finance's data, which for free/unauthenticated
    access is typically delayed ~15-20 minutes during market hours, not
    true tick-by-tick real-time -- labeled "latest price" in the UI rather
    than "live" for that reason. Field availability (especially the
    pre/post-market fields and exact timestamps) can vary by ticker type --
    ETFs/indices/crypto often don't have pre/post-market data at all, in
    which case this falls back to the regular/last price.

    Returns None if unavailable, otherwise:
        {
          "price": float,               the price to display right now
          "prev_close": float | None,   previous regular-session close
          "change_pct": float | None,   % change vs. prev_close
          "session": "pre"|"regular"|"post"|"closed",
          "session_label": "Pre-Market"|"Market Open"|"After-Hours"|"Market Closed",
          "as_of": ISO datetime string | None,   when this price was last updated
        }
    """
    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise ValueError(f"'{ticker}' does not look like a valid ticker on Yahoo Finance.")

    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None
    if not info:
        return None

    market_state = (info.get("marketState") or "CLOSED").upper()
    session = {"PRE": "pre", "PREPRE": "pre", "REGULAR": "regular",
               "POST": "post", "POSTPOST": "post"}.get(market_state, "closed")

    regular_price = info.get("regularMarketPrice") or info.get("currentPrice")
    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
    regular_time = info.get("regularMarketTime")

    price, change_pct, as_of_raw = regular_price, info.get("regularMarketChangePercent"), regular_time

    # Prefer the pre/post-market price + change when that's the active
    # session and yfinance actually has that data for this ticker (not
    # every ticker type -- e.g. crypto trades 24/7 and has no such fields).
    if session == "pre" and info.get("preMarketPrice") is not None:
        price = info["preMarketPrice"]
        change_pct = info.get("preMarketChangePercent")
        as_of_raw = info.get("preMarketTime")
    elif session == "post" and info.get("postMarketPrice") is not None:
        price = info["postMarketPrice"]
        change_pct = info.get("postMarketChangePercent")
        as_of_raw = info.get("postMarketTime")

    if price is None:
        return None
    if change_pct is None and prev_close:
        change_pct = (price - prev_close) / prev_close * 100

    return {
        "price": float(price),
        "prev_close": float(prev_close) if prev_close else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "session": session,
        "session_label": _SESSION_LABELS.get(session, "Market Closed"),
        "as_of": _epoch_to_iso(as_of_raw),
    }


def earnings_within_horizon(ticker, pred_len):
    """Convenience check used by assistant.explain -- True if the next
    earnings date falls within the next `pred_len` calendar days."""
    try:
        earnings_date = get_earnings_date(ticker)
    except ValueError:
        return None
    if earnings_date is None:
        return None
    days_out = (earnings_date - datetime.date.today()).days
    if 0 <= days_out <= pred_len * 1.5:  # rough calendar-day buffer for trading-day horizons
        return earnings_date
    return None


def get_analyst_targets(ticker):
    """
    Returns Wall Street analyst price targets and consensus rating, or a
    dict of Nones if unavailable (common for ETFs, indices, small/foreign
    caps that analysts don't cover).
    """
    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise ValueError(f"'{ticker}' does not look like a valid ticker on Yahoo Finance.")

    info = yf.Ticker(symbol).info or {}
    return {
        "ticker": symbol,
        "target_mean": info.get("targetMeanPrice"),
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "recommendation": info.get("recommendationKey"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }


def format_analyst_text(data):
    if not data.get("target_mean"):
        return f"No analyst coverage data available for {data['ticker']}."
    lines = [f"Analyst targets for {data['ticker']} ({data.get('num_analysts') or '?'} analysts):"]
    lines.append(f"Mean target: {_fmt_num(data.get('target_mean'))} "
                  f"(range {_fmt_num(data.get('target_low'))} - {_fmt_num(data.get('target_high'))})")
    if data.get("current_price") and data.get("target_mean"):
        upside = (data["target_mean"] - data["current_price"]) / data["current_price"] * 100
        lines.append(f"Implied upside from current price: {upside:+.1f}%")
    if data.get("recommendation"):
        lines.append(f"Consensus rating: {data['recommendation'].replace('_', ' ').title()}")
    return "\n".join(lines)
