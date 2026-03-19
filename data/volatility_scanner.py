"""Volatility scanner — ranks coins by recent volatility and momentum.

Scans all Roostoo-listed coins that are also on Binance,
ranks them by daily volatility, and selects the top N with
positive momentum for active trading.

Usage:
    python -m data.volatility_scanner
    python -m data.volatility_scanner --top 8
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Optional

import ccxt
import numpy as np
import yaml

logger = logging.getLogger(__name__)

SCAN_RESULT_FILE = Path("state/volatile_pairs.json")

# Coins on Roostoo that are also on Binance as /USDT
ROOSTOO_BINANCE_COINS = [
    "AVAX", "BTC", "TRX", "ENA", "XRP", "POL", "BIO", "BNB", "LTC",
    "FLOKI", "FORM", "WLD", "SEI", "PEPE", "DOT", "SHIB", "PAXG",
    "FIL", "CFX", "LINK", "XLM", "TRUMP", "ZEN", "UNI", "ADA", "CAKE",
    "TAO", "SUI", "APT", "HBAR", "PENGU", "CRV", "SOL", "EIGEN",
    "PENDLE", "BONK", "AAVE", "ETH", "ICP", "TON", "VIRTUAL", "NEAR",
    "ARB", "ONDO", "WIF", "ZEC", "1000CHEEMS", "DOGE", "FET", "LISTA",
    "OMNI", "S",
]


def scan_volatility(
    lookback_hours: int = 168,
    top_n: int = 8,
    min_daily_vol: float = 0.03,
) -> list[dict[str, Any]]:
    """Scan all coins and rank by volatility.

    Args:
        lookback_hours: Hours of 1h candle data to analyze.
        top_n: Number of top coins to return.
        min_daily_vol: Minimum daily volatility threshold.

    Returns:
        List of dicts with coin stats, sorted by score (vol * momentum).
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    results = []

    for coin in ROOSTOO_BINANCE_COINS:
        symbol = f"{coin}/USDT"
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=lookback_hours)
            if len(ohlcv) < 50:
                continue

            closes = np.array([c[4] for c in ohlcv], dtype=float)
            volumes = np.array([c[5] for c in ohlcv], dtype=float)
            highs = np.array([c[2] for c in ohlcv], dtype=float)
            lows = np.array([c[3] for c in ohlcv], dtype=float)
            returns = np.diff(closes) / closes[:-1]

            daily_vol = float(np.std(returns) * np.sqrt(24))
            daily_return = float(np.mean(returns) * 24)
            avg_range = float(np.mean((highs - lows) / closes) * 100)  # avg % range per candle
            volume_usd = float(np.mean(volumes) * closes[-1])

            if daily_vol < min_daily_vol:
                continue

            # Score: volatility * positive momentum bias
            # We want high vol coins that are trending up
            momentum_bonus = max(0, daily_return) * 10  # reward positive momentum
            score = daily_vol * (1 + momentum_bonus)

            results.append({
                "coin": coin,
                "pair": f"{coin}/USD",
                "binance_symbol": symbol,
                "daily_vol": daily_vol,
                "daily_return": daily_return,
                "avg_range_pct": avg_range,
                "volume_usd": volume_usd,
                "price": float(closes[-1]),
                "score": score,
            })

        except Exception as exc:
            logger.debug("Skipping %s: %s", coin, exc)

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    logger.info("Volatility scan complete. Top %d coins:", len(top))
    for r in top:
        logger.info(
            "  %s: vol=%.1f%% ret=%.1f%% range=%.1f%% score=%.4f",
            r["coin"], r["daily_vol"] * 100, r["daily_return"] * 100,
            r["avg_range_pct"], r["score"],
        )

    return top


def save_scan_results(results: list[dict[str, Any]]) -> Path:
    """Save scan results to state file.

    Args:
        results: List of coin scan results.

    Returns:
        Path to saved file.
    """
    SCAN_RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    pairs = [r["pair"] for r in results]
    data = {
        "pairs": pairs,
        "details": results,
    }
    with SCAN_RESULT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Saved %d volatile pairs to %s", len(pairs), SCAN_RESULT_FILE)
    return SCAN_RESULT_FILE


def load_volatile_pairs() -> Optional[list[str]]:
    """Load previously scanned volatile pairs.

    Returns:
        List of pair strings, or None if no scan exists.
    """
    if not SCAN_RESULT_FILE.exists():
        return None
    with SCAN_RESULT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pairs", [])


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Scan coins for volatility.")
    parser.add_argument(
        "--top", type=int, default=8, help="Number of top coins to select (default: 8)"
    )
    parser.add_argument(
        "--lookback", type=int, default=168, help="Hours of data to analyze (default: 168)"
    )
    parser.add_argument(
        "--min-vol", type=float, default=0.03, help="Min daily volatility (default: 0.03)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    results = scan_volatility(
        lookback_hours=args.lookback,
        top_n=args.top,
        min_daily_vol=args.min_vol,
    )

    save_scan_results(results)

    print(f"\n{'Rank':<5} {'Coin':<10} {'Pair':<12} {'DailyVol':>10} {'DailyRet':>10} {'Score':>10}")
    print("-" * 60)
    for i, r in enumerate(results):
        print(
            f"{i+1:<5} {r['coin']:<10} {r['pair']:<12} "
            f"{r['daily_vol']:>9.2%} {r['daily_return']:>9.2%} {r['score']:>10.4f}"
        )


if __name__ == "__main__":
    main()
