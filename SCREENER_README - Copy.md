# Kronos Stock Screener

Ranks a universe of stocks on trend, momentum, volatility, liquidity, risk,
and relative strength, then optionally runs the existing Kronos forecasting
pipeline on just the top-ranked candidates. Lives entirely in
`assistant/screener/`; nothing in the core forecasting/backtesting code was
changed, and it reuses `assistant/data_fetcher.py`, `assistant/indicators.py`,
and `assistant/forecaster.py` rather than duplicating them. Web UI at
`/screener` (`webapp/templates/screener.html` + `webapp/static/js/screener.js`).

No API key required -- everything runs on price/volume data via yfinance,
same as the rest of the app.

## Pipeline

```
Universe -> Download (concurrent, cached) -> Metrics -> Filters
-> Score & Rank -> Top N -> Kronos -> Re-rank Top N -> Result
```

One bad/delisted/thin ticker is recorded with a reason and skipped -- it
never aborts the rest of the screen. The result always includes a data
quality summary (`scanned / analyzed / insufficient_history /
download_failed / low_liquidity / filtered_out`) plus a `skipped` list with
per-ticker reasons, so nothing is silently dropped.

## Module map

| Module | Responsibility |
|---|---|
| `universe.py` | S&P 500 / NASDAQ-100 / Dow 30 / watchlist / custom list / CSV upload |
| `data.py` | Concurrent downloads (`ThreadPoolExecutor`) + disk cache (`assistant_data/screener_cache/`, TTL-based) |
| `metrics.py` | All trend/momentum/volatility/liquidity/price-structure/risk/relative-strength calculations |
| `scoring.py` | Normalizes metrics into 0-100 category scores + a transparent weighted composite |
| `presets.py` | Named strategies (Momentum, Breakout, Trend Following, Pullback, Conservative, Kronos Candidates) |
| `filters.py` | `(metric, operator, value)` evaluation engine -- backs both presets and the custom filter builder |
| `reasons.py` | Plain-language "why it ranked here" bullets, generated directly from the metrics (no LLM) |
| `kronos_integration.py` | Runs `assistant.forecaster.run_forecast` on just the shortlisted candidates |
| `engine.py` | `run_screen(...)` -- orchestrates all of the above; callable programmatically, no Flask dependency |

## Universes

`sp500` / `nasdaq100` / `dow30` try a live refresh from a public source
first (cached ~1 day in `assistant_data/screener_cache/`), and fall back to
a bundled snapshot in `assistant/screener/data/*.txt` if that fails (no
internet, source unreachable). The **S&P 500 fallback is a reduced
~200-ticker snapshot**, not the full ~500 -- it exists so the screener still
works offline/degraded rather than failing outright. When the live refresh
succeeds (normal case with internet access) you get the real index instead.
For exact, guaranteed membership use **Custom list** or **CSV upload**.

## Scoring

Seven categories: `trend`, `momentum`, `relative_strength`, `volatility`,
`liquidity`, `risk`, `kronos`. Deliberately no separate "technical" bucket
layered on top of trend/momentum/volatility, since that would double-count
the same handful of correlated price moves. Weights default to
`assistant.config.SCREENER_CONFIG["weights"]` and are overridden per-preset;
if a category is unavailable for a ticker (e.g. `kronos` wasn't run), its
weight is dropped and the rest re-normalize to sum to 1.0 automatically --
see `scoring.normalize_weights`.

Signal classification (`scoring.classify_signal`) is never a bare BUY/SELL:
`Strong Candidate / Candidate / Neutral / Weak Candidate / High Risk`.

## Configuration

Engineering defaults live in `assistant/config.py:SCREENER_CONFIG` (edit
that dict directly -- these aren't secrets, so they're intentionally **not**
in `.env`):

```python
SCREENER_CONFIG = {
    "min_history_days": 150,
    "min_avg_dollar_volume": 1_000_000,
    "benchmark": "SPY",
    "lookback_days": 400,
    "preselection_count": 30,   # how many technically-ranked candidates advance to Kronos
    "final_count": 10,          # how many the UI highlights as "top candidates"
    "max_workers": 8,           # concurrent download threads
    "cache_ttl_minutes": 60,
    "weights": {...},
}
```

The web UI lets you override most of these per-run (universe, preset,
custom filters, min dollar volume, lookback, shortlist size, whether to run
Kronos, and the forecast horizon).

## Using it programmatically

```python
from assistant.screener import engine

result = engine.run_screen(
    universe_key="nasdaq100",
    preset_key="momentum",
    enable_kronos=True,
    pred_len=30,
)
for row in result["rows"]:
    print(row["rank"], row["ticker"], row["overall_score"], row["signal"])
```

Same function the web app's `/screener/run` route calls -- no Flask
dependency, works the same from a script, the CLI, or a bot.

## Intentional scope decisions (v1)

- **Fundamentals (market cap, P/E, revenue growth, ...) are not included.**
  `yfinance`'s `Ticker.info` call is slow (roughly half a second each) and
  the brief marks fundamentals as strictly optional/price-volume-first --
  fetching it for an entire universe (hundreds of tickers) would make a
  screen impractically slow. The architecture has a natural slot for it
  (score it only for the post-filter shortlist, not the whole universe) as
  a follow-up.
- **Historical backtesting of the screener itself** ("if I'd run this
  screen on this date, how did the top picks perform afterward?") is not
  included. Every metric in `metrics.py` is computed only from a ticker's
  own history up to its last available bar, so it's ready to be run on a
  truncated/point-in-time `df` without any change -- what's missing is the
  walk-forward harness (rolling screening dates + forward-return
  evaluation) around it, a natural next module.
- **Custom filters combine with AND only** (no OR / grouping). Covers all
  six built-in presets and any single-strategy custom screen; a full
  boolean-logic builder would be a UI-heavy addition for relatively rare
  extra value.
- Company names aren't shown in the results table (ticker only) --
  avoiding an extra slow `Ticker.info` call per row in the shortlist.
