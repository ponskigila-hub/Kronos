# Kronos Backtesting Framework

A walk-forward evaluation system for Kronos, built the way quant firms evaluate
forecasting models: rolling out-of-sample predictions, multiple horizons, a full
metrics suite, a trading simulation with realistic portfolio statistics, baseline
comparisons, residual diagnostics, market-regime robustness checks, and
hyperparameter search. Lives entirely in `backtesting/` + `run_backtest.py`;
nothing in `assistant/` or the original Kronos code was changed (the framework
reuses `assistant/data_fetcher.py` and `assistant/forecaster.py` rather than
duplicating them).

## Accuracy fixes (if you saw an "always predicts one direction" or level-mismatch result)

Three real issues were fixed based on a run that showed Kronos's synthetic
price jumping to a different level than the real price at the start of each
walk-forward window, and a model that predicted "down" on 100% of bars:

1. **Continuity anchoring** (`assistant/forecaster.py:_anchor_to_last_close`,
   on by default). Kronos denormalizes each forecast window using that
   window's own mean/std, which can leave a visible jump between the last
   real close and the first forecasted step even when the predicted
   *shape* is reasonable. Forecasts are now shifted by a constant offset so
   they continue smoothly from the last known price -- this doesn't change
   what Kronos predicted about direction or magnitude of moves, it just
   removes the artificial level-jump. Disable with
   `anchor_to_last_close=False` if you specifically want Kronos's raw
   unadjusted output for model diagnosis.
2. **Internal sample averaging raised from 1 to 5**
   (`DEFAULT_KRONOS_SAMPLE_COUNT=5` in `.env.example`). Kronos's own
   `sample_count` parameter averages multiple internal samples into one
   forecast -- a single sample is noisier. This trades some speed for a
   smoother, more representative forecast.
3. **Automatic reliability warnings** (`backtesting/metrics.py:reliability_flags`).
   Every metrics computation now flags:
   - **low sample size** (<30 predictions) -- with an actual confidence
     interval on the direction accuracy, so "64% accuracy" doesn't get
     read as solid when it's actually consistent with anywhere from 45-83%.
   - **directional bias** (model predicts the same direction >90% of the
     time) -- because a model that always says "down" scores exactly as
     well as the market's own down-move base rate, regardless of any real
     skill. These show up automatically in the `backtest AAPL` chat reply
     and in `metrics_by_model_horizon.csv` (`low_sample_warning`,
     `direction_bias_warning`, `reliability_notes` columns).

**None of this guarantees Kronos is actually skillful on any given
ticker** -- it just makes sure the numbers you're looking at aren't
artifacts of a plumbing bug or too little data. Always run with enough
windows (20-30+) before trusting a result, and treat the reliability
warnings as a first filter, not a final verdict.

## Running on limited hardware (8GB RAM, no GPU / AMD Radeon iGPU)

