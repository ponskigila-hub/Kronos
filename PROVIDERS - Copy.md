# Market Data Providers

The app's OHLCV history now goes through a `MarketDataProvider` interface
(`assistant/providers/`) instead of calling `yfinance` directly everywhere.
`assistant/data_fetcher.py` -- the module every other part of the app
actually imports -- keeps the exact same `fetch_history()` /
`fetch_multi()` / `TickerNotFoundError` contract it always had; only its
internals changed.

```
                 assistant/data_fetcher.py
              (fetch_history, fetch_multi -- unchanged
               public contract, still cached here)
                          |
                          v
              assistant/providers/__init__.py
           get_history_with_fallback(symbol, ...)
                          |
              +-----------+-----------+
              |                       |
              v                       v
     YFinanceProvider          TwelveDataProvider
     (default, no key)         (needs TWELVEDATA_API_KEY)
```

## Why this exists

The goal was never "replace yfinance" -- yfinance is free, needs no key,
and works fine for the app's actual usage pattern (daily bars, moderate
call volume, personal/small-scale deployment). The goal was to make
*swapping it out* a one-line config change instead of a multi-file
refactor, in case yfinance's unofficial API ever becomes unreliable or
you need a data type it doesn't cover well. `TwelveDataProvider` is a
second, fully working implementation -- not a stub -- specifically to
prove the interface is real.

## Configuration

```bash
# .env
MARKET_DATA_PROVIDER=yfinance          # default; no key needed
# MARKET_DATA_PROVIDER=twelvedata      # switch the primary provider
# MARKET_DATA_FALLBACK_PROVIDER=twelvedata   # optional: try this if the primary fails
# TWELVEDATA_API_KEY=your_key_here     # required only if using twelvedata
```

Fallback only activates on a hard failure (`ProviderDataError` -- symbol
not found, request failed, empty response), and it's a full replacement,
never a merge: if the primary partially succeeds, its output is used
as-is. Blending rows from two providers isn't done automatically because
they can disagree on adjusted-vs-unadjusted prices, corporate-action
handling, and session boundaries in ways that would silently corrupt the
history fed to Kronos -- better to cleanly fail over to the fallback
provider's own complete, internally-consistent history than to stitch
two sources together.

## Adding a third provider

1. Create `assistant/providers/my_provider.py` implementing
   `MarketDataProvider` (`get_history`, `validate_symbol`; see
   `assistant/providers/base.py` for the exact contract each must satisfy,
   including the shared `normalize()` step every provider should run its
   output through).
2. Register it in `assistant/providers/__init__.py`'s `_REGISTRY` dict.
3. Set `MARKET_DATA_PROVIDER=my_provider` (or `..._FALLBACK_PROVIDER=...`)
   in `.env`.

Nothing else in the app needs to change -- `data_fetcher.fetch_history()`
and every one of its 8 call sites (core_assistant, portfolio_analysis,
screener, webapp) are unaffected.

## Provider comparison

Evaluated against the app's actual needs: daily OHLCV for global equities
+ crypto tickers, moderate request volume (a handful of tickers per chat
session, not high-frequency polling), Python-friendly, and a genuinely
free tier since this is meant to stay deployable on free/affordable
infrastructure for a solo developer. Free-tier numbers below were checked
against current (2026) sources at the time this was written -- providers
change these without much notice, so verify on the provider's own
pricing page before depending on a specific number.

| Provider | Free tier (OHLCV) | Historical daily bars | Intraday | Global equities | Fundamentals | News | Notes |
|---|---|---|---|---|---|---|---|
| **yfinance** (current default) | Unlimited, unofficial | Yes, deep history | Yes (limited range) | Good coverage | Yes (unofficial) | Yes (unofficial) | No API key, no rate-limit contract -- it's an unofficial wrapper around Yahoo's endpoints, so it can break without warning. This is the main reason to have a real fallback option, not because it's currently unreliable. |
| **Twelve Data** (implemented here) | 800 calls/day, 8/min | Yes | Yes | Good (100k+ instruments, 50+ exchanges) | Paid tiers only | No | Official, documented, keyed API. Free tier is comfortably enough for occasional fallback use given yfinance stays primary; would need a paid plan ($29+/mo) if it became the primary source for a busy deployment. |
| **Finnhub** (already used for news) | 60 calls/min | Limited on free tier | Limited on free tier | US-focused | Basic, free | Yes, generous free tier | Already integrated in `assistant/news.py`. Its free-tier *candles* (OHLCV) endpoint is more restricted than its news/quote endpoints, which is why it isn't the OHLCV provider despite already being configured for news. |
| **Alpha Vantage** | ~25 requests/day | Yes | Yes | Good | Yes, 50+ indicators | No | Free tier is too thin (25/day) to be a serious history source for a chat app that can trigger several fetches per conversation; better suited to scheduled, low-frequency jobs. |
| **Polygon.io** (rebranded "Massive", Oct 2025) | Very limited / effectively paid-only | Free tier restricted to ~1 year history | Paid | Excellent (US-focused) | Paid | Paid | Best-in-class for latency and depth if you're paying; not a fit for "free/affordable infra" as the default. |
| **Financial Modeling Prep (FMP)** | Limited daily calls on free tier | Yes | Limited | Good | Strong (its main strength) | Yes | Worth a look specifically if fundamentals depth becomes more important than it is today; not adopted here because OHLCV was the gap, and FMP's edge is fundamentals, not history breadth. |
| **Alpaca** | Free with a (paper or funded) brokerage account | Yes | Yes, including real-time via WebSocket | US equities/crypto only | No | No | Real-time streaming is its strength, which this app doesn't currently need (daily-bar forecasting, not live trading). Requiring a brokerage account signup is also a heavier onboarding step than the others for a hobby deployment. |

### Recommendation

Keep **yfinance as the default** -- it already works, costs nothing, and
the app's request volume doesn't stress it. Use **Twelve Data as the
configured fallback** (`MARKET_DATA_FALLBACK_PROVIDER=twelvedata`) if you
want resilience against yfinance's occasional breakage without adding a
paid dependency for normal operation. Revisit Alpaca or Polygon/Massive
only if the project grows into needing real-time/intraday data, which is
a different use case than what Kronos (trained on daily-bar-style
context) is doing today.
