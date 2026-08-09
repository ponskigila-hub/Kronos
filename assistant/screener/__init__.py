"""
Stock Screener -- ranks a universe of tickers on trend, momentum,
volatility, liquidity, risk, and relative strength, then optionally runs
the existing Kronos forecasting pipeline on just the top candidates.

Entry point: assistant.screener.engine.run_screen(...)

Submodules:
    universe.py            ticker universe providers (S&P 500, NASDAQ-100,
                            Dow 30, watchlist, custom list, CSV upload)
    data.py                 concurrent, cached OHLCV downloads
    metrics.py               all technical/risk/liquidity metric calculations
    scoring.py                normalization + composite weighted scoring
    presets.py                 named screening strategies (Momentum, Breakout, ...)
    filters.py                  custom metric/operator/value filter evaluation
    reasons.py                    plain-language "why this ranked here" bullets
    kronos_integration.py          runs assistant.forecaster on finalists
    engine.py                       orchestrates all of the above
"""
