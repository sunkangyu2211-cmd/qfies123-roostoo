"""Data feed helpers for the backtrader-based backtester.

Fetches historical OHLCV from Binance via ccxt and converts
to backtrader PandasData feeds. Also fetches historical Fear & Greed.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import backtrader as bt
import ccxt
import pandas as pd
import requests

logger = logging.getLogger(__name__)


def fetch_binance_feed(
    pair: str,
    days: int = 30,
    interval: str = "1h",
) -> bt.feeds.PandasData:
    """Fetch Binance OHLCV and return as a backtrader data feed.

    Args:
        pair: Roostoo-style pair (e.g. "BTC/USD").
        days: Number of days of history.
        interval: Candle interval (default "1h").

    Returns:
        A backtrader PandasData feed ready for cerebro.adddata().
    """
    binance_symbol = f"{pair.split('/')[0]}/USDT"
    exchange = ccxt.binance()
    total_candles = days * 24 + 100  # extra for indicator warmup

    logger.info("Fetching %d candles for %s...", total_candles, binance_symbol)

    all_candles: list[list] = []
    since: Optional[int] = None
    remaining = total_candles

    while remaining > 0:
        batch_limit = min(remaining, 1000)
        kwargs: dict[str, Any] = {"limit": batch_limit}
        if since is not None:
            kwargs["since"] = since

        batch = exchange.fetch_ohlcv(binance_symbol, interval, **kwargs)
        if not batch:
            break

        all_candles.extend(batch)
        since = batch[-1][0] + 1
        remaining -= len(batch)

        if len(batch) < batch_limit:
            break

    df = pd.DataFrame(
        all_candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("datetime")
    df = df[["open", "high", "low", "close", "volume"]]

    if len(df) > total_candles:
        df = df.tail(total_candles)

    logger.info("  Got %d candles for %s", len(df), pair)

    return bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # use index
        open="open",
        high="high",
        low="low",
        close="close",
        volume="volume",
        openinterest=-1,
    )


def fetch_fear_greed(days: int = 30) -> dict[str, int]:
    """Fetch historical Fear & Greed index.

    Args:
        days: Number of days of history.

    Returns:
        Dict mapping date string ("YYYY-MM-DD") to F&G value (0-100).
    """
    fng_map: dict[str, int] = {}
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": days + 5, "date_sort": "asc"},
            timeout=10,
        )
        data = resp.json().get("data", [])
        for entry in data:
            ts = int(entry["timestamp"])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            date_key = dt.strftime("%Y-%m-%d")
            fng_map[date_key] = int(entry["value"])
        logger.info("Loaded %d Fear & Greed entries.", len(fng_map))
    except Exception as exc:
        logger.warning("Failed to fetch Fear & Greed history: %s", exc)
    return fng_map
