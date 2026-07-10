"""
Lightweight, dependency-free intent parser (item #2 groundwork). Works
without any LLM/API key. If assistant.config.ANTHROPIC_API_KEY is set,
assistant.core_assistant can optionally route ambiguous messages through
Claude for smarter parsing -- but every intent below works offline.
"""
import re

from .ticker_utils import extract_tickers

INTENT_PATTERNS = [
    ("watchlist_add", re.compile(r"\badd\b.*\bwatchlist\b|\bwatchlist\b.*\badd\b", re.I)),
    ("watchlist_remove", re.compile(r"\bremove\b.*\bwatchlist\b|\bwatchlist\b.*\bremove\b|\bdelete\b.*\bwatchlist\b", re.I)),
    ("watchlist_show", re.compile(r"\bmy watchlist\b|\bshow.*watchlist\b|\bwatchlist\b$", re.I)),
    ("compare", re.compile(r"\bcompare\b|\bvs\.?\b|\bversus\b", re.I)),
    ("history", re.compile(r"\bhistory\b|\bshow.*(price|chart)\b", re.I)),
    ("why", re.compile(r"^\s*why\b", re.I)),
    ("risk", re.compile(r"\brisk", re.I)),
    ("news", re.compile(r"\bnews\b", re.I)),
    ("forecast", re.compile(r"\bforecast\b|\bpredict\b|\bprediction\b", re.I)),
    ("greeting", re.compile(r"^\s*(hi|hello|hey|start|help)\s*$", re.I)),
]


def parse_intent(text, context=None):
    """
    Returns a dict: {"intent": str, "tickers": [str], "raw": text}

    `context` (an assistant.conversation.ConversationContext) is used to
    resolve pronoun-like follow-ups ("why is it declining?", "compare with
    Microsoft" -> reuses the last ticker discussed).
    """
    text = text.strip()
    intent = "unknown"
    for name, pattern in INTENT_PATTERNS:
        if pattern.search(text):
            intent = name
            break

    tickers = extract_tickers(text)

    # Follow-up resolution: if no ticker was mentioned but we have context,
    # reuse the last one(s) discussed.
    if not tickers and context is not None and context.last_tickers:
        tickers = list(context.last_tickers)
    elif intent == "compare" and len(tickers) == 1 and context is not None and context.last_tickers:
        # "compare with Microsoft" -> combine new ticker with last one
        for t in context.last_tickers:
            if t not in tickers:
                tickers.append(t)

    if intent == "unknown" and tickers:
        # Bare ticker mention defaults to a forecast request.
        intent = "forecast"

    return {"intent": intent, "tickers": tickers, "raw": text}
