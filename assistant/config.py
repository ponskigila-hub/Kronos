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

# ---------------------------------------------------------------------------
# Data storage
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(BASE_DIR, "assistant_data")
WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlists.json")
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

# ---------------------------------------------------------------------------
# Optional LLM key used ONLY to make the assistant's natural-language
# understanding and explanations more fluent. Everything works without it
# via the rule-based assistant/nlp.py + assistant/explain.py.
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Messaging platform integrations (assistant/integrations/*)
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")
