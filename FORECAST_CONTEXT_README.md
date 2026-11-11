# Forecast context, uncertainty bands, and forward-grade analytics

This document describes the forecast/context and screener changes in this revision. They are additive: existing API fields and JSON paper portfolios remain in place, with new metadata added alongside them.

## Forecast bands

`assistant.forecaster.run_forecast()` now always returns `low_df`, `high_df`, and `band_source`.

- For `n_runs == 1`, the existing central forecast path is preserved. The extra range uses recent daily log-return volatility: `sigma_daily = sample_std(log(C_t / C_(t-1)))` over the latest 20 available returns (or all available returns for a shorter history). At forecast step `t`, `spread_t = forecast_close_t * 1.28 * sigma_daily * sqrt(t)`; the low/high paths are `forecast_close_t ± spread_t`. `band_source` is `analytical_vol`.
- For `n_runs > 1`, the existing empirical 10th/90th percentiles across sampled paths remain in use. `band_source` is `sampled`.
- The analytical range is a simple normal-approximation based on historical volatility. It is not a calibrated 80% confidence interval, does not quantify all model uncertainty, and does not imply actual 80% coverage. The chart and prose explicitly distinguish it from sampled paths.
- The range calculation and all widening operations leave `pred_df` untouched. The historical-volatility method version participates in the forecast cache key to avoid stale band results.
- Built-in chat forecast, web forecast, and paper-trading snapshot flows no longer apply the optional analyst-target covariate nudge to the point price. Analyst/news fundamentals remain context inputs. The legacy helper/config remain for external compatibility but are not invoked by these flows.

## Market regime context

`build_context_signal(..., hist_df=...)` optionally calls `backtesting.regimes.classify_regimes()` on the supplied history. When the classifier has enough data, it stores a combined label such as `bear_high_vol` in `ContextSignal.market_regime` and in `to_dict()`. Insufficient or invalid history yields `unknown`.

The classifier uses its existing defaults: a 60-bar trend window with ±5% thresholds and a 20-bar rolling-volatility classification. In `bear_high_vol`, the context sets a minimum `band_widen_factor` of 1.30 and adds an explicit note. This multiplier expands the forecast band around its central path; it does not change the model's direction or point price. Existing event-risk widening remains in force and the larger factor wins.

Forecast and Simulation pages display a Market badge. Paper-trading preview and existing holdings show the same context label. The label is contextual information, not a buy/sell instruction.

## SQLite forward-grade analytics

`assistant/db.py` creates a new `forecast_grades` table through the existing idempotent database initializer. The row uses `position_id` as its primary key, so repeated portfolio reads cannot count one matured paper forecast twice. No existing tables or JSON portfolio fields are removed.

`record_forecast_grade(...)` stores decimal returns (`0.05` means +5%), direction correctness, horizon, and `error_pct` in percentage points (for example, `3.0` means a 3 percentage-point absolute error). It returns whether a new row was inserted. `get_forecast_grade_summary(ticker=None)` returns count, direction accuracy percentage, mean absolute error percentage points, and mean predicted/actual decimal returns, overall or filtered by ticker.

When `simulation.get_portfolio()` grades a matured position, it writes the grade inside `try/except`. JSON grading and the portfolio response continue even if SQLite is unavailable. The existing persisted per-position JSON grade remains the user-facing record.

## Screener benchmark-regime weights

`assistant.screener.scoring.regime_adjusted_weights(base_weights, benchmark_df)` requires 200 valid close bars and compares the latest close with its 200-bar SMA. It returns `unknown` and unchanged weights when data are insufficient or malformed. Below SMA200 is `bear`; otherwise it is `bull`.

Automatic reweighting is deliberately gated to the `none` preset when no custom weights are supplied. In a bear regime it adds 0.05 each to risk, liquidity, and volatility; subtracts 0.08 from trend and 0.07 from momentum; and normalizes weights to sum to one. The change is recorded in `result.config_used` (`benchmark_regime`, `regime_adjustment_applied`, `weights`) and disclosed in the Screener result summary. A custom weighting or non-default preset is not overwritten; the benchmark regime is still reported for context. A bull regime does not shift weights.

## Files changed

- `assistant/forecaster.py`, `assistant/forecast_cache.py`: analytical band and cache versioning.
- `assistant/context_signal.py`, `assistant/core_assistant.py`, `assistant/simulation.py`, `webapp/app.py`: regime context flow and widening metadata.
- `assistant/charts.py`, `assistant/explain.py`, `webapp/static/js/forecast.js`, `webapp/templates/simulation.html`: source-accurate band labels and Market badges.
- `assistant/db.py`, `assistant/simulation.py`: persistent, idempotent forecast grade analytics.
- `assistant/screener/scoring.py`, `assistant/screener/engine.py`, `webapp/templates/screener.html`: gated benchmark-regime weights and disclosure.
- Regression tests: `tests/test_forecast_context_features.py`, `tests/test_forecast_grade_db.py`, `tests/test_screener_regime_weights.py`, plus `tests/test_simulation.py`.

## Limitations

The analytical band assumes recent return volatility is informative and uses a simple square-root-of-time scaling; jumps, volatility clustering, skew, changing regimes, corporate actions, and price floor effects are not modeled. It should not be treated as a probability guarantee. Regime-conditioned score weights are a heuristic ranking adjustment; they need out-of-sample evaluation before being treated as an improvement. Forward-grade summaries will be sparse until forecasts mature, and grades can depend on the market-data provider's history and timestamp availability.


## Validation

- `python3 -m compileall -q assistant backtesting benchmarking webapp tests`: passed.
- `python3 -m pytest tests/ -q`: **115 passed**. The run reported 21 non-failing warnings (mostly existing pandas weekday deprecation notices and one pytest parametrization deprecation).
- Flask smoke test: `/forecast`, `/simulation`, and `/screener` each returned HTTP 200.
- `webapp/static/js/forecast.js` passed `node --check`.
- Tests ran on CPU; no GPU is required. The app's existing background jobs remain server-side, so changing Chrome tabs does not cancel a submitted job.

A missing `benchmarking/model_benchmark.py` helper referenced by `tests/test_model_benchmark.py` was restored as a pure, side-effect-free aggregation/Markdown module so `pytest tests/` can collect and pass from this source archive.
