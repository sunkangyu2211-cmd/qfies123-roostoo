"""Performance metrics calculator.

Computes Sortino, Sharpe, Calmar ratios and max drawdown from
portfolio snapshot logs. Can be run as a standalone module.
"""

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

ANNUALIZATION_FACTOR: float = 365.0
RISK_FREE_RATE: float = 0.0


class MetricsCalculator:
    """Computes risk-adjusted performance metrics from trade logs.

    Reads portfolio_snapshot records from a JSONL log file and
    calculates standard portfolio performance metrics.
    """

    def __init__(self, log_file_path: str) -> None:
        """Initialize with path to the JSONL log file.

        Args:
            log_file_path: Path to newline-delimited JSON log.
        """
        self.log_path = Path(log_file_path)

    def load_snapshots(self) -> pd.DataFrame:
        """Read portfolio value snapshots from the log file.

        Returns:
            DataFrame with columns [timestamp, portfolio_value_usd],
            sorted by timestamp.
        """
        records: list[dict] = []
        if not self.log_path.exists():
            logger.warning("Log file %s does not exist.", self.log_path)
            return pd.DataFrame(columns=["timestamp", "portfolio_value_usd"])

        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "portfolio_snapshot":
                    records.append(
                        {
                            "timestamp": record["timestamp_ms"],
                            "portfolio_value_usd": record["portfolio_value_usd"],
                        }
                    )

        df = pd.DataFrame(records)
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def daily_returns(self) -> pd.Series:
        """Compute daily return series from portfolio snapshots.

        Resamples to daily frequency using last value per day,
        then computes percentage change.

        Returns:
            Series of daily returns.
        """
        snapshots = self.load_snapshots()
        if snapshots.empty or len(snapshots) < 2:
            return pd.Series(dtype=float)

        daily = (
            snapshots.set_index("timestamp")["portfolio_value_usd"]
            .resample("1D")
            .last()
            .dropna()
        )
        returns = daily.pct_change().dropna()
        return returns

    def sharpe_ratio(self) -> Optional[float]:
        """Calculate annualized Sharpe ratio.

        Returns:
            Sharpe ratio, or None if insufficient data.
        """
        returns = self.daily_returns()
        if returns.empty or returns.std() == 0:
            return None
        excess = returns.mean() - (RISK_FREE_RATE / ANNUALIZATION_FACTOR)
        sharpe = (excess / returns.std()) * math.sqrt(ANNUALIZATION_FACTOR)
        return float(sharpe)

    def sortino_ratio(self) -> Optional[float]:
        """Calculate annualized Sortino ratio.

        Uses only downside deviation (negative returns) in denominator.

        Returns:
            Sortino ratio, or None if insufficient data.
        """
        returns = self.daily_returns()
        if returns.empty:
            return None
        downside = returns[returns < 0]
        if downside.empty or downside.std() == 0:
            return None
        excess = returns.mean() - (RISK_FREE_RATE / ANNUALIZATION_FACTOR)
        sortino = (excess / downside.std()) * math.sqrt(ANNUALIZATION_FACTOR)
        return float(sortino)

    def max_drawdown(self) -> Optional[float]:
        """Calculate maximum drawdown from portfolio snapshots.

        Returns:
            Max drawdown as a positive fraction (e.g. 0.15 = 15%),
            or None if insufficient data.
        """
        snapshots = self.load_snapshots()
        if snapshots.empty or len(snapshots) < 2:
            return None

        values = snapshots["portfolio_value_usd"].values
        peak = values[0]
        max_dd = 0.0
        for value in values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return float(max_dd)

    def calmar_ratio(self) -> Optional[float]:
        """Calculate annualized Calmar ratio.

        Calmar = annualized return / max drawdown.

        Returns:
            Calmar ratio, or None if insufficient data.
        """
        returns = self.daily_returns()
        max_dd = self.max_drawdown()
        if returns.empty or max_dd is None or max_dd == 0:
            return None
        annualized_return = returns.mean() * ANNUALIZATION_FACTOR
        calmar = annualized_return / max_dd
        return float(calmar)

    def print_summary(self) -> None:
        """Print a formatted summary of all performance metrics."""
        snapshots = self.load_snapshots()
        print("\n" + "=" * 60)
        print("  PERFORMANCE METRICS SUMMARY")
        print("=" * 60)

        if snapshots.empty:
            print("  No portfolio snapshots found in log file.")
            print("=" * 60)
            return

        start_val = snapshots["portfolio_value_usd"].iloc[0]
        end_val = snapshots["portfolio_value_usd"].iloc[-1]
        total_return = (end_val - start_val) / start_val if start_val else 0

        print(f"  Start Value:     ${start_val:>14,.2f}")
        print(f"  End Value:       ${end_val:>14,.2f}")
        print(f"  Total Return:    {total_return:>14.2%}")
        print(f"  Snapshots:       {len(snapshots):>14d}")
        print("-" * 60)

        _print_metric("Sharpe Ratio", self.sharpe_ratio())
        _print_metric("Sortino Ratio", self.sortino_ratio())
        _print_metric("Calmar Ratio", self.calmar_ratio())
        _print_metric("Max Drawdown", self.max_drawdown(), is_pct=True)

        print("=" * 60 + "\n")


def _print_metric(
    name: str,
    value: Optional[float],
    is_pct: bool = False,
) -> None:
    """Print a single metric line.

    Args:
        name: Metric display name.
        value: Metric value, or None if unavailable.
        is_pct: If True, format as percentage.
    """
    if value is None:
        print(f"  {name:<18s} {'N/A':>14s}")
    elif is_pct:
        print(f"  {name:<18s} {value:>14.2%}")
    else:
        print(f"  {name:<18s} {value:>14.4f}")


def main() -> None:
    """CLI entrypoint for standalone metrics calculation."""
    parser = argparse.ArgumentParser(
        description="Calculate trading performance metrics from log file."
    )
    parser.add_argument(
        "--log",
        type=str,
        required=True,
        help="Path to the JSONL trade log file.",
    )
    args = parser.parse_args()
    calc = MetricsCalculator(args.log)
    calc.print_summary()


if __name__ == "__main__":
    main()
