# Kronos AI Stock Assistant

This adds a conversational AI layer on top of the original Kronos forecasting
model, per the brief in `AI Development Prompt`. The original model files
(`model/`, `finetune*/`, `examples/`, `webui/`, `yahoopredict.py`,
`csvpredict.py`) are **untouched** -- everything new lives in `assistant/`
and `integrations/`.

## What was added, mapped to the original 9 requirements

| # | Requirement | Where |
|---|---|---|
| 1 | Automatic Yahoo Finance integration (no more manual CSV) | `assistant/data_fetcher.py`, `assistant/ticker_utils.py` |
| 2 | Conversational assistant with follow-up context | `assistant/nlp.py`, `assistant/conversation.py`, `assistant/core_assistant.py` |
| 3 | News-aware analysis + sentiment | `assistant/news.py` |
| 4 | Explainable forecasts | `assistant/explain.py`, confidence bands in `assistant/forecaster.py` |
| 5 | Technical indicators | `assistant/indicators.py` |
| 6 | Interactive charts | `assistant/charts.py` |
| 7 | Multi-stock support (compare) | `StockAssistant._compare()` in `core_assistant.py`, `data_fetcher.fetch_multi()` |
| 8 | Watchlist / favorites | `assistant/watchlist.py` |
| 9 | Discord / WhatsApp, platform-agnostic core | `integrations/discord_bot.py`, `integrations/whatsapp_bot.py` (both are thin adapters over `StockAssistant`) |

## Architecture

```
your message ("forecast tesla")
        |
        v
integrations/discord_bot.py  \
integrations/whatsapp_bot.py  >-- thin adapters, no business logic
chat_cli.py                  /
        |
        v
assistant/core_assistant.py  (StockAssistant.handle_message)
        |
        +-- assistant/nlp.py          -> figure out intent + tickers
        +-- assistant/conversation.py -> remember context for follow-ups
        +-- assistant/data_fetcher.py -> pull + clean Yahoo Finance data
        +-- assistant/indicators.py   -> RSI/MACD/SMA/EMA/BB/ATR
        +-- assistant/forecaster.py   -> run Kronos, build confidence band
        +-- assistant/news.py         -> headlines + sentiment
        +-- assistant/explain.py      -> turn all of the above into text
        +-- assistant/charts.py       -> interactive Plotly figure
        +-- assistant/watchlist.py    -> per-user saved tickers
```

Nothing platform-specific ever touches the modules above the adapters line --
that's what makes adding a 4th interface later (e.g. Telegram, a web chat)
a matter of writing one more thin file like `discord_bot.py`.

## Setup

```bash
cd Kronos-master
python -m venv kronos_env      # skip if you already have one from before
source kronos_env/bin/activate # Windows: kronos_env\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # optional -- fill in API keys only if you want
                                # news/Discord/WhatsApp extras
```

`torch` and the Kronos model weights download from Hugging Face the first
time you run a forecast -- that part is unchanged from the original project.

## How to run each part

### 1. Quick local test -- terminal chat (no bot account needed)
```bash
python chat_cli.py
```
Try:
```
you> forecast AAPL
you> why is it expected to decline
you> compare NVDA and AMD
you> add TSLA to my watchlist
you> my watchlist
you> backtest AAPL
```
Every `forecast`/`history`/`compare` reply now saves **a static PNG chart**
(styled like the original `yahoopredict.py`/`csvpredict.py` matplotlib plot)
to `assistant_data/charts/`, and `chat_cli.py` will try to pop it open in
your OS's default image viewer automatically -- the same experience as the
original scripts' `plt.show()`. It also saves an interactive
`last_chart.html` (Plotly, with indicators/volume/news) alongside it if you
want to explore the data further in a browser.

### 2. Use it directly in Python / your own script
```python
from assistant.core_assistant import StockAssistant

bot = StockAssistant(pred_len=30, n_forecast_runs=3)  # n_forecast_runs>1 = confidence band
result = bot.handle_message(user_id="me", text="forecast tesla for 14 days")
print(result["text"])
result["chart"].show()   # opens the interactive Plotly chart
```

### 3. Discord bot
```bash
pip install discord.py
# in .env: DISCORD_BOT_TOKEN=your_bot_token
python integrations/discord_bot.py
```
Then DM the bot or @mention it in a server channel with e.g. `forecast aapl`.

### 4. WhatsApp bot (via Twilio sandbox)
```bash
pip install twilio flask
# in .env: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM
python integrations/whatsapp_bot.py
ngrok http 5001   # expose it publicly
```
Set the ngrok URL + `/whatsapp` as the webhook in your Twilio WhatsApp
sandbox settings. Full walkthrough: https://www.twilio.com/docs/whatsapp/sandbox

### 5. Existing Flask web UI (`webui/app.py`) — unchanged
Still works exactly as before for CSV/local-file based predictions; it does
not currently call into `assistant/`. Wiring it up to the new auto-fetch
pipeline is a natural next step if you want a browser UI on top of this too.

## Known limitations / honest notes

- **News sentiment is lexicon-based**, not a trained model -- good enough to
  say "mostly positive/negative" but not investment-grade sentiment analysis.
- **Confidence bands** come from running Kronos multiple independent times
  (`n_forecast_runs`) and taking the 10th/90th percentile of the closes --
  this is slower (Nx inference time), so it defaults to 1 (no band) unless
  you raise `DEFAULT_SAMPLE_RUNS` or pass `n_forecast_runs` explicitly.
- **NLP intent parsing is rule-based** (regex + keyword matching), not an
  LLM. It handles the command styles from the original brief well, but
  won't handle arbitrarily-phrased free-form chit-chat. If you set
  `ANTHROPIC_API_KEY`, that's a hook you can extend `assistant/nlp.py` with
  to route ambiguous messages through an LLM -- not wired up by default so
  the assistant works with zero API keys.
- **WhatsApp uses Twilio**, not Meta's official WhatsApp Business API
  directly -- it's the realistic path for an individual developer; the
  official API requires business verification.
- Discord/WhatsApp chart delivery needs the optional `kaleido` package to
  export PNGs; without it, Discord falls back to sending an HTML file and
  WhatsApp skips the image (text reply still works).
