"""External market data feeds.

Fetches OHLCV candles from Binance (via ccxt), Fear & Greed index,
and Roostoo ticker prices. Includes in-memory TTL caching for OHLCV data.
"""

import logging
import time
from typing import Any, Optional

import ccxt
import pandas as pd
import requests

logger = logging.getLogger(__name__)


class DataFeed:
    """Aggregates market data from multiple external sources.

    Provides cached OHLCV candles, Fear & Greed index,
    and Roostoo ticker prices.
    """

    FEAR_GREED_URL: str = "https://api.alternative.me/fng/?limit=1"

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize data feeds with configuration.

        Args:
            config: Data config section from config.yaml.
        """
        self.ohlcv_interval: str = config.get("ohlcv_interval", "1h")
        self.ohlcv_limit: int = config.get("ohlcv_limit", 100)
        self.cache_ttl: int = config.get("cache_ttl_seconds", 300)
        self.exchange = ccxt.binance({"enableRateLimit": True})
        self._ohlcv_cache: dict[str, tuple[float, pd.DataFrame]] = {}

    def get_ohlcv(
        self,
        coin: str,
        interval: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV candles from Binance public API.

        Uses in-memory cache with TTL to avoid redundant fetches.

        Args:
            coin: Trading pair in Binance format (e.g. "BTC/USDT").
            interval: Candle interval (e.g. "1h"). Defaults to config.
            limit: Number of candles. Defaults to config.

        Returns:
            DataFrame with columns [timestamp, open, high, low, close, volume],
            or None on failure.
        """
        interval = interval or self.ohlcv_interval
        limit = limit or self.ohlcv_limit
        cache_key = f"{coin}:{interval}:{limit}"

        cached = self._ohlcv_cache.get(cache_key)
        if cached is not None:
            cached_time, cached_df = cached
            if time.time() - cached_time < self.cache_ttl:
                logger.debug("OHLCV cache hit for %s", cache_key)
                return cached_df

        try:
            raw = self.exchange.fetch_ohlcv(coin, timeframe=interval, limit=limit)
            df = pd.DataFrame(
                raw,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            self._ohlcv_cache[cache_key] = (time.time(), df)
            logger.info("Fetched %d candles for %s (%s)", len(df), coin, interval)
            return df
        except ccxt.BaseError as exc:
            logger.error("Failed to fetch OHLCV for %s: %s", coin, exc)
            return None

    def get_fear_greed(self) -> Optional[int]:
        """Fetch the current Fear & Greed index value.

        Returns:
            Integer 0-100 (0=extreme fear, 100=extreme greed), or None.
        """
        try:
            resp = requests.get(self.FEAR_GREED_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            value = int(data["data"][0]["value"])
            logger.info("Fear & Greed index: %d", value)
            return value
        except (requests.RequestException, KeyError, ValueError) as exc:
            logger.error("Failed to fetch Fear & Greed index: %s", exc)
            return None

    def get_roostoo_prices(self, client: Any) -> Optional[dict[str, dict[str, float]]]:
        """Fetch all ticker prices from the Roostoo exchange.

        Args:
            client: RoostooClient instance.

        Returns:
            Dict mapping pair to price data, or None on failure.
        """
        data = client.get_ticker()
        if data is None:
            return None
        return _parse_ticker_response(data)

    def get_binance_symbol(self, roostoo_pair: str) -> str:
        """Convert Roostoo pair format to Binance format.

        Args:
            roostoo_pair: Pair in Roostoo format (e.g. "BTC/USD").

        Returns:
            Pair in Binance format (e.g. "BTC/USDT").
        """
        base = roostoo_pair.split("/")[0]
        return f"{base}/USDT"


def _parse_ticker_response(
    data: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """Parse Roostoo ticker response into a clean price dict.

    Args:
        data: Raw ticker API response.

    Returns:
        Dict mapping pair to {bid, ask, last, change} floats.
    """
    prices: dict[str, dict[str, float]] = {}
    ticker_data = data.get("Data", data.get("Tickers", data))
    if isinstance(ticker_data, dict):
        for pair, info in ticker_data.items():
            if not isinstance(info, dict):
                continue
            prices[pair] = {
                "bid": float(info.get("MaxBid", info.get("Bid", 0))),
                "ask": float(info.get("MinAsk", info.get("Ask", 0))),
                "last": float(info.get("LastPrice", info.get("Last", 0))),
                "change": float(info.get("Change", 0)),
            }
    return prices
