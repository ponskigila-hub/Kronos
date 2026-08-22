"""
Unit tests for assistant.llm._call_with_timeout -- confirms a slow or
failing LLM call degrades to the fallback value instead of blocking or
raising, and that a fast successful call returns normally. No real Gemini
client or API key involved.
"""
import time

from assistant import llm


def test_fast_call_returns_result():
    result = llm._call_with_timeout(lambda: "polished text", 1.0, default="fallback")
    assert result == "polished text"


def test_slow_call_times_out_and_returns_default():
    def slow():
        time.sleep(2.0)
        return "too late"

    start = time.time()
    result = llm._call_with_timeout(slow, 0.2, default="fallback")
    elapsed = time.time() - start

    assert result == "fallback"
    assert elapsed < 1.0  # returned near the timeout, not after the full 2s sleep


def test_exception_returns_default_without_raising():
    def boom():
        raise RuntimeError("Gemini is down")

    result = llm._call_with_timeout(boom, 1.0, default="fallback")
    assert result == "fallback"


def test_polish_explanation_falls_back_when_no_client(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: None)
    text = "AAPL is expected to rise 3% over 14 days."
    assert llm.polish_explanation(text, ticker="AAPL") == text


def test_polish_explanation_empty_text_short_circuits():
    assert llm.polish_explanation("", ticker="AAPL") == ""


def test_polish_explanation_times_out_and_keeps_original_text(monkeypatch):
    class SlowClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                time.sleep(2.0)
                raise AssertionError("should have been abandoned at the timeout")

    monkeypatch.setattr(llm, "_get_client", lambda: SlowClient())
    monkeypatch.setattr(llm, "LLM_POLISH_TIMEOUT_SECONDS", 0.2)
    text = "AAPL is expected to rise 3% over 14 days."

    start = time.time()
    result = llm.polish_explanation(text, ticker="AAPL")
    elapsed = time.time() - start

    assert result == text  # unpolished original preserved, not blank/broken
    assert elapsed < 1.0
