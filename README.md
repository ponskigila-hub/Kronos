# Kronos AI Stock Assistant

Conversational AI stock analysis and forecasting app built on top of **Kronos** — a foundation transformer model for financial time series (OHLCV).

The core forecasting engine is the open-source Kronos model. This project wraps it with automatic market data, technical indicators, news sentiment, fundamentals, a stock screener, walk-forward backtesting, paper-trading simulation, relative valuation, interactive charts, and a full web UI + optional Discord/WhatsApp bots.

> **Disclaimer**: This is a research / educational tool. Forecasts are not financial advice. Past performance and model predictions do not guarantee future results.

---

## Features

| Feature | Description |
|---------|-------------|
| **Kronos forecasting** | Multi-horizon OHLCV predictions with optional multi-sample paths & confidence bands |
| **Conversational chat** | Natural-language intents (forecast, compare, why, risks, news, fundamentals, backtest, watchlist, …) |
| **Technical indicators** | SMA/EMA, RSI, MACD, Bollinger, ATR, support/resistance, regime detection |
| **News & sentiment** | Aggregated headlines (yfinance primary, optional Finnhub/NewsAPI) with simple sentiment |
| **Fundamentals** | Key ratios, earnings dates, analyst consensus (via yfinance) |
| **Stock screener** | Universe (S&P 500 / NASDAQ-100 / Dow / custom) → metrics → filters → score → optional Kronos re-rank |
| **Watchlist** | Per-user favorites + correlation matrix |
| **Backtesting** | Walk-forward validation, baselines (naive, drift, MA, linear, ARIMA), metrics, regime analysis |
| **Day Trade desk** | Scanner, entry timer, exit planner, risk sizing (pure Python, no Claude, no broker) |
| **Paper trading** | Demo “buy at today’s price and track” against future real prices |
| **Relative valuation** | Peer multiples (P/E, EV/EBITDA, etc.) with scenario ranges |
| **Charts** | Interactive Plotly (history + forecast overlay, indicators, correlation) |
| **Multi-interface** | Web app (primary), CLI chat, Discord bot, WhatsApp (Twilio) — all share the same `StockAssistant` core |

---

## Project structure

```
.
├── model/                  # Kronos foundation model (tokenizer + transformer + predictor)
├── assistant/              # All business logic (forecast, NLP, indicators, screener, …)
│   ├── providers/          # Market data providers (yfinance default, Twelve Data optional)
│   ├── screener/           # Universe → download → metrics → filter → score → Kronos
│   └── …
├── webapp/                 # Flask web UI (chat, forecast, screener, backtest, watchlist, valuation)
├── backtesting/            # Walk-forward framework + baseline forecasters
├── integrations/           # Thin Discord & WhatsApp adapters
├── tests/                  # Unit / integration tests
├── chat_cli.py             # Terminal chat for local testing
├── run_backtest.py         # CLI entry for backtesting
├── requirements.txt
├── .env.example
├── BACKTEST_README.md      # Deep-dive on the backtesting framework
└── DEPLOYMENT.md           # Deploy webapp / bots
```

Runtime data (watchlists, conversation history, forecast cache, paper positions) is stored under `assistant_data/` (created on first run, git-ignored).

---

## Quick start

```bash
# 1. Create & activate virtualenv
python -m venv kronos_env
source kronos_env/bin/activate          # Windows: kronos_env\Scripts\activate

# 2. Install
pip install -r requirements.txt

# 3. (Optional) API keys for news / Discord / WhatsApp / Twelve Data
cp .env.example .env
# edit .env if needed — core forecast works with zero keys

# 4. Run
python chat_cli.py                      # terminal chat
# or
python webapp/app.py                    # web UI at http://127.0.0.1:5000
```

First forecast downloads Kronos weights from Hugging Face and caches them locally.

### Example chat commands
```
forecast AAPL
why is it expected to rise
compare NVDA AMD
add TSLA to watchlist
my watchlist
backtest AAPL
news for MSFT
fundamentals GOOGL
```

---

## Architecture (high level)

```
User message
    │
    ▼
nlp.parse_intent()  ──►  intent + tickers + mode
    │
    ▼
StockAssistant.handle_message()
    │
    ├── data_fetcher (yfinance / Twelve Data) → OHLCV history
    ├── indicators.compute_indicators()
    ├── forecaster.run_forecast()  ──►  KronosPredictor (singleton)
    ├── news / fundamentals / valuation / screener / backtest …
    ├── explain.build_explanation()   (rule-based + optional LLM polish)
    └── charts (Plotly)
    │
    ▼
{ text, chart, image_path, data, suggestions }
```

- **Business logic lives only in `assistant/`**. Web, Discord, WhatsApp, and CLI are thin adapters.
- **Model loading is a process-wide singleton** (`assistant/model_loader.py`) so weights are loaded once.
- **Forecast cache** avoids re-running Kronos for identical (ticker, history, params) requests within a TTL.
- **Screener** is fully isolatable: one bad ticker never aborts the whole screen.

---

## Techniques & approaches used

