# Pipeline upgrades merged from Grok ZIP

## What was integrated

### SQLite document persistence

The existing SQLite database (`KRONOS_DATABASE_PATH`, default `assistant_data/kronos.sqlite3`) is initialized at Flask startup and imports legacy JSON documents once. `assistant.storage` now tries SQLite first, promotes recoverable JSON/backup reads into SQLite, and continues writing the atomic JSON mirror and rotating backups. The existing database filename, grade schema, and file restore workflow are retained; JSON remains the fallback if SQLite is unavailable.

### Forecast uncertainty metadata and position-plan sizing

Forecast responses now expose `uncertainty_pct`, defined as the full low-to-high band width at the forecast horizon divided by the last observed close, in percentage points. For multi-run forecasts this is the sampled 10th-to-90th percentile width; for one-run forecasts it is the existing historical-volatility estimate. These are different estimates and neither is a calibrated probability. When context widens the displayed band, the width metadata is recomputed around the unchanged central path.

Position-plan share sizing scales its requested dollar risk budget using this width: 100% of the requested risk at or below 15%; it decreases linearly between 15% and 30%; it floors at 50% from 30% upward. Missing/invalid uncertainty leaves the requested risk unchanged. The plan reports the requested risk budget, effective budget/percentage, uncertainty width, and multiplier. It does not shift forecast prices, entry levels, or stops and does not place orders.

### Paper-grade reliability for screener ranking

Reliability summaries are queried from the existing idempotent `forecast_grades` table; there is no second counter table to drift out of sync. Queries can be scoped to ticker, the current user, and the same forecast horizon. Screener reliability weighting runs only after a valid Kronos forecast is produced and only after at least 10 matured, matched-horizon grades. Accuracy is shrunk toward a neutral 50% prior equivalent to 10 grades. A low smoothed accuracy (<45%) reduces Kronos weight by 25%; a high smoothed accuracy (≥65%) increases it by 10%; weights are normalized. This is a bounded ranking heuristic, not a calibrated estimate of future success. It can also inherit selection bias from which paper trades a user chose to track.

### Model import behavior

Kronos model classes are imported lazily on the first actual forecast, so app startup and pure helper tests do not load the heavyweight model stack prematurely. CPU thread settings and prediction execution are unchanged.

## Deliberately not merged

- Grok’s new multi-window/volatility-damped drift path was excluded because it changes the central point forecast and has not been established by a clean out-of-sample comparison.
- Analyst-target and context-covariate nudges were excluded. Context may explain risk and widen bands; it must not shift the point forecast in built-in forecast, web, or simulation flows.
- Grok’s replacement ticker-only grade counter was excluded because it is not idempotent and would discard position identity, user/horizon data, and existing grade history. Current per-position DB records remain the source of truth.
- Grok’s backtesting files/tests/docs were not copied because they remove safeguards and audit artifacts present in the current version. The current backtest implementation, current light-theme navbar crop, and the matching Home template comment are retained.
- The separate day-trade sizing adjustment was not connected: that path has no producer for the proposed forecast uncertainty scale, and a unitless scale must not be confused with percentage-point uncertainty.

## Changed files

`assistant/db.py`, `assistant/storage.py`, `assistant/forecaster.py`, `assistant/context_signal.py`, `assistant/position_plan.py`, `assistant/model_loader.py`, `assistant/screener/scoring.py`, `assistant/screener/kronos_integration.py`, `assistant/screener/engine.py`, `webapp/app.py`, `webapp/templates/invest.html`, `webapp/templates/screener.html`, `webapp/static/js/screener.js`, `.env.example`, `README.md`, and `tests/test_pipeline_merge.py`.

The separately retained current UI fix and its `UI_FIXES.md` remain included in the merged project archive.

## Validation

- `python3 -m pytest -q tests/`: **123 passed**.
- `compileall`, screener JavaScript syntax, and changed Jinja templates: passed.
- Flask test-client smoke checks for Home, Screener, Valuation, and the light hero asset: HTTP 200.
- The suite reports 21 upstream warnings (pytest parametrization deprecation and pandas weekday deprecation); no test failures.
