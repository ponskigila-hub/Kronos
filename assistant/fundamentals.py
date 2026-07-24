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
