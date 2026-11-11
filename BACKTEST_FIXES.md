# Backtest Fixes — 2026-11-10 project progress

This patch was applied to the project in the newly supplied `backtesting.zip`, not to the earlier archive. It addresses accounting and validation defects; it does not claim that the forecast has a profitable edge.

## Findings and changes

| Area | Issue | Change |
|---|---|---|
| Capped walk-forward | `max_windows` stopped at the oldest part of history, potentially years before the latest data. | Capped runs now select the latest eligible chronological origins. A cap is still not a representative sample of every market regime. |
| Trade timing | Overlapping forecast trades were compounded sequentially as if each could use all capital simultaneously. | A single position is allowed per horizon. A signal that would enter before the prior trade exits is skipped; `overlap_skipped_origins` is reported. The forced always-long baseline follows the same rule. |
| Signal vs fill price | The predicted return used to generate a trade was measured from origin close even though entry is assumed at the next open. | Trading decisions now compare the forecast target with the assumed entry fill; forecast-accuracy metrics remain referenced to the origin close. |
| Equity / drawdown | Equity was observed only at trade endpoints, hiding losses inside the holding period. | The validator stores the daily close path; equity is marked each market bar while a position is open and carried flat while in cash. Starting capital is included in the drawdown high-water mark. |
| Risk metrics | Annualization did not match the equity observation cadence, and Sortino used an unsuitable downside calculation. | Daily-marked returns use 252 periods/year; Sortino uses RMS downside deviation versus a per-period risk-free hurdle. |
| Forecast metric alignment | Invalid values could shift previous prices relative to actual/predicted observations. | Direction and IC calculations now drop invalid rows jointly and keep observations aligned. |
| Direction interval | A small-sample direction interval could look like a formal confidence claim under dependent forecast errors. | Reliability note uses a Wilson interval labelled IID/rough and explicitly says serial/overlap dependence is not adjusted. |
| Tuning | Search defaulted to price RMSE and its NaN ordering could put invalid scores ahead under maximization. | Grid/random search defaults to return RMSE and consistently ranks invalid scores last. |
| Auditability | The run did not preserve enough inputs and artifacts to reconstruct its evaluation. | The full runner saves a manifest, input-bar snapshot, per-origin endpoint forecasts, trade logs and daily equity curves for both strategy and baseline. |

## Verification

`python3 -m compileall -q backtesting tests/test_backtesting_validation.py` passed. `python3 -m pytest -q tests/test_backtesting_validation.py tests/test_jobs.py` passed **18 tests**, including ten backtest regression cases. A synthetic quick-summary formatter smoke test also passed.

No live market-data fetch or Kronos model backtest was run. `yfinance` is not installed in the sandbox, so the broader `tests/test_simulation.py` collection is blocked by that missing dependency. These tests validate code behavior against fixtures, not real-market profitability.

## Remaining limitations

The configured provider's OHLC adjustment basis is not verified as point-in-time total return. Dividends, splits, delistings, ticker changes and survivorship can affect conclusions. Transaction cost remains an assumed 0.05% per side; spread, impact, borrow, margin, tax, liquidity and partial fills are not modeled. Horizons are evaluated separately and are not combined into one portfolio. A capped run focuses on the latest origins; after tuning, reserve an untouched final period. Diebold–Mariano results compare forecast loss with a baseline, not the statistical significance of trading profits.
