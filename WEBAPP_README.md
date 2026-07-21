# Kronos Web App

A browser front end that unifies everything built in `assistant/` and
`backtesting/` into one place: chat, manual data setup (ticker or your own
CSV), backtesting, and a watchlist. It's a thin layer -- every route calls
straight into `StockAssistant`, `assistant.data_fetcher`,
`assistant.forecaster`, `assistant.charts`, `assistant.watchlist`, or
`backtesting.runner.quick_backtest`, exactly like `chat_cli.py` and the
Discord/WhatsApp bots do. No new business logic lives in `webapp/`.

This is separate from the original `webui/` (which still works standalone,
CSV-only, untouched) -- `webapp/` is the recommended one going forward since
it's wired into the full assistant + backtesting stack.

## Run it

```bash
cd Kronos-master
python webapp/app.py
```
Then open **http://127.0.0.1:5050**. Change the port with `WEBAPP_PORT` in
`.env` if 5050 is taken.

## Pages

| Page | What it does |
|---|---|
| **Dashboard** (`/`) | Landing page, your watchlist at a glance, links into the other three flows. |
| **Chat** (`/chat`) | Same conversational assistant as the CLI/Discord/WhatsApp bots, over AJAX (`POST /api/chat`). Forecast charts show inline. |
| **Forecast** (`/forecast`) | Two tabs: **by ticker** (auto-fetches from Yahoo Finance, same as chat) or **upload CSV** (manual setup -- bring your own OHLCV file, no ticker required). |
| **Backtest** (`/backtest`) | Runs `quick_backtest()` -- the same walk-forward check available via the `backtest AAPL` chat command -- and shows the direction-summary chart plus a significance check against the best baseline. |
| **Watchlist** (`/watchlist`) | Add/remove tickers. Shared storage with the CLI/Discord/WhatsApp bots (`assistant_data/watchlists.json`) -- same list everywhere. |

## CSV upload format

Same schema as `backtesting/data_loaders.py:CSVLoader` (which the upload
route reuses directly): a date/timestamp column plus `open`, `high`, `low`,
`close`, `volume`. Column names are matched case-insensitively; `amount` is
computed automatically if your file doesn't have it. Needs at least 30 rows.

## Design notes

- **Direction**: a trading desk after hours -- ink-dark surfaces, one warm
  gold accent (ticker tape / clock hands), teal for gains, soft red for
  losses. `Fraunces` for display type (a serif with some personality,
  nodding at "Kronos" being an old idea applied to new markets), `Inter` for
  body copy, `IBM Plex Mono` for anything numeric -- tickers, prices,
  metrics -- so data reads like a terminal printout.
- **Signature element**: the dashboard hero is a clock face built from 24
  small candlesticks arranged in a circle, with a slowly sweeping gold
  hand (90s per rotation, `prefers-reduced-motion` respected) -- Kronos was
  the Greek personification of time, rendered here literally as market data.
  A simplified version of the same mark is the sidebar logo.
- **Session model**: each browser gets a random `user_id` in a Flask
  session cookie, used for watchlist and chat-context continuity within
  that browser -- there's no login system. If you want multi-user auth,
  that's the seam to extend (swap the session-based ID for a real account
  system and everything downstream -- watchlist, chat context -- already
  keys off `user_id`).
- Charts are served from `assistant_data/charts/` and
  `assistant_data/backtests/` directly via a small `/media/<root>/<file>`
  route rather than copied into `static/` -- one less thing to keep in sync.

## What I'd recommend adding next (not built -- time/scope)

- **Auth**, if this ever needs to run somewhere other than your own
  machine -- right now anyone who can reach the port has full access
  (forecast, backtest, watchlist). Fine for `127.0.0.1`, not fine to expose
  publicly as-is.
- **Progress feedback for backtests** -- `quick_backtest` can take a while
  on CPU-only hardware and the request currently just blocks until it's
  done. A polling job-status endpoint (start job -> poll `/status/<id>`)
  would avoid a browser timeout on slower machines.
- **Interactive Plotly embeds** instead of static PNGs -- `assistant/charts.py`
  already builds a Plotly figure (`build_forecast_chart`) alongside the PNG;
  wiring `fig.to_html(full_html=False)` into the forecast/chat results would
  give the same hover/zoom/indicator-toggle experience the CLI's saved
  `last_chart.html` has, directly in the page.
- **A settings page** for the `.env` values currently only editable by hand
  (model choice, temperature, CPU threads, lookback) -- would remove the
  last reason to touch a text editor for day-to-day use.