### 1. Kronos foundation model (core forecast engine)
- Transformer architecture specialized for financial time series (“language of markets”).
- **Hybrid tokenization** with Binary Spherical Quantization (BSQuantizer) that compresses continuous OHLCV into discrete tokens.
- Autoregressive multi-step prediction of future OHLCV bars.
- Supports multi-sample generation (temperature / top-p) to produce distribution of paths → confidence bands.
- Small inference tweaks in this fork: GPU auto-detect (CUDA/MPS), CPU thread limiting, continuity bias correction (anchor first predicted close to last observed close).
- Model weights loaded from Hugging Face (`NeoQuasar/Kronos-base` by default; mini/small variants configurable).

### 2. Data pipeline
- Provider abstraction (`assistant/providers/`): yfinance (default, no key) + optional Twelve Data fallback.
- Normalized schema expected by Kronos: `timestamps, open, high, low, close, volume, amount`.
- Short-lived in-memory history cache + on-disk forecast cache.
- Ticker validation and multi-ticker concurrent fetch.

### 3. Technical analysis
- Classic indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, volume metrics).
- Support / resistance levels.
- Simple market-regime detection (trend + volatility) used both for explanation and for historical accuracy notes.

### 4. Explainability
- Rule-based narrative generator (`assistant/explain.py`) that turns indicator readings + forecast delta + news into readable text.
- Optional Gemini polish when `GEMINI_API_KEY` is set (content still grounded in the rule-based facts).
- Beginner vs advanced language mode.

### 5. NLP / intent routing
- Lightweight regex + keyword intent classifier (`assistant/nlp.py`) — no heavy NLU model required.
- Conversation context (last tickers, beginner mode) for follow-ups (“why”, “risks”, “compare them”).

### 6. Screener pipeline
```
Universe → concurrent download (cached) → metrics → filters → weighted score → Top-N
         → (optional) Kronos forecast re-rank → final ranking + reasons
```
- Metrics include momentum, volatility, volume, relative strength, fundamental screens, etc.
- Presets + fully custom filters/weights.
- Designed to be free of look-ahead bias within a single screen (all computed as-of latest bar).

### 7. Backtesting
- Walk-forward validation (rolling train / test windows).
- Multiple baseline forecasters sharing the same `predict_fn` interface (naive, drift, moving average, linear regression, ARIMA).
- Metrics: MAE, RMSE, MAPE, directional accuracy, Sharpe-like stats, drawdown, etc.
- Regime splitting and residual diagnostics (normality, autocorrelation, heteroscedasticity).
- See `BACKTEST_README.md` for full details.

### 8. Additional modules
- **Relative valuation**: peer-group multiples, not DCF; transparent and offline-testable.
- **Paper trading simulation**: “buy” at real price today, track P&L against future real prices (complements historical backtests).
- **Portfolio helpers**: correlation, basic multi-ticker analysis.

### 9. Web & integrations
- Flask webapp with background job queue for long-running forecasts (so the browser can leave the chat page).
- Persistent sessions → stable per-user identity for watchlist / paper positions / conversation history.
- Discord & WhatsApp bots are pure adapters over `StockAssistant.handle_message()`.

---

## Configuration

All settings are overridable via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `KRONOS_MODEL_ID` | `NeoQuasar/Kronos-base` | Hugging Face model |
| `KRONOS_TOKENIZER_ID` | `NeoQuasar/Kronos-Tokenizer-base` | Matching tokenizer |
| `KRONOS_MAX_CONTEXT` | `512` | Context length |
| `DEFAULT_PRED_LEN` | `30` | Forecast horizon (days) |
| `MARKET_DATA_PROVIDER` | `yfinance` | Primary OHLCV source |
| `GEMINI_API_KEY` | — | Optional LLM polish for explanations |
| `FINNHUB_API_KEY` / `NEWSAPI_API_KEY` | — | Optional news fallbacks |
| `TWELVEDATA_API_KEY` | — | Optional secondary market-data provider |

---

## Running the web app

```bash
python webapp/app.py
# or with production-ish settings
WEBAPP_DEBUG=false WEBAPP_PORT=8080 python webapp/app.py
```

Pages: Chat · Forecast · Screener · Backtest · Watchlist · Valuation · News.

See `DEPLOYMENT.md` for Heroku / Docker / reverse-proxy notes and bot setup.

---

## Testing

```bash
pytest tests/ -q
```

---

## Known limitations

- Kronos is a research foundation model; it does **not** incorporate real-time news, order-book, or fundamental surprises into the numerical forecast itself (those appear only in the surrounding explanation / screener).
- No portfolio optimization or risk-factor neutralization — forecasts are raw signals.
- Screener historical walk-forward evaluation is out of scope of the current module (single-screen is look-ahead-free).
- Free-tier data providers (yfinance, free news APIs) have rate limits and occasional gaps.
- LLM explanations (when enabled) are polishing only; the underlying facts remain rule-based.

---

## Attribution

Kronos model: [Shi et al., 2025 — “Kronos: A Foundation Model for the Language of Financial Markets”](https://arxiv.org/abs/2508.02739)

```bibtex
@misc{shi2025kronos,
  title={Kronos: A Foundation Model for the Language of Financial Markets},
  author={Yu Shi and Zongliang Fu and Shuo Chen and Bohan Zhao and Wei Xu and Changshui Zhang and Jian Li},
  year={2025},
  eprint={2508.02739},
  archivePrefix={arXiv},
  primaryClass={q-fin.ST},
  url={https://arxiv.org/abs/2508.02739},
}
```

Licensed under the MIT License (see `LICENSE`).
