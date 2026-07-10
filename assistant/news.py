"""
News-aware analysis (item #3).

Default source: yfinance's built-in `Ticker.news`, which needs no API key
at all. If FINNHUB_API_KEY / NEWSAPI_API_KEY are set in the environment,
those are used as richer/backup sources.

Sentiment is a small lexicon-based scorer -- no extra heavy ML dependency
required. It's intentionally simple and transparent rather than a black box;
good enough to say "mostly positive / mixed / mostly negative" about a
headline batch, which is what the explanation layer needs.
"""
import requests

from .config import FINNHUB_API_KEY, NEWSAPI_API_KEY

POSITIVE_WORDS = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "rallies",
    "gain", "gains", "growth", "record", "strong", "upgrade", "upgraded",
    "bullish", "outperform", "profit", "profits", "positive", "rise",
    "rises", "jump", "jumps", "boost", "boosts", "win", "wins", "expansion",
    "breakthrough", "optimistic", "exceeds", "buy",
}
NEGATIVE_WORDS = {
    "miss", "misses", "plunge", "plunges", "slump", "slumps", "crash",
    "crashes", "fall", "falls", "falling", "decline", "declines", "weak",
    "downgrade", "downgraded", "bearish", "underperform", "loss", "losses",
    "negative", "drop", "drops", "cut", "cuts", "lawsuit", "investigation",
    "recall", "layoff", "layoffs", "warning", "sell", "concerns", "risk",
    "risks", "fraud", "delay", "delays",
}


def score_sentiment(text):
    """Return a score in [-1, 1] and a label."""
    if not text:
        return 0.0, "neutral"
    words = [w.strip(".,!?:;()'\"").lower() for w in text.split()]
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    if pos == neg == 0:
        return 0.0, "neutral"
    score = (pos - neg) / max(1, (pos + neg))
    if score > 0.2:
        label = "positive"
    elif score < -0.2:
        label = "negative"
    else:
        label = "neutral"
    return round(score, 2), label


def _from_yfinance(ticker, limit=8):
    import yfinance as yf
    items = []
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []
    for entry in raw[:limit]:
        content = entry.get("content", entry)  # newer yfinance nests under "content"
        title = content.get("title") or entry.get("title") or ""
        publisher = (content.get("provider") or {}).get("displayName") if isinstance(content.get("provider"), dict) else entry.get("publisher", "")
        link = (content.get("canonicalUrl") or {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else entry.get("link", "")
        pub_date = content.get("pubDate") or entry.get("providerPublishTime", "")
        if not title:
            continue
        score, label = score_sentiment(title)
        items.append({
            "title": title,
            "publisher": publisher or "Yahoo Finance",
            "link": link,
            "published": pub_date,
            "sentiment_score": score,
            "sentiment_label": label,
        })
    return items


def _from_finnhub(ticker, limit=8):
    if not FINNHUB_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": "2024-01-01", "to": "2030-01-01", "token": FINNHUB_API_KEY},
            timeout=8,
        )
        resp.raise_for_status()
        raw = resp.json() or []
    except Exception:
        raw = []
    items = []
    for entry in raw[:limit]:
        title = entry.get("headline", "")
        if not title:
            continue
        score, label = score_sentiment(title)
        items.append({
            "title": title,
            "publisher": entry.get("source", "Finnhub"),
            "link": entry.get("url", ""),
            "published": entry.get("datetime", ""),
            "sentiment_score": score,
            "sentiment_label": label,
        })
    return items


def get_news(ticker, limit=8):
    """
    Returns (news_items, aggregate_summary) where aggregate_summary is
    {"avg_score": float, "label": str, "positive": n, "negative": n, "neutral": n}
    """
    items = _from_yfinance(ticker, limit=limit)
    if not items:
        items = _from_finnhub(ticker, limit=limit)

    if not items:
        return [], {"avg_score": 0.0, "label": "no data", "positive": 0, "negative": 0, "neutral": 0}

    pos = sum(1 for i in items if i["sentiment_label"] == "positive")
    neg = sum(1 for i in items if i["sentiment_label"] == "negative")
    neu = len(items) - pos - neg
    avg = round(sum(i["sentiment_score"] for i in items) / len(items), 2)
    if avg > 0.15:
        label = "mostly positive"
    elif avg < -0.15:
        label = "mostly negative"
    else:
        label = "mixed / neutral"

    return items, {"avg_score": avg, "label": label, "positive": pos, "negative": neg, "neutral": neu}
