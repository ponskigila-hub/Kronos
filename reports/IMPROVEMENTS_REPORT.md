# Kronos Stock Assistant — Improvement Report

This documents what was actually changed, why, and — importantly — what
still needs to be run/verified on your own machine, since this work was
done in a sandbox with no GPU, no Hugging Face network access, and no
live market data access.

---

## 1. Changes made

| Area | File(s) | What changed |
|---|---|---|
| Prediction cache | `assistant/forecast_cache.py` (new), `assistant/forecaster.py` | Content-hash-keyed, TTL+LRU in-memory cache wrapping `run_forecast()`. |
| Chart generation | `assistant/charts.py`, `assistant/core_assistant.py` | `LazyFigure` wrapper defers building the Plotly figure until something actually reads it. |
| LLM call safety | `assistant/llm.py`, `assistant/config.py` | Bounded-timeout wrapper (`_call_with_timeout`) around both existing Gemini calls; failures/timeouts degrade to the original rule-based text instead of blocking. |
| Web forecast page | `webapp/app.py`, `webapp/templates/forecast.html`, `webapp/static/js/forecast.js`, `webapp/static/js/loading.js` | `/forecast/ticker` and `/forecast/csv` converted from blocking form POSTs to the same background-job + polling pattern `/api/chat/send` already used. |
| Data provider abstraction | `assistant/providers/` (new package), `assistant/data_fetcher.py`, `assistant/config.py`, `PROVIDERS.md` (new), `.env.example` | `MarketDataProvider` interface; `YFinanceProvider` (moved, unchanged logic) and `TwelveDataProvider` (new, working); optional fallback. `fetch_history()`/`fetch_multi()`/`TickerNotFoundError` contract unchanged. |
| Model benchmark harness | `benchmarking/latency_probe.py`, `benchmarking/model_benchmark.py` (new) | Per-model subprocess measuring load time/latency/memory; orchestrator that also runs your existing `run_backtest.py` per model and aggregates into a comparison table. |
| Chat copilot | `assistant/tools.py`, `assistant/copilot.py` (new), `assistant/core_assistant.py`, `assistant/config.py` | LLM tool-selection layer (6 structured tools) wired into the `_fallback` path only — every rule-based intent is untouched. |
| Tests | `tests/test_*.py` (7 new files, 53 tests) | Unit/integration coverage for every item above, all passing. |

Nothing in `assistant/nlp.py`, `assistant/conversation.py`,
`assistant/model_loader.py`, `assistant/explain.py`,
`assistant/watchlist.py`, `assistant/screener/`, `integrations/`, or the
backtesting framework was modified — they were already solid on
inspection (see the original audit in this conversation) and the brief
explicitly asked not to touch what already works.

---

## 2. Why each change was made

**Prediction cache** — Confirmed by reading the code (not assumed) that
every one of `_forecast`, `_why`, `_risk`, `_history`, and
`_detailed_forecast` in `core_assistant.py` called `run_forecast()`
independently, so a `forecast AAPL` → `why?` → `what risks?` sequence ran
full Kronos inference three times for identical market data. The cache
key is a content hash of the *actual* data and parameters fed to the
model, not a ticker string, so a cache hit is provably the same output a
fresh call would produce — never a staleness compromise within its TTL
window.

**Lazy chart** — Traced every consumer of `result["chart"]`
(`chat_cli.py`, `integrations/discord_bot.py`,
`integrations/whatsapp_bot.py`, `webapp/app.py`) and found the web app's
JSON API never reads it at all, and Discord/WhatsApp only fall back to it
if PNG generation failed (which it normally doesn't, since PNG is built
first). The interactive Plotly figure — the most expensive of the two
chart types, with multiple subplots — was being built unconditionally on
every call regardless of channel.

**LLM timeout guard** — `polish_explanation()` is a purely cosmetic
wording pass that ran synchronously inline in the hot path of `_forecast`
and `_why`, with no timeout. A slow or hanging Gemini call would make a
forecast reply slow even though the actual financial content was already
complete and correct without it.

**Async forecast page** — `/api/chat/send` already used a
background-thread + job-id + polling pattern; `/forecast/ticker` and
`/forecast/csv` did not, and were fully synchronous blocking POSTs. This
was an inconsistency in the app, not a missing feature — the pattern to
copy already existed and worked.

