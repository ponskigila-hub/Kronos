"""
Optional LLM layer.

Everything in assistant/nlp.py (intent parsing) and assistant/explain.py
(explanation text) already works fully offline/rule-based. When
assistant.config.GEMINI_API_KEY is set, this module adds two things on
top of that rule-based core:

  1. polish_explanation() -- rewrites an already-correct forecast note
     into smoother prose, WITHOUT changing any numbers or facts.
  2. general_chat() -- handles free-form questions the rule-based intent
     parser doesn't recognize (no command keyword, no ticker), e.g.
     "what stocks do you recommend?" or "how does this app work?" --
     genuinely conversational, grounded in what Kronos can actually do.

If the key is missing, the `google-genai` package isn't installed, the
API call fails, or anything else goes wrong, every function here falls
back to a safe default (unchanged text / None). This module must never
raise -- callers use it as a drop-in "make this nicer / try to answer
this" step.
"""
import logging

from .config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_client = None
_client_unavailable = False

# Grounds general_chat() in what this specific app can do, so "what stocks
# do you recommend" gets pointed at the screener (a real, data-backed
# feature) rather than the model inventing picks from parametric memory.
_SYSTEM_PROMPT = (
    "You are the conversational layer of Kronos, a local stock-market "
    "assistant app built on the Kronos time-series forecasting model. "
    "You are answering a free-form question that didn't match one of the "
    "app's structured commands.\n\n"
    "What this app can actually do (steer the user toward these when "
    "relevant, using the exact phrasing so it's clickable/typeable):\n"
    "- \"Forecast <TICKER>\" -- Kronos-generated price forecast with explanation\n"
    "- \"Screen the market\" / the Screener page -- ranks a whole universe of "
    "stocks on trend, momentum, volatility, liquidity, and risk; this is the "
    "right answer to 'what stocks do you recommend' or 'what looks good right "
    "now' -- it's backed by real ranked data, you are not\n"
    "- \"Compare X and Y\", \"Backtest <TICKER>\", \"Fundamentals of <TICKER>\", "
    "\"Analyst targets for <TICKER>\", \"News for <TICKER>\", \"Add <TICKER> to "
    "my watchlist\"\n\n"
    "Rules:\n"
    "- Never state or imply a personal buy/sell recommendation for a specific "
    "stock from your own general knowledge. If asked what to buy, explain "
    "that you don't hand-pick stocks, then point at the Screener as the "
    "actual data-driven way to find candidates in this app.\n"
    "- You may discuss investing concepts, market mechanics, how the app "
    "works, or general education in your own words.\n"
    "- Keep replies short -- 2-4 sentences unless the question genuinely "
    "needs more.\n"
    "- Not personalized financial advice; you don't know the user's "
    "portfolio, risk tolerance, or goals."
)


def _get_client():
    """Lazily build (and cache) the Gemini client. Cheap to call
    repeatedly -- only actually does work once."""
    global _client, _client_unavailable
    if _client is not None or _client_unavailable:
        return _client
    if not GEMINI_API_KEY:
        _client_unavailable = True
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        logger.warning(
            "GEMINI_API_KEY is set but the Gemini client could not be "
            "initialized (is the 'google-genai' package installed?). "
            "Falling back to rule-based wording.",
            exc_info=True,
        )
        _client_unavailable = True
        _client = None
    return _client


def is_available():
    """True if the Gemini layer is actually usable right now (key set,
    package importable, client built OK). Used by the web app to show an
    accurate status badge -- never assume the key alone means it works."""
    return _get_client() is not None


def polish_explanation(text, ticker=None, beginner=False):
    """
    Rewrite `text` (already factually complete, rule-based) into smoother
    prose. Returns `text` unchanged if polishing isn't available or fails
    for any reason -- this is a strictly cosmetic layer, never a source of
    new facts, numbers, or claims.
    """
    if not text:
        return text
    client = _get_client()
    if client is None:
        return text

    style = (
        "Keep it approachable and jargon-light for a beginner investor."
        if beginner else
        "Keep it concise and professional; the reader is comfortable with trading/technical jargon."
    )
    prompt = (
        "Rewrite the following stock-analysis note in smoother, more natural "
        "English. Do NOT add, remove, invent, or change any numbers, "
        "percentages, prices, dates, or facts -- only improve the wording "
        f"and flow. {style} Return ONLY the rewritten note, no preamble or "
        "commentary.\n\n"
        f"Ticker: {ticker or 'N/A'}\n\nNote:\n{text}"
    )
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        polished = (resp.text or "").strip()
        return polished or text
    except Exception:
        logger.warning("Gemini polish call failed; using rule-based wording.", exc_info=True)
        return text


def general_chat(text, history=None, beginner=False):
    """
    Free-form conversational fallback for messages the rule-based intent
    parser (assistant/nlp.py) doesn't recognize -- no command keyword, no
    ticker to default to a forecast. Returns None (never raises) if the
    Gemini layer isn't available or the call fails, so callers can fall
    back to the static "I didn't quite catch that" message.

    `history`: optional list of {"role": "user"/"assistant", "text": ...}
    dicts (assistant.conversation.ConversationContext.history) for
    multi-turn continuity -- e.g. "what about something safer?" after a
    prior reply.
    """
    if not text:
        return None
    client = _get_client()
    if client is None:
        return None

    from google.genai import types

    contents = []
    for turn in (history or [])[-10:]:
        role = "model" if turn.get("role") == "assistant" else "user"
        turn_text = turn.get("text")
        if turn_text:
            contents.append(types.Content(role=role, parts=[types.Part(text=turn_text)]))
    contents.append(types.Content(role="user", parts=[types.Part(text=text)]))

    system_prompt = _SYSTEM_PROMPT
    if beginner:
        system_prompt += "\nThe user is in beginner mode -- keep language jargon-light."

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=300,
            ),
        )
        reply = (resp.text or "").strip()
        return reply or None
    except Exception:
        logger.warning("Gemini general_chat call failed; using static fallback.", exc_info=True)
        return None
