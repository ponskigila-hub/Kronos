"""
Central configuration for the Kronos AI Stock Assistant.

All values can be overridden with environment variables (e.g. via a `.env`
file loaded with python-dotenv). Nothing here requires an API key to run the
core forecasting flow -- news/sentiment and Discord/WhatsApp integrations
are the only pieces that need extra keys, and they degrade gracefully when
the keys are missing.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is optional; if it's not installed we just rely on
    # whatever is already in the environment.
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Kronos model settings
# ---------------------------------------------------------------------------
KRONOS_MODEL_ID = os.getenv("KRONOS_MODEL_ID", "NeoQuasar/Kronos-base")
KRONOS_TOKENIZER_ID = os.getenv("KRONOS_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-base")
KRONOS_MAX_CONTEXT = int(os.getenv("KRONOS_MAX_CONTEXT", "512"))
# Limit PyTorch's CPU thread count when running without a GPU (e.g. an AMD
# Radeon iGPU, which torch can't use for compute). Unset/0 = torch's own
# default (usually all logical cores), which can cause more contention than
# benefit on a laptop. A good starting point on a 6-core/12-thread CPU with
# 8GB RAM is 4-6.
KRONOS_CPU_THREADS = int(os.getenv("KRONOS_CPU_THREADS", "0")) or None
DEFAULT_LOOKBACK_DAYS = int(os.getenv("DEFAULT_LOOKBACK_DAYS", "400"))
DEFAULT_PRED_LEN = int(os.getenv("DEFAULT_PRED_LEN", "30"))
# Sampling temperature: 1.0 = Kronos's most exploratory/random setting.
# Lower values (0.6-0.8) produce more stable, less noisy forecasts --
# generally preferable for financial forecasting where wild single-sample
# swings hurt more than they help. Override with KRONOS_TEMPERATURE.
DEFAULT_KRONOS_T = float(os.getenv("KRONOS_TEMPERATURE", "0.7"))
# How many samples Kronos averages internally per single predict() call
# (its own built-in noise reduction -- higher is smoother but slower).
DEFAULT_KRONOS_SAMPLE_COUNT = int(os.getenv("DEFAULT_KRONOS_SAMPLE_COUNT", "5"))
# How many independent sampling passes to run through Kronos in order to
# build a confidence band around the forecast. 1 = fast, no band.
DEFAULT_SAMPLE_RUNS = int(os.getenv("DEFAULT_SAMPLE_RUNS", "1"))
# How many independent sampled paths to plot for the "detailed forecast"
# command/page (a spaghetti plot -- see assistant/charts.py:build_detailed_forecast_png).
# Much slower than a normal forecast (this many separate Kronos predict()
# calls) -- kept modest by default for CPU-only/limited-RAM machines.
DETAILED_FORECAST_RUNS = int(os.getenv("DETAILED_FORECAST_RUNS", "8"))

# How long a Kronos forecast stays cached (keyed on a content hash of the
# exact history window + parameters fed to the model -- see
# assistant/forecast_cache.py) before it's treated as stale and recomputed.
# Daily-bar data only changes once a new session closes, so a value in the
# minutes-to-tens-of-minutes range avoids re-running inference for repeated
# or follow-up questions about the same ticker without ever serving a
# meaningfully outdated forecast.
FORECAST_CACHE_TTL_SECONDS = int(os.getenv("FORECAST_CACHE_TTL_SECONDS", "900"))
# Hard cap on distinct cached forecasts kept in memory at once (LRU
# eviction beyond this) so a long-running process touching many tickers
# can't grow this unboundedly.
FORECAST_CACHE_MAX_ENTRIES = int(os.getenv("FORECAST_CACHE_MAX_ENTRIES", "256"))

# ---------------------------------------------------------------------------
# Data storage
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(BASE_DIR, "assistant_data")
WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlists.json")
SCREENER_HISTORY_PATH = os.path.join(DATA_DIR, "screener_history.json")
# How many past screen runs to keep per user. Each entry only stores the
# ranked ticker list + score/signal + the config used (not full per-ticker
# metrics), so this stays cheap even at a generous cap.
SCREENER_HISTORY_MAX_RUNS = int(os.getenv("SCREENER_HISTORY_MAX_RUNS", "50"))
WATCHLIST_NOTES_PATH = os.path.join(DATA_DIR, "watchlist_notes.json")
WATCHLIST_ENTRY_ZONES_PATH = os.path.join(DATA_DIR, "watchlist_entry_zones.json")
CONVERSATION_DIR = os.path.join(DATA_DIR, "conversations")
CHARTS_DIR = os.path.join(DATA_DIR, "charts")
BACKTEST_DIR = os.path.join(DATA_DIR, "backtests")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CONVERSATION_DIR, exist_ok=True)
os.makedirs(CHARTS_DIR, exist_ok=True)
os.makedirs(BACKTEST_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Quick in-chat backtest defaults (see backtesting/runner.py: quick_backtest).
# A full walk-forward run (backtesting/run_backtest.py) is much more
# thorough but too slow to run inline in a chat reply -- these defaults
# keep an in-chat "backtest AAPL" fast (a handful of windows, few horizons).
# ---------------------------------------------------------------------------
BACKTEST_QUICK_HORIZONS = tuple(
    int(h) for h in os.getenv("BACKTEST_QUICK_HORIZONS", "5,14,30").split(",")
)
BACKTEST_QUICK_MAX_WINDOWS = int(os.getenv("BACKTEST_QUICK_MAX_WINDOWS", "15"))
BACKTEST_QUICK_MIN_TRAIN_SIZE = int(os.getenv("BACKTEST_QUICK_MIN_TRAIN_SIZE", "252"))
BACKTEST_QUICK_STEP_SIZE = int(os.getenv("BACKTEST_QUICK_STEP_SIZE", "30"))

# ---------------------------------------------------------------------------
# Optional third-party news / sentiment keys.
# All are optional -- assistant/news.py falls back to yfinance's built-in
# news feed (which needs no key) if these are unset.
# ---------------------------------------------------------------------------
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
NEWSAPI_API_KEY = os.getenv("NEWSAPI_API_KEY", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# Which MarketDataProvider (assistant/providers/) supplies OHLCV history.
# "yfinance" needs no key and remains the default so the app works
# out of the box exactly as before. See PROVIDERS.md for the comparison
# behind this choice and how to add another provider.
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "yfinance")
# Optional: a second provider to try if the primary one raises
# ProviderDataError (symbol not found there, or the API is down). Left
# empty by default -- fall back only if you've deliberately set this,
# since silently trying a second paid API on every miss isn't something
# a solo-dev deployment should do without opting in.
MARKET_DATA_FALLBACK_PROVIDER = os.getenv("MARKET_DATA_FALLBACK_PROVIDER", "")

# ---------------------------------------------------------------------------
# Optional LLM key used ONLY to make the assistant's natural-language
# understanding and explanations more fluent. Everything works without it
# via the rule-based assistant/nlp.py + assistant/explain.py.
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Hard ceiling on how long the purely-cosmetic wording polish step
# (assistant.llm.polish_explanation) is allowed to block a forecast reply.
# This step only rewrites text that's already fully correct -- it should
# never be the reason a forecast takes noticeably longer to come back, so
# a slow/stalled Gemini call is abandoned in favor of the unpolished
# rule-based text rather than making the user wait on it.
LLM_POLISH_TIMEOUT_SECONDS = float(os.getenv("LLM_POLISH_TIMEOUT_SECONDS", "4"))
# Looser ceiling for general_chat(), since there the LLM reply IS the
# content being waited for (not an optional polish on top of something
# already usable) -- still bounded so a stalled call can't hang a request
# forever.
LLM_CHAT_TIMEOUT_SECONDS = float(os.getenv("LLM_CHAT_TIMEOUT_SECONDS", "15"))
# The tool-calling copilot layer (assistant/copilot.py) can make several
# sequential model calls plus real tool executions (a forecast, a mini
# backtest, ...) in one turn, so it gets a looser ceiling than a single
# chat completion. Still bounded -- a stuck loop must never hang a chat
# reply indefinitely.
COPILOT_TIMEOUT_SECONDS = float(os.getenv("COPILOT_TIMEOUT_SECONDS", "25"))
# Hard cap on how many tool-selection rounds the model gets in one turn.
# 3 comfortably covers "forecast + indicators + performance" in one
# question without letting a confused model loop indefinitely.
COPILOT_MAX_TOOL_ROUNDS = int(os.getenv("COPILOT_MAX_TOOL_ROUNDS", "3"))

# ---------------------------------------------------------------------------
# Messaging platform integrations (assistant/integrations/*)
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")

# ---------------------------------------------------------------------------
# Stock Screener (assistant/screener/) -- ranks a universe of tickers on
# trend/momentum/volatility/liquidity/risk/relative-strength, then optionally
# runs Kronos on just the top candidates. Fully price/volume based, no API
# key required. These are engineering defaults, not user secrets, so they
# live here (not in .env) -- edit this dict directly to change them.
# ---------------------------------------------------------------------------
SCREENER_CACHE_DIR = os.path.join(DATA_DIR, "screener_cache")
os.makedirs(SCREENER_CACHE_DIR, exist_ok=True)

SCREENER_CONFIG = {
    "min_history_days": 150,        # below this, a ticker is marked "insufficient history" rather than scored
    "min_avg_dollar_volume": 1_000_000,  # 20D avg (close * volume); below this, flagged "low liquidity"
    "benchmark": "SPY",             # used for relative strength + beta
    "lookback_days": 400,           # how much history to pull per ticker
    "preselection_count": 30,       # how many top-ranked-by-technicals candidates advance to the Kronos stage
    "final_count": 10,              # how many the final ranked list shows
    "max_workers": 8,               # concurrent download threads
    "cache_ttl_minutes": 60,        # reuse downloaded OHLCV within this window instead of re-fetching
    "weights": {                    # must sum to 1.0 when kronos is disabled these are re-normalized automatically
        "trend": 0.25,
        "momentum": 0.20,
        "relative_strength": 0.15,
        "volatility": 0.10,
        "liquidity": 0.10,
        "risk": 0.10,
        "kronos": 0.10,
    },
}
