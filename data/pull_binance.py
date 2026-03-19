"""Download historical OHLCV data from Binance and save to CSV.

Pulls 1h candles for configured trading pairs and stores them
in data/historical/ for offline backtesting and strategy training.

Usage:
    python -m data.pull_binance --days 90
    python -m data.pull_binance --days 365 --pairs BTC/USD ETH/USD SOL/USD
"""

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import ccxt
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

HISTORICAL_DIR = Path("data/historical")


def pull_ohlcv(
    symbol: str,
    days: int = 90,
    timeframe: str = "1h",
) -> pd.DataFrame:
    """Fetch historical OHLCV candles from Binance.

    Args:
        symbol: Binance trading pair (e.g. "BTC/USDT").
        days: Number of days of history to fetch.
        timeframe: Candle interval.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    total_candles = days * 24  # 1h candles
    all_candles: list[list] = []
    since: Optional[int] = None

    # Calculate start time
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    since = now_ms - (days * 24 * 60 * 60 * 1000)

    logger.info("Fetching %d candles for %s (%d days)...", total_candles, symbol, days)

    remaining = total_candles
    while remaining > 0:
        batch_limit = min(remaining, 1000)
        kwargs: dict[str, Any] = {"limit": batch_limit}
        if since is not None:
            kwargs["since"] = since

        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, **kwargs)
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
    # Remove duplicates by timestamp
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    logger.info("Fetched %d candles for %s", len(df), symbol)
    return df


def save_ohlcv(df: pd.DataFrame, pair: str, timeframe: str = "1h") -> Path:
    """Save OHLCV DataFrame to CSV.

    Args:
        df: OHLCV data.
        pair: Trading pair name (e.g. "BTC/USD").
        timeframe: Candle interval for filename.

    Returns:
        Path to the saved CSV file.
    """
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = pair.replace("/", "_")
    filename = f"{safe_name}_{timeframe}.csv"
    path = HISTORICAL_DIR / filename
    df.to_csv(path, index=False)
    logger.info("Saved %d rows to %s", len(df), path)
    return path


def load_ohlcv(pair: str, timeframe: str = "1h") -> Optional[pd.DataFrame]:
    """Load previously saved OHLCV data from CSV.

    Args:
        pair: Trading pair name (e.g. "BTC/USD").
        timeframe: Candle interval.

    Returns:
        DataFrame or None if file doesn't exist.
    """
    safe_name = pair.replace("/", "_")
    filename = f"{safe_name}_{timeframe}.csv"
    path = HISTORICAL_DIR / filename
    if not path.exists():
        return None
    df = pd.read_csv(path)
    logger.info("Loaded %d rows from %s", len(df), path)
    return df


def roostoo_to_binance(pair: str) -> str:
    """Convert Roostoo pair to Binance pair. e.g. BTC/USD -> BTC/USDT."""
    base = pair.split("/")[0]
    return f"{base}/USDT"


def pull_all(pairs: list[str], days: int = 90, timeframe: str = "1h") -> dict[str, Path]:
    """Pull and save OHLCV data for multiple pairs.

    Args:
        pairs: List of Roostoo trading pairs.
        days: Days of history.
        timeframe: Candle interval.

    Returns:
        Dict mapping pair to saved CSV path.
    """
    saved = {}
    for pair in pairs:
        binance_symbol = roostoo_to_binance(pair)
        df = pull_ohlcv(binance_symbol, days=days, timeframe=timeframe)
        path = save_ohlcv(df, pair, timeframe)
        saved[pair] = path
    return saved


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Pull historical OHLCV from Binance.")
    parser.add_argument(
        "--days", type=int, default=90, help="Days of history to fetch (default: 90)"
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=None,
        help="Trading pairs (default: from config.yaml)",
    )
    parser.add_argument(
        "--timeframe", type=str, default="1h", help="Candle interval (default: 1h)"
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml", help="Path to config file"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    pairs = args.pairs
    if pairs is None:
        config_path = Path(args.config)
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            pairs = config.get("trading", {}).get("pairs", ["BTC/USD", "ETH/USD", "SOL/USD"])
        else:
            pairs = ["BTC/USD", "ETH/USD", "SOL/USD"]

    saved = pull_all(pairs, days=args.days, timeframe=args.timeframe)
    print(f"\nPulled data for {len(saved)} pairs:")
    for pair, path in saved.items():
        print(f"  {pair} -> {path}")


if __name__ == "__main__":
    main()
