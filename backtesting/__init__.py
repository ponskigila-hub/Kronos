"""
Kronos Backtesting Framework
============================

A walk-forward evaluation system for the Kronos forecasting model, built to
answer:
  - How accurate is Kronos, at which forecast horizons?
  - Does prediction quality degrade over time / across market regimes?
  - Would Kronos-driven trading signals actually be profitable?
  - How does Kronos compare to simple baselines (naive, moving average,
    linear regression, ARIMA)?
  - Which hyperparameters (window size, temperature, top_p, sample_count)
    work best?

Modules:
  data_loaders        - pluggable data sources (Yahoo Finance, CSV, ...)
  kronos_adapter       - wraps assistant.forecaster so Kronos can be used
                         as a `predict_fn` in the walk-forward loop
  walk_forward          - expanding/rolling window walk-forward validator
  metrics                 - regression / directional / correlation / financial metrics
  trading_simulator         - converts predictions into buy/sell/hold signals + P&L
  portfolio_metrics           - Sharpe, Sortino, Calmar, drawdown, CAGR, etc.
  benchmarks                    - naive, moving average, linear regression, ARIMA
  residual_analysis                - normality, autocorrelation, heteroscedasticity tests
  regimes                            - bull/bear/sideways + high/low-vol regime splitting
  hyperparam_search                    - grid search + random search over Kronos params
  visualization                         - matplotlib plots (equity curve, drawdown, etc.)
  runner                                  - BacktestRunner: orchestrates everything, multi-asset

See BACKTEST_README.md in the project root for usage and honest notes on scope.
"""
