"""
Tests for assistant/copilot.py -- the tool-dispatch helper and the
availability guard in answer(). The full genai function-calling loop
needs the real google-genai package/API and isn't exercised here (that's
an integration concern, not a unit-testable one without a live key);
these tests cover what IS unit-testable: dispatch-by-name correctness,
and that answer() degrades to None (triggering the existing
general_chat() fallback in core_assistant.py) whenever the client isn't
available, without ever raising.
"""
import pytest

from assistant import copilot


def test_dispatch_known_tool(monkeypatch):
    monkeypatch.setitem(copilot.tools.TOOL_REGISTRY, "get_kronos_forecast",
                         lambda ticker, horizon=14: {"ticker": ticker, "horizon": horizon})
    result = copilot._dispatch_tool_call("get_kronos_forecast", {"ticker": "AAPL", "horizon": 30})
    assert result == {"ticker": "AAPL", "horizon": 30}


def test_dispatch_unknown_tool_returns_error_not_raise():
    result = copilot._dispatch_tool_call("not_a_real_tool", {})
    assert "error" in result
    assert "not_a_real_tool" in result["error"]


def test_dispatch_bad_arguments_returns_error_not_raise(monkeypatch):
    monkeypatch.setitem(copilot.tools.TOOL_REGISTRY, "get_kronos_forecast",
                         lambda ticker, horizon=14: {"ticker": ticker})
    result = copilot._dispatch_tool_call("get_kronos_forecast", {"not_a_real_kwarg": 1})
    assert "error" in result


def test_answer_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(copilot.llm, "_get_client", lambda: None)
    result = copilot.answer("why is AAPL declining and what would change that?",
                             context_tickers=["AAPL"])
    assert result is None


def test_answer_returns_none_and_does_not_raise_on_loop_exception(monkeypatch):
    class ExplodingClient:
        pass  # any use of .models.generate_content will AttributeError

    monkeypatch.setattr(copilot.llm, "_get_client", lambda: ExplodingClient())
    # _call_with_timeout catches everything and returns the default (None)
    # -- this must never propagate an exception up into core_assistant.
    result = copilot.answer("what about MSFT too?", context_tickers=["AAPL"])
    assert result is None


def test_tool_declarations_match_registry():
    declared_names = {d["name"] for d in copilot.TOOL_DECLARATIONS}
    registry_names = set(copilot.tools.TOOL_REGISTRY.keys())
    assert declared_names == registry_names
