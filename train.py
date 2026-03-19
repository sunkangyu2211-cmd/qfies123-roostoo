"""Training pipeline — evaluate all strategies and select the best.

Pulls historical data from Binance, backtests every registered strategy,
ranks them by the competition's composite score (0.4*Sortino + 0.3*Sharpe + 0.3*Calmar),
and selects the best. Falls back to buy-and-hold if no strategy beats it.

The result is saved to state/selected_strategy.json so bot.py can load it.

Usage:
    python train.py
    python train.py --days 90 --capital 1000000
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from backtest.engine import BacktestEngine
from data.pull_binance import pull_all, load_ohlcv
from strategy import STRATEGY_REGISTRY, BaseStrategy

logger = logging.getLogger(__name__)

SELECTION_FILE = Path("state/selected_strategy.json")


def composite_score(metrics: dict[str, Any]) -> float:
    """Compute the competition composite risk-adjusted score.

    Formula: 0.4 * Sortino + 0.3 * Sharpe + 0.3 * Calmar

    Args:
        metrics: Dict with sortino, sharpe, calmar keys.

    Returns:
        Composite score (higher is better). Returns -inf for invalid metrics.
    """
    sortino = metrics.get("sortino")
    sharpe = metrics.get("sharpe")
    calmar = metrics.get("calmar")

    if sortino is None or sharpe is None or calmar is None:
        return float("-inf")

    return 0.4 * sortino + 0.3 * sharpe + 0.3 * calmar


def evaluate_strategy(
    name: str,
    strategy: BaseStrategy,
    config_path: str = "config.yaml",
    days: int = 60,
    capital: float = 1_000_000.0,
) -> dict[str, Any]:
    """Run a backtest for a single strategy and return results.

    Args:
        name: Strategy name for logging.
        strategy: Strategy instance to evaluate.
        config_path: Path to config.yaml.
        days: Backtest period in days.
        capital: Starting capital.

    Returns:
        Dict with strategy name, metrics, and composite score.
    """
    logger.info("Evaluating strategy: %s", name)

    engine = BacktestEngine(
        config_path=config_path,
        days=days,
        starting_capital=capital,
        strategy=strategy,
    )
    metrics = engine.run()

    score = composite_score(metrics)
    result = {
        "name": name,
        "metrics": metrics,
        "composite_score": score,
    }

    total_return = metrics.get("total_return", 0)
    logger.info(
        "  %s: return=%.2f%%, score=%.4f, trades=%d",
        name,
        total_return * 100,
        score,
        metrics.get("total_trades", 0),
    )
    return result


def train(
    config_path: str = "config.yaml",
    days: int = 60,
    capital: float = 1_000_000.0,
    pull_data: bool = True,
    strategies: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Run the full training pipeline.

    1. Pull historical data from Binance (if requested)
    2. Backtest all strategies
    3. Select the best one (or buy-and-hold as fallback)
    4. Save the selection

    Args:
        config_path: Path to config.yaml.
        days: Days of historical data for backtesting.
        capital: Starting capital for backtests.
        pull_data: Whether to pull fresh data from Binance.
        strategies: List of strategy names to evaluate (default: all).

    Returns:
        Dict with selected strategy name and all results.
    """
    # Load config for pairs
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    pairs = config.get("trading", {}).get("pairs", ["BTC/USD", "ETH/USD", "SOL/USD"])
    strategy_config = config.get("strategy", {})

    # Step 1: Pull data
    if pull_data:
        logger.info("Pulling historical data from Binance...")
        pull_all(pairs, days=days + 10)  # Extra days for warmup
        logger.info("Data pull complete.")

    # Step 2: Evaluate strategies
    strategy_names = strategies or list(STRATEGY_REGISTRY.keys())
    results: list[dict[str, Any]] = []

    for name in strategy_names:
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unknown strategy: %s, skipping.", name)
            continue

        try:
            strategy = cls(strategy_config)
            result = evaluate_strategy(
                name=name,
                strategy=strategy,
                config_path=config_path,
                days=days,
                capital=capital,
            )
            results.append(result)
        except Exception as exc:
            logger.error("Failed to evaluate %s: %s", name, exc)

    if not results:
        logger.error("No strategies evaluated successfully.")
        return {"selected": "buy_and_hold", "results": []}

    # Step 3: Rank and select
    # Sort by composite score (descending)
    results.sort(key=lambda r: r["composite_score"], reverse=True)

    print("\n" + "=" * 80)
    print("  STRATEGY TRAINING RESULTS")
    print("=" * 80)
    print(f"  {'Rank':<5} {'Strategy':<22} {'Return':>10} {'Sharpe':>10} "
          f"{'Sortino':>10} {'Calmar':>10} {'Score':>10}")
    print("-" * 80)

    for i, r in enumerate(results):
        m = r["metrics"]
        ret = m.get("total_return", 0) * 100
        sharpe = m.get("sharpe")
        sortino = m.get("sortino")
        calmar = m.get("calmar")
        score = r["composite_score"]

        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "N/A"
        sortino_str = f"{sortino:.4f}" if sortino is not None else "N/A"
        calmar_str = f"{calmar:.4f}" if calmar is not None else "N/A"
        score_str = f"{score:.4f}" if score != float("-inf") else "N/A"

        print(f"  {i+1:<5} {r['name']:<22} {ret:>9.2f}% {sharpe_str:>10} "
              f"{sortino_str:>10} {calmar_str:>10} {score_str:>10}")

    print("=" * 80)

    # Find buy-and-hold result for comparison
    bnh_result = next((r for r in results if r["name"] == "buy_and_hold"), None)
    bnh_score = bnh_result["composite_score"] if bnh_result else float("-inf")

    # Select best strategy
    best = results[0]
    selected_name = best["name"]

    # If the best active strategy doesn't beat buy-and-hold, fall back
    if selected_name != "buy_and_hold" and best["composite_score"] <= bnh_score:
        selected_name = "buy_and_hold"
        logger.info("No active strategy beats buy-and-hold. Falling back.")
    elif best["composite_score"] == float("-inf"):
        selected_name = "buy_and_hold"
        logger.info("Best strategy has invalid metrics. Falling back to buy-and-hold.")

    print(f"\n  SELECTED STRATEGY: {selected_name}")
    if selected_name == "buy_and_hold":
        print("  (No active strategy outperformed buy-and-hold)")
    print()

    # Step 4: Save selection
    selection = {
        "selected_strategy": selected_name,
        "composite_score": best["composite_score"] if best["name"] == selected_name else bnh_score,
        "total_return": best["metrics"].get("total_return", 0) if best["name"] == selected_name else (
            bnh_result["metrics"].get("total_return", 0) if bnh_result else 0
        ),
        "backtest_days": days,
        "capital": capital,
        "all_rankings": [
            {"name": r["name"], "score": r["composite_score"],
             "return": r["metrics"].get("total_return", 0)}
            for r in results
        ],
    }

    SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SELECTION_FILE.open("w", encoding="utf-8") as f:
        json.dump(selection, f, indent=2)
    logger.info("Saved strategy selection to %s", SELECTION_FILE)

    return selection


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Train and evaluate all strategies, select the best one."
    )
    parser.add_argument(
        "--days", type=int, default=60, help="Days of history for backtesting (default: 60)"
    )
    parser.add_argument(
        "--capital", type=float, default=1_000_000.0,
        help="Starting capital (default: 1000000)",
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml", help="Path to config file"
    )
    parser.add_argument(
        "--no-pull", action="store_true", help="Skip pulling fresh data from Binance"
    )
    parser.add_argument(
        "--strategies", nargs="+", default=None,
        help="Specific strategies to evaluate (default: all)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    train(
        config_path=args.config,
        days=args.days,
        capital=args.capital,
        pull_data=not args.no_pull,
        strategies=args.strategies,
    )


if __name__ == "__main__":
    main()
