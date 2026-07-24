"""
A small static directory of common tickers + company names, used only for
autocomplete suggestions while typing (webapp/app.py:/api/tickers/search).
Deliberately not live-fetched -- this needs to respond instantly on every
keystroke, and doesn't need to be exhaustive (assistant.ticker_utils
already validates and accepts any real ticker beyond this list; this file
only affects what shows up as a suggestion).
"""

TICKER_DIRECTORY = [
    ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corp."), ("GOOGL", "Alphabet Inc."),
    ("AMZN", "Amazon.com Inc."), ("META", "Meta Platforms Inc."), ("TSLA", "Tesla Inc."),
    ("NVDA", "NVIDIA Corp."), ("AMD", "Advanced Micro Devices"), ("INTC", "Intel Corp."),
    ("NFLX", "Netflix Inc."), ("DIS", "Walt Disney Co."), ("BA", "Boeing Co."),
    ("JPM", "JPMorgan Chase & Co."), ("BAC", "Bank of America Corp."), ("WFC", "Wells Fargo & Co."),
    ("GS", "Goldman Sachs Group"), ("V", "Visa Inc."), ("MA", "Mastercard Inc."),
    ("PYPL", "PayPal Holdings"), ("SQ", "Block Inc."), ("COIN", "Coinbase Global"),
    ("KO", "Coca-Cola Co."), ("PEP", "PepsiCo Inc."), ("MCD", "McDonald's Corp."),
    ("SBUX", "Starbucks Corp."), ("NKE", "Nike Inc."), ("WMT", "Walmart Inc."),
    ("TGT", "Target Corp."), ("COST", "Costco Wholesale"), ("HD", "Home Depot Inc."),
    ("LOW", "Lowe's Companies"), ("XOM", "Exxon Mobil Corp."), ("CVX", "Chevron Corp."),
    ("PFE", "Pfizer Inc."), ("JNJ", "Johnson & Johnson"), ("UNH", "UnitedHealth Group"),
    ("MRNA", "Moderna Inc."), ("ABBV", "AbbVie Inc."), ("LLY", "Eli Lilly and Co."),
    ("ORCL", "Oracle Corp."), ("CRM", "Salesforce Inc."), ("ADBE", "Adobe Inc."),
    ("IBM", "IBM Corp."), ("CSCO", "Cisco Systems"), ("QCOM", "Qualcomm Inc."),
    ("TXN", "Texas Instruments"), ("UBER", "Uber Technologies"), ("LYFT", "Lyft Inc."),
    ("ABNB", "Airbnb Inc."), ("SHOP", "Shopify Inc."), ("SPOT", "Spotify Technology"),
    ("SNAP", "Snap Inc."), ("PINS", "Pinterest Inc."), ("RBLX", "Roblox Corp."),
    ("F", "Ford Motor Co."), ("GM", "General Motors Co."), ("RIVN", "Rivian Automotive"),
    ("LCID", "Lucid Group"), ("PLTR", "Palantir Technologies"), ("SNOW", "Snowflake Inc."),
    ("NET", "Cloudflare Inc."), ("DDOG", "Datadog Inc."), ("CRWD", "CrowdStrike Holdings"),
    ("ZM", "Zoom Video Communications"), ("DOCU", "DocuSign Inc."), ("TWLO", "Twilio Inc."),
    ("BABA", "Alibaba Group"), ("JD", "JD.com Inc."), ("PDD", "PDD Holdings"),
    ("TSM", "Taiwan Semiconductor"), ("ASML", "ASML Holding"), ("SONY", "Sony Group Corp."),
    ("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ Trust"), ("DIA", "SPDR Dow Jones ETF"),
    ("IWM", "iShares Russell 2000 ETF"), ("VTI", "Vanguard Total Stock Market ETF"),
    ("XLK", "Technology Select Sector SPDR"), ("XLF", "Financial Select Sector SPDR"),
    ("XLE", "Energy Select Sector SPDR"), ("ARKK", "ARK Innovation ETF"),
    ("GLD", "SPDR Gold Shares"), ("SLV", "iShares Silver Trust"),
    ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
    ("DOGE-USD", "Dogecoin"), ("XRP-USD", "XRP"), ("BNB-USD", "BNB"),
    ("^GSPC", "S&P 500 Index"), ("^IXIC", "NASDAQ Composite"), ("^DJI", "Dow Jones Industrial"),
    ("^VIX", "CBOE Volatility Index"),
]


def search_tickers(query, limit=8):
    """Case-insensitive prefix/substring match against symbol or name."""
    if not query:
        return []
    q = query.strip().lower()
    starts = [(sym, name) for sym, name in TICKER_DIRECTORY if sym.lower().startswith(q)]
    contains = [(sym, name) for sym, name in TICKER_DIRECTORY
                if not sym.lower().startswith(q) and (q in sym.lower() or q in name.lower())]
    return (starts + contains)[:limit]
