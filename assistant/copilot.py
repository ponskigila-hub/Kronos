"""
The "AI Stock Intelligence Copilot" layer: an LLM that selects and calls
structured financial tools (assistant/tools.py) rather than answering
from its own memory of stock data.

Architecture (matches the project brief exactly):

    User question
         v
    LLM picks which tool(s) it needs
         v
    assistant.tools.* (wraps forecaster/indicators/news/fundamentals/
                        backtesting -- the same modules the rule-based
                        intents already use)
         v
    Structured (small, JSON-safe) results
         v
    LLM writes the final answer, grounded only in those results
         v
    Response

This is deliberately a SEPARATE layer from assistant/nlp.py's rule-based
intent parser, not a replacement for it. Every existing rule-based intent
(forecast, why, risk, compare, backtest, fundamentals, ...) still runs
exactly as before with zero LLM involvement -- fast, free, and works with
no API key. This module only activates from core_assistant._fallback(),
i.e. for messages the rule-based parser couldn't confidently classify:
compound or conversational questions like "why does Kronos think it'll
decline, and what would change that view?" that don't cleanly match a
single keyword pattern. That's also exactly why it exists: those
questions used to get a plain, ungrounded general_chat() reply; now they
can actually pull real numbers before answering.

Every failure mode here (no API key, package missing, timeout, malformed
tool call, tool exception) falls back to returning None, so
core_assistant.py can drop straight back to llm.general_chat() -- the
copilot is a strict enhancement, never a new way for the chat to break.
"""
import json
import logging

from .config import COPILOT_TIMEOUT_SECONDS, COPILOT_MAX_TOOL_ROUNDS
from . import llm, tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the reasoning layer of a Kronos-based AI stock \
forecasting assistant. You do not know current prices, forecasts, \
indicators, news, or fundamentals yourself -- you MUST call the provided \
tools to get real numbers before stating any of them. Never invent or \
estimate a price, percentage, or indicator value.

Rules:
- Call only the tools relevant to what was actually asked. Don't fetch \
data for tickers the user didn't ask about.
- If a tool returns an "error" field, say so plainly rather than making \
something up to fill the gap.
- Ground every specific claim (price, trend, indicator reading, accuracy \
percentage) in a tool result. General reasoning/context that isn't a \
specific number doesn't need a tool call.
- Never state or imply investment advice ("you should buy/sell") -- \
describe what the data shows and let the person decide.
- Keep the final answer concise and structured (short sections/bullets \
for multi-part answers), not a wall of prose.
- If the person's message isn't about a specific stock/forecast at all, \
just answer conversationally without calling any tools.
"""

# JSON Schema tool declarations for the Gemini function-calling API.
# Written by hand (not auto-generated from tools.py's docstrings/type
# hints) so the exact schema the model sees is explicit and reviewable --
# this is the one place that fully determines what the LLM is able to
# trigger, so it's worth being deliberate about rather than relying on
# introspection magic that could change behavior on a library upgrade.
TOOL_DECLARATIONS = [
    {
        "name": "get_kronos_forecast",
        "description": tools.get_kronos_forecast.__doc__,
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "horizon": {"type": "integer", "description": "Forecast horizon in trading days (default 14)."},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": tools.get_technical_indicators.__doc__,
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_prediction_performance",
        "description": tools.get_prediction_performance.__doc__,
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_news_sentiment",
        "description": tools.get_news_sentiment.__doc__,
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": tools.get_fundamentals.__doc__,
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "compare_stocks",
        "description": tools.compare_stocks.__doc__,
        "parameters": {
            "type": "object",
            "properties": {
                "ticker_a": {"type": "string"},
                "ticker_b": {"type": "string"},
                "horizon": {"type": "integer"},
            },
            "required": ["ticker_a", "ticker_b"],
        },
    },
]


def _dispatch_tool_call(name, args):
    fn = tools.TOOL_REGISTRY.get(name)
    if fn is None:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"Bad arguments for '{name}': {e}"}


def _run_tool_loop(client, model_name, question, context_tickers, history, beginner):
    from google.genai import types

    context_hint = ""
    if context_tickers:
        context_hint = f"\n\n(For reference, the tickers already discussed in this conversation are: {', '.join(context_tickers)}.)"

    contents = []
    for turn in (history or [])[-6:]:  # a few recent turns for continuity, not the whole history
        role = "user" if turn.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=turn.get("text", ""))]))
    contents.append(types.Content(role="user", parts=[types.Part(text=question + context_hint)]))

    tool_config = types.Tool(function_declarations=[
        types.FunctionDeclaration(**decl) for decl in TOOL_DECLARATIONS
    ])
    gen_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + (
            "\nThe person may be a beginner -- avoid unexplained jargon." if beginner else ""
        ),
        tools=[tool_config],
        max_output_tokens=500,
    )

    used_tools = []
    for _ in range(COPILOT_MAX_TOOL_ROUNDS):
        resp = client.models.generate_content(model=model_name, contents=contents, config=gen_config)
        candidate = resp.candidates[0] if resp.candidates else None
        if candidate is None:
            break
        parts = candidate.content.parts or []
        function_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        if not function_calls:
            text = (resp.text or "").strip()
            return text or None, used_tools

        contents.append(candidate.content)  # the model's tool-call turn
        response_parts = []
        for call in function_calls:
            args = dict(call.args or {})
            result = _dispatch_tool_call(call.name, args)
            used_tools.append({"name": call.name, "args": args})
            response_parts.append(types.Part(function_response=types.FunctionResponse(
                name=call.name, response={"result": json.dumps(result, default=str)},
            )))
        contents.append(types.Content(role="user", parts=response_parts))

    # Ran out of rounds without a final text reply -- ask once more for a
    # plain answer using whatever's been gathered so far, rather than
    # silently returning nothing.
    resp = client.models.generate_content(
        model=model_name,
        contents=contents + [types.Content(role="user", parts=[types.Part(
            text="Please give your final answer now based on the tool results above.")])],
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, max_output_tokens=500),
    )
    return (resp.text or "").strip() or None, used_tools


def answer(question, context_tickers=None, history=None, beginner=False):
    """
    Try to answer `question` using the tool-calling copilot. Returns the
    final text, or None if the copilot isn't available/usable right now
    (no key, package missing, timeout, error) -- callers should fall back
    to assistant.llm.general_chat() in that case, exactly as before this
    module existed.
    """
    client = llm._get_client()
    if client is None:
        return None

    def _run():
        from .config import GEMINI_MODEL
        text, used = _run_tool_loop(client, GEMINI_MODEL, question, context_tickers, history, beginner)
        if used:
            logger.info("Copilot used tools: %s", [t["name"] for t in used])
        return text

    return llm._call_with_timeout(_run, COPILOT_TIMEOUT_SECONDS, default=None)
