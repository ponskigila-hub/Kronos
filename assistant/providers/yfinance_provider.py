"""
The default provider -- wraps yfinance exactly as data_fetcher.py and
ticker_utils.py did before the provider abstraction existed. The
download/clean/reshape logic here is unchanged from the original
data_fetcher.fetch_history; it has only been moved behind the
MarketDataProvider interface so it can be swapped for another source
without touching any caller.
"""
import pandas as pd
import yfinance as yf

from .base import MarketDataProvider, ProviderDataError


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def get_history(self, symbol: str, lookback_days: int, interval: str = "1d") -> pd.DataFrame:
        # Pull extra calendar days to survive weekends/holidays and still
        # end up with `lookback_days` trading rows.
        period_days = int(lookback_days * 1.6) + 10

        df = yf.download(
            symbol,
            period=f"{period_days}d",
            interval=interval,
            auto_adjust=False,
            progress=False,
        )

        if df is None or df.empty:
            raise ProviderDataError(f"No historical data returned for '{symbol}' from yfinance.")

        # yfinance sometimes returns a MultiIndex on columns (esp. for
        # multi-ticker calls, but occasionally on single-ticker calls in
        # newer versions too).
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })

        # Handle missing values instead of silently failing: forward-fill
        # small gaps (e.g. a single missing print), then drop any rows
        # that are still incomplete (e.g. leading NaNs before the asset
        # existed).
        df[["open", "high", "low", "close", "volume"]] = (
            df[["open", "high", "low", "close", "volume"]].ffill()
        )
        df = df.dropna(subset=["open", "high", "low", "close"])
        if df.empty:
            raise ProviderDataError(f"No usable historical rows for '{symbol}' after cleaning.")

        df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)

        df = df.reset_index()
        date_col = "Date" if "Date" in df.columns else "Datetime"
        df = df.rename(columns={date_col: "timestamps"})

        if len(df) > lookback_days:
            df = df.iloc[-lookback_days:].reset_index(drop=True)

        return self.normalize(df)

    def validate_symbol(self, symbol: str) -> bool:
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            return hist is not None and not hist.empty
        except Exception:
            return False

    def get_quote(self, symbol: str) -> dict:
        try:
            fast = yf.Ticker(symbol).fast_info
            price = fast.get("lastPrice") if hasattr(fast, "get") else getattr(fast, "last_price", None)
            if price is None:
                raise ProviderDataError(f"No quote available for '{symbol}'.")
            currency = fast.get("currency") if hasattr(fast, "get") else getattr(fast, "currency", "USD")
            return {"price": float(price), "currency": currency or "USD", "as_of": None}
        except ProviderDataError:
            raise
        except Exception as e:
            raise ProviderDataError(f"Quote lookup failed for '{symbol}': {e}")
