"""
Kronos AI Stock Assistant package.

Submodules (forecaster, data_fetcher, screener, …) can be imported without
loading the heavy StockAssistant / model stack. Use:

    from assistant.core_assistant import StockAssistant
"""

__all__ = ["StockAssistant"]


def __getattr__(name):
    if name == "StockAssistant":
        from .core_assistant import StockAssistant
        return StockAssistant
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
