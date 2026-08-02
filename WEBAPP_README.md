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
| **Chat** (`/chat`) | Same conversational assistant as the CLI/Discord/WhatsApp bots, over AJAX (`POST /api/chat`). Forecast charts and sparklines show inline, quick-reply chips suggest follow-ups, a ticker autocomplete dropdown helps while typing, chat history survives a page refresh, and a Beginner/Advanced toggle controls how technical the explanations are. |
| **Forecast** (`/forecast`) | Two tabs: **by ticker** (auto-fetches from Yahoo Finance, same as chat) or **upload CSV** (manual setup -- bring your own OHLCV file, no ticker required). A "detailed multi-path chart" checkbox switches to the slower spaghetti-plot visualization (several sampled paths + mean + confidence band). |
| **Backtest** (`/backtest`) | Runs `quick_backtest()` -- the same walk-forward check available via the `backtest AAPL` chat command -- and shows the direction-summary chart plus a significance check against the best baseline. |
| **Watchlist** (`/watchlist`) | Per-ticker cards with the latest price (auto-refreshing), next earnings date + estimated quarter, a buy-range entry zone you set yourself (flagged in/above/below once a price is known), free-text notes (autosaved), and a correlation matrix across everything on your list once you have 2+. Shared ticker list with the CLI/Discord/WhatsApp bots (`assistant_data/watchlists.json`); notes and entry zones are web-app-only for now. |

## CSV upload format

Same schema as `backtesting/data_loaders.py:CSVLoader` (which the upload
route reuses directly): a date/timestamp column plus `open`, `high`, `low`,
`close`, `volume`. Column names are matched case-insensitively; `amount` is
computed automatically if your file doesn't have it. Needs at least 30 rows.

## Watchlist page features

**Latest price** -- `assistant/fundamentals.py:get_live_price()` via yfinance's
`.info` payload. Session-aware: shows whether the price is from **pre-market**,
**regular hours**, **after-hours**, or the **last regular close while the
market's closed**, each with its own badge (pulsing dot when the market is
open) and an "as of HH:MM" timestamp converted to your browser's local
time. Labeled "latest price," not "live," on purpose: Yahoo Finance's
free/unauthenticated data is typically delayed ~15-20 minutes during market
hours, not true tick-by-tick. The page polls `/api/watchlist/prices` every
45 seconds to keep it reasonably current without hammering Yahoo Finance.
Pre/post-market data isn't available for every ticker type (crypto trades
24/7 and has none, for instance) -- falls back to the regular/last price
when that's the case.

**Next earnings date + quarter** -- `assistant/fundamentals.py:get_next_earnings_info()`.
The date itself comes straight from yfinance. The *quarter* label (e.g.
"Q3 2026") is a **heuristic estimate**, not authoritative: it assumes a
standard January-December fiscal year and infers which quarter is being
reported from the report month. Companies with a non-calendar fiscal year
(Apple's ends in September, for instance) will show a quarter that's off
by one from how that company actually labels it -- hence "(est.)" always
shown alongside it. Good enough to know roughly what's coming; don't quote
it as the company's own label.

**Entry zone** -- a price range you set yourself (`assistant/watchlist_extras.py`),
purely a personal annotation, not a recommendation Kronos generated. The
badge (in zone / above / below) is a simple comparison against the latest
price, recalculated on every price poll.

**Notes** -- free-text per ticker, autosaved on blur (`assistant/watchlist_extras.py`).
No formatting, no AI involvement -- just a place to jot down your own
thesis so it doesn't live only in your head.

Both notes and entry zones are stored in `assistant_data/watchlist_notes.json`
and `assistant_data/watchlist_entry_zones.json`, keyed by the same
session-based `user_id` as the watchlist itself -- back them up along with
`assistant_data/` if that matters to you.

## "It's actually running" feedback

Forecast, backtest, CSV upload, and the correlation matrix all trigger a
real Kronos call that can take anywhere from a few seconds to a couple of
minutes on CPU-only hardware -- previously the page just sat there with no
feedback while that happened. Now a full-screen loading overlay (spinner +
message, e.g. "Running forecast…") appears the moment you submit, and the
submit button disables so you can't accidentally fire it twice
(`webapp/static/js/loading.js`, wired up via a `data-loading-message`
attribute on the relevant forms/links -- reusable for any future
slow-running form). The watchlist page also shows a skeleton-loading
shimmer on price/earnings while `/api/watchlist/details` is still
fetching, and the chat's "thinking" state is an animated three-dot
indicator instead of static text.

## Watchlist data safety

Your watchlist, notes, and entry zones live in `assistant_data/` and are
**never touched by code updates** -- extracting a new zip over your project
folder only replaces `.py`/`.html`/`.js`/`.css` files, never anything under
`assistant_data/`. Three things back this up further:
- `.gitignore` now excludes `assistant_data/` outright, so it can't end up
  reset by a `git pull`/checkout if you're using version control.
- Every write to the watchlist/notes/entry-zone JSON files is a
  read-modify-write (`assistant/watchlist.py`, `assistant/watchlist_extras.py`)
  -- there's no code path that overwrites the whole file wholesale.
- A **Backup & restore** section on the Watchlist page lets you download a
  portable JSON snapshot (tickers + notes + entry zones) and, if you ever
  want to, restore it elsewhere. Import is strictly additive: it adds
  tickers you don't already have and fills in notes/zones only for
  tickers that don't already have one -- it can never overwrite or delete
  anything currently saved.

## Design notes

**UI polish pass**: subtle hover elevation on cards, smoother transitions
throughout (nav, buttons, inputs, toggles), a dark custom scrollbar instead
of the browser default, and a soft page fade-in on navigation. All
respects `prefers-reduced-motion` -- animations (the clockface sweep, the
market-open pulse dot, the page fade-in) turn off automatically if the
user's OS has reduced-motion enabled.

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
