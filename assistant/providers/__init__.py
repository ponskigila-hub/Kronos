"""
Registry + factory for MarketDataProvider implementations, and the
fallback logic used by assistant.data_fetcher.

Kept intentionally small: a plain dict registry, not a plugin system with
auto-discovery -- there are two providers today, and a solo developer
adding a third can register it here in one line. Do not over-engineer
this until there's an actual third-party need for dynamic registration.
"""
import logging

from .base import MarketDataProvider, ProviderDataError
from .yfinance_provider import YFinanceProvider
from .twelvedata_provider import TwelveDataProvider
from ..config import MARKET_DATA_PROVIDER, MARKET_DATA_FALLBACK_PROVIDER

logger = logging.getLogger(__name__)

_REGISTRY = {
    "yfinance": YFinanceProvider,
    "twelvedata": TwelveDataProvider,
}

_instances = {}  # name -> singleton instance, lazily constructed


def get_provider(name: str = None) -> MarketDataProvider:
    """Get (and cache) a provider instance by name. Defaults to
    MARKET_DATA_PROVIDER from config/.env."""
    name = (name or MARKET_DATA_PROVIDER or "yfinance").lower()
    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY)
        raise ValueError(f"Unknown market data provider '{name}'. Available: {available}")
    if name not in _instances:
        _instances[name] = _REGISTRY[name]()
    return _instances[name]


def get_history_with_fallback(symbol: str, lookback_days: int, interval: str = "1d"):
    """
    Try the configured primary provider; if it raises ProviderDataError and
    MARKET_DATA_FALLBACK_PROVIDER is set, try that one too. Returns
    (dataframe, provider_name_used).

    Deliberately does NOT try to merge/stitch data from both providers on
    a partial failure -- two providers can disagree on adjusted vs.
    unadjusted prices, corporate-action handling, or session boundaries,
    and silently blending them would produce a history that's internally
    inconsistent in ways that are hard to detect later. Either one
    provider succeeds cleanly, or the next one is tried as a full
    replacement, never a merge.
    """
    primary = get_provider(MARKET_DATA_PROVIDER)
    try:
        return primary.get_history(symbol, lookback_days, interval), primary.name
    except ProviderDataError as primary_error:
        if not MARKET_DATA_FALLBACK_PROVIDER:
            raise
        logger.warning(
            "Primary provider '%s' failed for '%s' (%s); trying fallback '%s'.",
            primary.name, symbol, primary_error, MARKET_DATA_FALLBACK_PROVIDER,
        )
        fallback = get_provider(MARKET_DATA_FALLBACK_PROVIDER)
        try:
            return fallback.get_history(symbol, lookback_days, interval), fallback.name
        except ProviderDataError as fallback_error:
            raise ProviderDataError(
                f"Both providers failed for '{symbol}': "
                f"{primary.name}: {primary_error}; {fallback.name}: {fallback_error}"
            )


__all__ = [
    "MarketDataProvider", "ProviderDataError",
    "YFinanceProvider", "TwelveDataProvider",
    "get_provider", "get_history_with_fallback",
]