**Data provider abstraction** — Not because yfinance is currently broken
(it isn't), but because it's an unofficial, keyless wrapper around
Yahoo's endpoints with no rate-limit contract, and it was called directly
in 4+ files. The interface makes "yfinance is down, use something else"
a one-line env var change instead of a multi-file patch, without forcing
you to actually make that change today.

**Model benchmark harness** — The brief explicitly said "do not assume
Kronos-base is automatically better" and asked for measured numbers, not
assumptions. Your `backtesting/` framework already computes every metric
needed (MAE, RMSE, MAPE, directional accuracy); what was missing was the
orchestration to run mini/small/base each in a clean process (required
because `model_loader.py` is a deliberate singleton — see below) and
aggregate the results.

**Tool-calling copilot** — Read `assistant/llm.py` and `assistant/nlp.py`
closely and confirmed the LLM layer was polish-and-fallback only; it
never called anything to check its own claims. Compound/conversational
follow-ups ("what could invalidate that forecast?") that don't match a
single rule-based intent landed in `general_chat()`, which had no way to
ground its answer in real numbers. This was the one clear, verified gap
matching the brief's "AI Stock Intelligence Copilot" request.

---

## 3. Before/after — what's measured vs. what needs your hardware

Being direct about this rather than fabricating numbers: **I could not
run Kronos inference, download model weights, or hit live market data in
this sandbox** (no GPU, no Hugging Face network access, network egress
limited to package registries). Every number below is either (a)
something I actually measured by running tests in this sandbox, or (b)
explicitly marked as needing a run on your machine.

### Measured (in this sandbox, real test runs)

| Check | Result |
|---|---|
| Forecast cache: identical input → cache hit, correct TTL/LRU behavior | ✅ 8/8 tests pass |
| LazyFigure: build function not called until accessed | ✅ 5/5 tests pass |
| LLM timeout guard: a stalled 2-second call is abandoned in <1s and falls back to original text | ✅ 6/6 tests pass, timing asserted |
| Data provider fallback: primary failure → fallback used; primary success → fallback never touched | ✅ 9/9 tests pass |
| `data_fetcher.fetch_history()` external contract unchanged after provider refactor | ✅ 6/6 tests pass |
| Benchmark harness CSV aggregation (averaging Kronos-only rows across tickers, excluding other benchmark models) | ✅ 3/3 tests pass |
| Structured tools return compact dicts, degrade to `{"error": ...}` on failure, never raise | ✅ 10/10 tests pass |
| Copilot tool dispatch, unavailable-client fallback, never raises into `core_assistant` | ✅ 6/6 tests pass |
| **Total** | **53/53 tests pass** |
| All modified Python files | `py_compile` clean |
| All modified JS files | `node --check` clean |

### Needs to be run on your machine (I built the tooling; you run it)

```bash
# Full mini vs small vs base comparison (latency, memory, MAE/RMSE/MAPE, directional accuracy)
python benchmarking/model_benchmark.py

# Faster sanity check first
python benchmarking/model_benchmark.py --models mini small --tickers AAPL MSFT --max-windows 5
```

This writes `benchmark_results/model_comparison.csv` and `.md` in
exactly the format the brief asked for. I can't fill in real numbers
without downloading ~130M+ params of weights and running inference,
which needs your GPU/CPU and Hugging Face access.

For the cache's actual latency win in your running app, the honest way
to see it is the timestamp difference between two identical requests in
your own logs (e.g. `forecast AAPL` twice in a row) — I'd rather point
you at that than invent a "before/after ms" number I never measured.

---

## 4. Kronos model recommendation

**I'm not making one.** The brief was explicit: "do not select the
largest model simply because it is larger" and "do not make major
architectural decisions before seeing benchmark results." I built the
tool to produce that evidence (`benchmarking/model_benchmark.py`) but
didn't run it, so a recommendation from me right now would violate the
same principle the brief is protecting against. Run it against your
actual ticker universe and hardware, then this table has real numbers
to decide from:

```
Model          Params    Latency    MAE    Directional Accuracy
----------------------------------------------------------------
Mini           4.1M      ???        ???    ???
Small          24.7M     ???        ???    ???
Base           102.3M    ???        ???    ???
```

One thing worth knowing before you run it: **Kronos-mini uses a
different tokenizer with a 2048-token context** (`Kronos-Tokenizer-2k`)
vs. 512 for small/base (`Kronos-Tokenizer-base`) — confirmed from your
own `README.md`. The benchmark harness sets this correctly per model
automatically; if you ever configure mini by hand, get this pairing
right or it'll silently just use less context than it could.

---

## 5. Data provider recommendation

**Keep yfinance as the default** (already validated — it's free, needs
no key, and your usage pattern doesn't stress it). **Configure Twelve
Data as the fallback** (`MARKET_DATA_FALLBACK_PROVIDER=twelvedata` +
`TWELVEDATA_API_KEY=...`) if you want resilience against yfinance's
occasional breakage, at zero cost on its free tier (800 calls/day is
comfortable for occasional-fallback use). Full comparison table and
reasoning against Finnhub/Alpha Vantage/Polygon (now "Massive")/FMP/Alpaca
is in `PROVIDERS.md`.

---

## 6. Chat architecture explanation

```
User message
     |
     v
assistant/nlp.py -- rule-based intent parser (unchanged, still first)
     |
     +-- matched a known intent (forecast/why/risk/compare/backtest/...)
     |        |
     |        v
     |   core_assistant.py's existing handler -- fast, free, zero LLM
     |   involvement, works with no API key. UNCHANGED.
     |
     +-- "unknown" -- no ticker, no matched pattern (compound/conversational)
              |
              v
         core_assistant._fallback()
              |
              +-- ticker in recent context? --> assistant/copilot.py
              |         |
              |         v
              |    LLM picks from 6 tools (assistant/tools.py):
              |    get_kronos_forecast, get_technical_indicators,
              |    get_prediction_performance, get_news_sentiment,
              |    get_fundamentals, compare_stocks
              |         |
              |         v
              |    tool results (compact dicts, never raw DataFrames)
              |    fed back to the LLM for a grounded final answer
              |         |
              |         v (only if copilot unavailable/times out/fails)
              +--------->  assistant/llm.py general_chat() -- the
                           original static/LLM fallback, unchanged
```

Every rule-based intent still runs exactly as before — the copilot is
strictly additive, sitting only in the one gap that was actually
verified to exist (compound follow-ups with no clean keyword match). If
`GEMINI_API_KEY` isn't set, or the copilot call fails/times out for any
reason, the app degrades gracefully to the pre-existing fallback text,
so nothing about "works without an LLM key" changed.

---

## 7. Remaining bottlenecks (honest list, not resolved here)

- **No real streaming to the UI.** Job-polling now covers both chat and
  the forecast page, but neither surfaces per-stage progress ("fetching
  data…", "running forecast…") — just pending/done/error. A genuinely
  responsive multi-stage progress UI would need the background job to
  write intermediate status, and the frontend to render it.
- **Copilot tool calls are sequential, not parallelized.** If the LLM
  asks for `get_kronos_forecast` + `get_technical_indicators` +
  `get_news_sentiment` in one turn, they currently run one after another.
  Could be parallelized with a thread pool similar to `_forecast`'s
  existing pattern.
- **The benchmark harness numbers don't exist yet** — see section 3.
  Until it's run, the mini/small/base tradeoff is still an open question,
  by design.
- **`quick_backtest()` inside `get_prediction_performance`** is capped at
  5 windows for copilot-turn speed, which is fine for a quick answer but
  is deliberately less thorough than the standalone `backtest AAPL`
  command (which uses your configured default windows). This tradeoff is
  documented in the tool's docstring but worth knowing if numbers look
  slightly different between the two paths.
- **No caching layer for the copilot's own LLM calls** — a repeated
  compound question re-runs the whole tool-selection loop rather than
  reusing a recent answer. Given `forecast_cache` already de-duplicates
  the expensive part (actual Kronos inference) underneath it, this is
  lower priority, but worth knowing.

---

## 8. Deployment recommendations

No change to the fundamental recommendation in your existing
`DEPLOYMENT.md` — everything added here is compatible with a single
process on affordable/free infrastructure:

- The prediction cache is in-process memory — zero new infrastructure.
- The provider fallback is opt-in via env var — zero infrastructure cost
  unless you choose to use it.
- The benchmark harness runs offline/locally — it's a dev tool, not
  something deployed.
- The copilot layer reuses the same Gemini client/timeout pattern already
  in production use for `polish_explanation`/`general_chat` — no new
  service dependency.

If you do end up needing multiple concurrent Kronos model variants (e.g.
a "fast mode" mini + "deep mode" base, per the brief's optional
architecture sketch) that's a bigger change than anything done here —
it would mean either running two model processes or reloading the
singleton per request (defeating the whole point of the singleton). Only
worth doing if the benchmark numbers actually justify it; the harness
built here is exactly what would inform that decision.

---

## 9. Future improvements (not done, explicitly out of scope for this pass)

- Parallelize copilot tool calls within a single turn.
- Stage-level progress streaming for both chat and forecast jobs.
- A `screen_stocks(criteria)` / `backtest_stock(ticker, parameters)` tool
  added to the copilot's registry, wrapping the existing screener and
  full backtest runner (the brief listed these; they were left out of
  this pass to keep the tool set small and focused on the gap that was
  actually verified — "why"/"what if"/comparison questions — rather than
  duplicating what `screen` and `backtest` commands already do well as
  direct rule-based intents).
- Once `benchmarking/model_benchmark.py` has real numbers, consider the
  brief's optional "Fast Mode (mini) vs Deep Mode (small/base)"
  architecture — only if the data justifies the added complexity.
