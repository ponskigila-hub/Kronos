"""
Lightweight, dependency-free intent parser (item #2 groundwork). Works
without any LLM/API key. If assistant.config.GEMINI_API_KEY is set,
assistant.core_assistant can optionally route ambiguous messages through
Gemini for smarter parsing -- but every intent below works offline.
"""
import re

from .ticker_utils import extract_tickers

INTENT_PATTERNS = [
    ("watchlist_add", re.compile(r"\badd\b.*\bwatchlist\b|\bwatchlist\b.*\badd\b", re.I)),
    ("watchlist_remove", re.compile(r"\bremove\b.*\bwatchlist\b|\bwatchlist\b.*\bremove\b|\bdelete\b.*\bwatchlist\b", re.I)),
    ("correlation", re.compile(r"\bcorrelat|\bdiversif", re.I)),
    ("watchlist_show", re.compile(r"\bmy watchlist\b|\bshow.*watchlist\b|\bwatchlist\b$", re.I)),
    ("backtest", re.compile(r"\bbacktest\b|\bback-test\b|\bback test\b", re.I)),
    ("earnings", re.compile(r"\bearnings\b|\breport(s)? date\b|\bwhen.*report\b", re.I)),
    ("analyst", re.compile(r"\banalyst|\bprice target|\brating\b|\bconsensus\b", re.I)),
    ("fundamentals", re.compile(r"\bfundamental|\bp/?e ratio\b|\bmarket cap\b|\bvaluation\b|\beps\b|\brevenue\b", re.I)),
    ("opinion", re.compile(
        r"\bshould i (buy|sell|invest)\b|"
        r"\bworth (buying|it|an? investment)\b|"
        r"\b(good|bad|solid|safe|smart|decent)\s+(buy|investment|pick|stock|entry)\b|"
        r"\bbuy or sell\b|\bbuy,?\s*hold,?\s*(or\s*)?sell\b|"
        r"\bis it (a )?(good |bad )?buy\b|\bwould you buy\b|"
        r"\bthumbs up\b|\bshould i get in\b", re.I)),
    ("set_mode", re.compile(r"\b(beginner|simple|plain|advanced|expert|technical)\s+mode\b|"
                             r"\buse\s+(beginner|simple|plain|advanced|expert|technical)\b", re.I)),
    ("compare", re.compile(r"\bcompare\b|\bvs\.?\b|\bversus\b", re.I)),
    ("history", re.compile(r"\bhistory\b|\bshow.*(price|chart)\b", re.I)),
    ("why", re.compile(r"^\s*why\b", re.I)),
    ("risk", re.compile(r"\brisk", re.I)),
    ("news", re.compile(r"\bnews\b", re.I)),
    ("detailed_forecast", re.compile(r"\bdetailed forecast\b|\bsampled paths\b|\bshow paths\b|"
                                      r"\bmultiple paths\b|\bforecast paths\b", re.I)),
    ("forecast", re.compile(r"\bforecast\b|\bpredict\b|\bprediction\b", re.I)),
    ("general", re.compile(
        r"\b(what can you do|what can you help with|what are you able to do|what can this assistant do|"
        r"how does this app work|how does kronos work|how does it work|what stocks do you recommend|"
        r"what do you recommend|what looks good right now|what should i buy|what should i do|"
        r"what do you think|what do you think about|how is the market|how are the markets|"
        r"can you help me|help me|what is this tool|what is this app|tell me about this app|"
        r"tell me what (this )?(assistant|app|tool) can help with|tell me what you can do|"
        r"tell me what this assistant can do)\b|\bhelp with\b",
        re.I,
    )),
    ("greeting", re.compile(r"^\s*(hi|hello|hey|start|help)\s*$", re.I)),
]

BEGINNER_WORDS = {"beginner", "simple", "plain"}
ADVANCED_WORDS = {"advanced", "expert", "technical"}


def detect_mode(text):
    """Returns True for beginner mode, False for advanced, None if the text
    doesn't mention a mode at all."""
    lowered = text.lower()
    if any(w in lowered for w in BEGINNER_WORDS):
        return True
    if any(w in lowered for w in ADVANCED_WORDS):
        return False
    return None


def parse_intent(text, context=None):
    """
    Returns a dict: {"intent": str, "tickers": [str], "raw": text, "mode": bool|None}

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

    # These intents trigger on a single common word (\brisk, \bnews\b,
    # \bhistory\b, \bcorrelat...) which is great for a quick follow-up
    # ("any risks?", "news?") but was also silently hijacking longer,
    # genuinely open-ended questions that just happen to contain the word
    # ("what's the historical relationship between rates and risk assets in
    # general") -- especially once combined with the followup-ticker reuse
    # below, which would then attach an unrelated previous ticker to a
    # question that was never about it. If there's no ticker in the message
    # itself and it's not short/command-like, let it fall through to
    # "unknown" -> general_chat instead, where Gemini can actually judge
    # what was meant instead of a keyword match forcing a specific ticker
    # command.
    AMBIGUOUS_WHEN_LONG = {"risk", "news", "history", "correlation", "fundamentals", "analyst", "earnings"}
    SHORT_COMMAND_WORD_LIMIT = 6
    if intent in AMBIGUOUS_WHEN_LONG and not tickers and len(text.split()) > SHORT_COMMAND_WORD_LIMIT:
        intent = "unknown"

    # Follow-up resolution: only reuse last ticker for explicit follow-up intents
    # (e.g. "why is it moving?", "compare with Microsoft"). Plain conversational
    # questions such as "what do you think?" and "how does this app work?"
    # should stay general and not trigger a forecast out of the blue.
    followup_intents = {"why", "compare", "risk", "news", "history", "fundamentals", "analyst", "earnings", "opinion", "watchlist_show"}
    if not tickers and intent in followup_intents and context is not None and context.last_tickers:
        tickers = list(context.last_tickers)
    elif intent == "compare" and len(tickers) == 1 and context is not None and context.last_tickers:
        # "compare with Microsoft" -> combine new ticker with last one
        for t in context.last_tickers:
            if t not in tickers:
                tickers.append(t)

    if intent == "unknown" and tickers:
        # Bare ticker mention defaults to a forecast request.
        intent = "forecast"

    if intent == "general" and not tickers:
        # Conversational questions should stay conversational even if there was a
        # previous forecast in context; the user has to ask for a market action.
        pass

    return {"intent": intent, "tickers": tickers, "raw": text, "mode": detect_mode(text)}
