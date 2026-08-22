"""
Second MarketDataProvider implementation, proving the interface is
actually swappable rather than a paper abstraction over a single
hardcoded source.

Why Twelve Data specifically (see PROVIDERS.md for the full comparison
table against Finnhub / Alpha Vantage / Polygon / FMP / Alpaca):
  - Free tier covers daily OHLCV for global equities, ETFs, and crypto
    with a plain REST GET -- no SDK, no OAuth dance.
  - 800 requests/day on the free tier is generous enough for a solo-dev
    deployment relying primarily on the (free, unlimited) yfinance
    default and only calling this as an occasional fallback.
  - Response schema is already close to OHLCV, minimizing normalization
    surface area (and therefore bugs) compared to providers that return
    deeply nested or inconsistent shapes.

Requires TWELVEDATA_API_KEY to be set; get_history raises ProviderDataError
immediately (not a network call) if it isn't, so a misconfigured fallback
fails fast and obviously instead of timing out.
"""
import pandas as pd
import requests

from .base import MarketDataProvider, ProviderDataError
from ..config import TWELVEDATA_API_KEY

_BASE_URL = "https://api.twelvedata.com/time_series"

_INTERVAL_MAP = {
    "1d": "1day",
    "1wk": "1week",
    "1mo": "1month",
}


class TwelveDataProvider(MarketDataProvider):
    name = "twelvedata"

    def _require_key(self):
        if not TWELVEDATA_API_KEY:
            raise ProviderDataError(
                "TWELVEDATA_API_KEY is not set -- can't use the Twelve Data provider."
            )

    def get_history(self, symbol: str, lookback_days: int, interval: str = "1d") -> pd.DataFrame:
        self._require_key()
        td_interval = _INTERVAL_MAP.get(interval, "1day")

        try:
            resp = requests.get(
                _BASE_URL,
                params={
                    "symbol": symbol,
                    "interval": td_interval,
                    "outputsize": min(lookback_days, 5000),
                    "apikey": TWELVEDATA_API_KEY,
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            raise ProviderDataError(f"Twelve Data request failed for '{symbol}': {e}")

        if not isinstance(payload, dict) or payload.get("status") == "error":
            message = payload.get("message", "unknown error") if isinstance(payload, dict) else "malformed response"
            raise ProviderDataError(f"Twelve Data couldn't resolve '{symbol}': {message}")

        rows = payload.get("values") or []
        if not rows:
            raise ProviderDataError(f"No historical data returned for '{symbol}' from Twelve Data.")

        df = pd.DataFrame(rows)
        df = df.rename(columns={"datetime": "timestamps"})
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        if df.empty:
            raise ProviderDataError(f"No usable historical rows for '{symbol}' after cleaning.")

        df["volume"] = df["volume"].fillna(0)
        df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)

        # Twelve Data returns newest-first.
        df = df.iloc[::-1].reset_index(drop=True)
        if len(df) > lookback_days:
            df = df.iloc[-lookback_days:].reset_index(drop=True)

        return self.normalize(df)

    def validate_symbol(self, symbol: str) -> bool:
        self._require_key()
        try:
            resp = requests.get(
                "https://api.twelvedata.com/symbol_search",
                params={"symbol": symbol, "apikey": TWELVEDATA_API_KEY},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            return any(d.get("symbol", "").upper() == symbol.upper() for d in data)
        except Exception:
            return False
