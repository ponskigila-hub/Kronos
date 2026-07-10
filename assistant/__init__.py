"""
Kronos AI Stock Assistant
=========================

A modular layer built on top of the Kronos forecasting model that adds:

- Automatic Yahoo Finance data retrieval (assistant.data_fetcher)
- Technical indicators (assistant.indicators)
- Multi-run Kronos forecasting with confidence bands (assistant.forecaster)
- News retrieval + lightweight sentiment (assistant.news)
- Rule-based, indicator-grounded explanations (assistant.explain)
- Interactive Plotly charts (assistant.charts)
- Watchlists (assistant.watchlist)
- Natural-language intent parsing + multi-turn context (assistant.nlp,
  assistant.conversation)
- A single platform-agnostic entry point (assistant.core_assistant.StockAssistant)
  that Discord/WhatsApp/CLI adapters all call into.

See ASSISTANT_README.md in the project root for setup and architecture notes.
"""
from .core_assistant import StockAssistant

__all__ = ["StockAssistant"]