Kronos runs on CPU automatically when no CUDA/MPS GPU is detected (an AMD
Radeon iGPU can't be used by PyTorch for this) -- no crash, just slower.
Three things help keep it usable on a machine like a Ryzen 5000-series
laptop with 8GB RAM:

```bash
# one flag: caps walk-forward windows at 15, skips the slow ARIMA
# benchmark, and limits PyTorch to 4 CPU threads so the rest of your
# system (browser, OS) still has headroom
python run_backtest.py --tickers AAPL --low-resource

# or tune each part yourself
python run_backtest.py --tickers AAPL --max-windows 15 --no-arima --cpu-threads 4
```

`--cpu-threads` (or `KRONOS_CPU_THREADS` in `.env`) matters more than it
might seem: PyTorch defaults to using every logical core, which on a
6-core/12-thread CPU can cause more contention and thermal throttling than
it's worth, especially while other things are running. Start at 4 and
adjust based on how the rest of your system feels during a run.

For experimentation (hyperparameter search, trying settings on several
tickers), consider switching `KRONOS_MODEL_ID` back to `NeoQuasar/Kronos-small`
temporarily -- it's ~4x smaller than `Kronos-base` and iterates much faster
for the exploratory phase. Switch back to `Kronos-base` for your final,
fewer-but-longer verification runs once you've settled on settings.

## Statistical significance (is Kronos actually better, or just noise?)

`backtesting/significance.py` implements a Diebold-Mariano test, run
automatically:
- In `run_backtest.py`: `backtest_results/<TICKER>/significance_vs_best_benchmark.csv`
  -- Kronos vs. whichever benchmark had the lowest RMSE, per horizon.
- In the in-chat `backtest AAPL` command: a `Significance check` line in the
  reply.

This costs nothing extra to compute (it reuses predictions already made)
and answers the question a plain RMSE comparison can't: is the gap between
Kronos and the benchmark large enough, relative to the noise in the data,
to trust -- or could you get a gap that size by chance even if the two
models were equally good? A non-significant result (p >= 0.05) means "can't
tell them apart with this much data," which is common and expected with
small `--max-windows` values.

## Other recommended next steps (not yet automated -- manual for now)

- **Multi-ticker sweep**: run the same settings across several tickers
  (`--tickers AAPL MSFT NVDA TSLA SPY BTC-USD`) and check
  `cross_asset_comparison.csv` -- if a directional bias or weak result shows
  up on every ticker, it's a general finding; if it's isolated to one, it's
  ticker-specific.
- **Kronos-small vs Kronos-base A/B test**: run the same backtest with each
  `KRONOS_MODEL_ID` and compare `metrics_by_model_horizon.csv` -- bigger
  isn't automatically better for every ticker/horizon.
- **Hyperparameter search** (`backtesting/hyperparam_search.py`, already
  built): search over `T`, `lookback`, `top_p` instead of guessing:
  ```python
  from backtesting.hyperparam_search import grid_search
  results = grid_search(df, param_grid={"T": [0.6, 0.7, 0.8], "lookback": [200, 400]}, max_windows=10)
  ```
- **Regime-split results** (`backtesting/regimes.py`, already built): check
  `regime_metrics.json` per ticker -- a model can look fine on average while
  being much worse specifically in bear markets or high-volatility periods.
- **Trading threshold**: the default `--threshold 0.0` acts on any signal,
  however small. Raising it to `0.01-0.02` (1-2%) generally trades less
  often but with more conviction.

## Quick start

```bash
# sanity check first -- 5 windows, one ticker, so you're not waiting an hour
# before finding out something's misconfigured
python run_backtest.py --tickers AAPL --max-windows 5

# once that looks right, run it for real
python run_backtest.py --tickers AAPL --horizons 1 3 5 7 14 30

# multi-asset (requirement #11) -- same code, just a longer list
python run_backtest.py --tickers AAPL MSFT NVDA TSLA SPY BTC-USD ETH-USD
```

### Also available as a chatbot command

You don't need the CLI for a fast check -- `chat_cli.py` (and Discord/WhatsApp)
understand `"backtest AAPL"` directly:

```
you> backtest AAPL

bot> Backtest for AAPL -- 5 walk-forward windows, horizons [5, 14, 30] days (expanding window):
       h=5d: RMSE=2.10, MAE=1.50, direction accuracy=58.0%, IC=0.12
       h=14d: RMSE=4.30, MAE=3.10, direction accuracy=55.0%, IC=0.08
       h=30d: RMSE=7.80, MAE=5.90, direction accuracy=52.0%
     At 30d horizon, ranked by RMSE (lower is better): Kronos (RMSE=7.80), Linear Regression (RMSE=8.50), Naive (last close) (RMSE=9.10)
     Simulated trading at 30d horizon: total return 12.4%, Sharpe 1.35, win rate 61.0%, max drawdown -5.2%, 8 trades.
     This is a quick in-chat check (few windows, few benchmarks). For a full report with plots and diagnostics, run `python run_backtest.py --tickers AAPL`.
```

This calls `backtesting.runner.quick_backtest()` -- a deliberately small,
fast version of the full framework (5 windows, 3 horizons, 2 benchmarks,
one direction-summary chart attached inline, an equity curve chart also
saved to disk) so it returns in a reasonable time inside a chat reply
instead of running the full multi-hour walk-forward. The attached image is
`direction_summary.png` -- real vs. Kronos price with green/red
correct-vs-wrong direction markers, a rolling directional-accuracy line,
and an up/down bias bar chart (see `backtesting/visualization.py:plot_direction_summary`).
Tune it via `.env`:
```
BACKTEST_QUICK_HORIZONS=5,14,30
BACKTEST_QUICK_MAX_WINDOWS=5
BACKTEST_QUICK_MIN_TRAIN_SIZE=252
BACKTEST_QUICK_STEP_SIZE=30
```
For the real, thorough evaluation (full history, all horizons, all
benchmarks, every plot and diagnostic), use `run_backtest.py` as shown above.

Results land in `backtest_results/<TICKER>/`:
- `metrics_by_model_horizon.csv` -- every metric, every model, every horizon
- `portfolio_metrics_by_horizon.csv` -- Sharpe/Sortino/drawdown/etc. for Kronos's trading signals
- `residual_diagnostics.csv` -- Shapiro-Wilk/Durbin-Watson/Ljung-Box/Breusch-Pagan per horizon
- `regime_metrics.json` -- accuracy split by bull/bear/sideways
- `direction_summary_h<N>.png` -- real vs. Kronos price with correct/wrong
  direction markers, rolling directional accuracy, and an up/down bias bar
  chart, for each horizon (see below)
- `*.png` -- every plot from the visualization suite
- `backtest_results/cross_asset_comparison.csv` -- best model per horizon per asset

**A real run is compute-heavy.** Every walk-forward window re-invokes
`KronosPredictor.predict()` per horizon. With `Kronos-base` (the "heaviest" model
you switched to earlier) and 6 horizons over a multi-year expanding window, that's
potentially hundreds of forward passes. Always start with `--max-windows` small
while you dial in settings, then remove it for the full run -- ideally on a machine
with a GPU, or plan for a long CPU run.

## Requirement -> file map

| # | Requirement | File |
|---|---|---|
| 1 | Walk-forward validation (expanding/rolling, configurable horizon/step) | `backtesting/walk_forward.py` |
| 2 | Multiple forecast horizons | `WalkForwardValidator(horizons=(1,3,5,7,14,30))` |
| 3 | Error metrics (regression/bias/directional/correlation/financial) | `backtesting/metrics.py` |
| 4 | Trading simulation (long/short/long-short) | `backtesting/trading_simulator.py` |
| 5 | Portfolio performance | `backtesting/portfolio_metrics.py` |
| 6 | Benchmark comparison | `backtesting/benchmarks.py` |
| 7 | Prediction visualization | `backtesting/visualization.py` |
| 8 | Residual analysis | `backtesting/residual_analysis.py` |
| 9 | Robustness / market regimes | `backtesting/regimes.py` |
| 10 | Hyperparameter search | `backtesting/hyperparam_search.py` |
| 11 | Multi-asset | `BacktestRunner(tickers=[...])` |
| 12 | Pluggable data sources | `backtesting/data_loaders.py` |

## Usage beyond the CLI

```python
from backtesting.runner import BacktestRunner

runner = BacktestRunner(
    tickers=["AAPL", "NVDA"],
    horizons=(1, 5, 14, 30),
    window_type="rolling",      # or "expanding"
    min_train_size=252,
    step_size=30,
    max_windows=10,               # None for a full run
    kronos_params={"T": 1.0, "top_p": 0.9, "n_runs": 1},
    trading_strategy="long_short",
    trading_threshold=0.01,         # only trade if |predicted return| > 1%
)
summary = runner.run()
```

### Hyperparameter search

```python
from backtesting.data_loaders import YahooFinanceLoader
from backtesting.hyperparam_search import grid_search

df = YahooFinanceLoader().load("AAPL")
results = grid_search(
    df,
    param_grid={"lookback": [200, 400], "T": [0.8, 1.0], "top_p": [0.8, 0.9], "n_runs": [1]},
    horizons=(5, 14, 30),
    max_windows=5,          # keep this small -- grid search multiplies calls fast
    score_metric="rmse",
)
print(results[0])  # best combination first
```

### Using a different data source

```python
from backtesting.data_loaders import CSVLoader
from backtesting.runner import BacktestRunner

runner = BacktestRunner(tickers=["my_data.csv"], data_loader=CSVLoader())
runner.run()
```

## Honest notes on scope

The brief asked for a very large system; here's exactly what's simplified,
optional-and-skipped, or stubbed, and why:

- **LSTM and Prophet benchmarks are not implemented** (`backtesting/benchmarks.py`
  raises `NotImplementedError` with guidance). Both were marked "(optional)" in the
  brief, and both need a much heavier dependency (`tensorflow`/`keras`,
  `prophet`+`cmdstanpy`) that would roughly double install size/time for something
  optional. Naive, drift, moving-average, linear-regression, and ARIMA are all
  fully implemented and run by default.
- **Bayesian hyperparameter optimization is a stub** (`backtesting/hyperparam_search.py:bayesian_search`).
  Also marked optional. Grid search and random search are fully implemented and
  cover the requirement without adding `scikit-optimize` as a hard dependency.
- **Polygon, Alpha Vantage, Binance, and Interactive Brokers data loaders are
  stubs** (`backtesting/data_loaders.py`) that raise `NotImplementedError` with
  clear extension instructions. These need paid API keys / SDKs / a live broker
  connection that can't be provisioned generically. Yahoo Finance and CSV loaders
  are fully implemented and are what `BacktestRunner` uses by default.
- **Trading simulation is single-position, one trade per walk-forward window**
  (enter at the split date, exit at the end of the horizon) rather than a full
  multi-asset portfolio/order-book simulator. This is a standard, honest way to
  evaluate "would acting on these forecasts have made money" without building a
  full execution engine -- but it doesn't model slippage beyond a flat
  `transaction_cost`, partial fills, or overlapping positions across horizons.
- **Market regime classification is a simple rule** (trailing % change vs. a
  threshold for trend, rolling volatility vs. its own median for vol) — not a
  statistical regime-detection model (e.g. a Hidden Markov Model). Good enough to
  see "does accuracy hold up in a downtrend," not a research-grade regime model.
- **RMSLE** returns NaN when any actual/predicted price is <= 0, since log of a
  non-positive number is undefined -- not expected to trigger for real stock/crypto
  prices, but included for completeness per the brief.

Everything else in the original 12-point brief is fully implemented and was
smoke-tested with synthetic data end-to-end (walk-forward splitting, all metrics,
trading simulation, portfolio metrics, residual diagnostics, regime splitting, and
every plot) before being handed to you.
