"""
Optional LLM polish layer.

Everything in assistant/nlp.py (intent parsing) and assistant/explain.py
(explanation text) already works fully offline/rule-based. This module is
purely cosmetic on top of that: when assistant.config.GEMINI_API_KEY is
set, it asks Google Gemini to rewrite the already-correct, rule-based
explanation into smoother, more natural prose -- WITHOUT changing any of
the underlying numbers or facts (those still come entirely from
explain.py).

If the key is missing, the `google-genai` package isn't installed, the
API call fails, or anything else goes wrong, every function here falls
back to returning the original text unchanged. This module must never
raise -- callers use it as a drop-in "make this nicer if possible" step.
"""
import logging

from .config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_client = None
_client_unavailable = False


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
    """True if AI-polished wording is actually usable right now (key set,
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
