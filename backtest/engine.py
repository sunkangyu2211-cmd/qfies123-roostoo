"""Backtesting engine for strategy evaluation.

Replays historical 1h candles through the same strategy and risk
management classes used by the live bot, simulating limit order fills,
fees, stop-losses, and the kill switch.

Usage:
    python -m backtest.engine --days 30
    python -m backtest.engine --days 90 --csv results/backtest.csv
"""

import argparse
import csv
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import ccxt
import pandas as pd
import requests
import yaml

from risk.manager import RiskManager
from strategy.base import BaseStrategy
from strategy.multi_signal import MultiSignalStrategy

logger = logging.getLogger(__name__)

ANNUALIZATION_FACTOR: float = 365.0
RISK_FREE_RATE: float = 0.0
FEE_RATE: float = 0.0005  # 0.05% maker fee
WARMUP_CANDLES: int = 100


class BacktestEngine:
    """Event-driven backtester reusing live strategy and risk classes."""

    def __init__(
        self,
        config_path: str = "config.yaml",
        days: int = 30,
        starting_capital: float = 50_000.0,
        strategy: Optional[BaseStrategy] = None,
    ) -> None:
        self.config = self._load_config(config_path)
        self.days = days
        self.starting_capital = starting_capital

        self.strategy = strategy or MultiSignalStrategy(self.config["strategy"])
        self.risk_manager = RiskManager(self.config["trading"])

        self.pairs: list[str] = self.config["trading"]["pairs"]
        self.limit_offset: float = self.config["trading"]["limit_offset_pct"]
        self.min_trade_usd: float = self.config["trading"]["min_trade_usd"]
        self.kill_pause_ms: int = (
            self.config["trading"]["kill_switch_pause_minutes"] * 60 * 1000
        )

        self.portfolio: dict[str, dict[str, str]] = {}
        self.entry_prices: dict[str, float] = {}
        self.peak_value: float = 0.0
        self.kill_switch_until: int = 0

        self.ohlcv_data: dict[str, pd.DataFrame] = {}
        self.fear_greed_map: dict[str, int] = {}
        self.snapshots: list[dict[str, Any]] = []
        self.trades: list[dict[str, Any]] = []

    @staticmethod
    def _load_config(config_path: str) -> dict[str, Any]:
        path = Path(config_path)
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _fetch_data(self) -> None:
        """Fetch historical OHLCV and Fear & Greed data."""
        exchange = ccxt.binance()
        total_candles = self.days * 24 + WARMUP_CANDLES

        for pair in self.pairs:
            binance_symbol = f"{pair.split('/')[0]}/USDT"
            logger.info("Fetching %d candles for %s...", total_candles, binance_symbol)

            all_candles: list[list] = []
            since: Optional[int] = None
            remaining = total_candles

            # Paginate if needed (Binance max ~1000 per request)
            while remaining > 0:
                batch_limit = min(remaining, 1000)
                kwargs: dict[str, Any] = {"limit": batch_limit}
                if since is not None:
                    kwargs["since"] = since

                batch = exchange.fetch_ohlcv(binance_symbol, "1h", **kwargs)
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
            # Keep only the most recent total_candles
            if len(df) > total_candles:
                df = df.tail(total_candles).reset_index(drop=True)

            self.ohlcv_data[pair] = df
            logger.info("  Got %d candles for %s", len(df), pair)

        self._fetch_fear_greed()

    def _fetch_fear_greed(self) -> None:
        """Fetch historical Fear & Greed index."""
        limit = self.days + 5
        try:
            resp = requests.get(
                "https://api.alternative.me/fng/",
                params={"limit": limit, "date_sort": "asc"},
                timeout=10,
            )
            data = resp.json().get("data", [])
            for entry in data:
                ts = int(entry["timestamp"])
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_key = dt.strftime("%Y-%m-%d")
                self.fear_greed_map[date_key] = int(entry["value"])
            logger.info("Loaded %d Fear & Greed entries.", len(self.fear_greed_map))
        except Exception as exc:
            logger.warning("Failed to fetch Fear & Greed history: %s", exc)

    def _init_portfolio(self) -> None:
        """Set up simulated portfolio matching live bot format."""
        self.portfolio = {"USD": {"Free": str(self.starting_capital), "Lock": "0"}}
        for pair in self.pairs:
            coin = pair.split("/")[0]
            if coin not in self.portfolio:
                self.portfolio[coin] = {"Free": "0", "Lock": "0"}
        self.entry_prices = {}
        self.peak_value = self.starting_capital
        self.kill_switch_until = 0

    def _get_portfolio_value(self, current_prices: dict[str, float]) -> float:
        """Compute total portfolio value in USD."""
        total = 0.0
        for coin, amounts in self.portfolio.items():
            holding = float(amounts["Free"]) + float(amounts["Lock"])
            if holding <= 0:
                continue
            if coin in ("USD", "USDT", "USDC"):
                total += holding
            else:
                pair_key = f"{coin}/USD"
                total += holding * current_prices.get(pair_key, 0.0)
        return total

    def _update_balance(self, coin: str, delta: float) -> None:
        """Add delta to a coin's Free balance."""
        if coin not in self.portfolio:
            self.portfolio[coin] = {"Free": "0", "Lock": "0"}
        current = float(self.portfolio[coin]["Free"])
        self.portfolio[coin]["Free"] = str(current + delta)

    def _build_market_data(
        self,
        pair: str,
        candle_idx: int,
        current_prices: dict[str, float],
    ) -> dict[str, Any]:
        """Build market_data dict matching the live bot's format."""
        ohlcv = self.ohlcv_data[pair]
        window = ohlcv.iloc[: candle_idx + 1].copy()

        # 24h change from candle data
        change_24h = 0.0
        if candle_idx >= 24:
            close_now = float(ohlcv.iloc[candle_idx]["close"])
            close_24ago = float(ohlcv.iloc[candle_idx - 24]["close"])
            if close_24ago > 0:
                change_24h = (close_now - close_24ago) / close_24ago * 100

        # Fear & Greed for this candle's date
        ts_ms = int(ohlcv.iloc[candle_idx]["timestamp"])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        date_key = dt.strftime("%Y-%m-%d")
        fear_greed = self.fear_greed_map.get(date_key)

        # Synthetic prices dict
        prices: dict[str, dict[str, float]] = {}
        for p in self.pairs:
            price = current_prices.get(p, 0.0)
            change_raw = 0.0
            p_ohlcv = self.ohlcv_data[p]
            if candle_idx >= 24 and candle_idx < len(p_ohlcv):
                c_now = float(p_ohlcv.iloc[candle_idx]["close"])
                c_ago = float(p_ohlcv.iloc[candle_idx - 24]["close"])
                if c_ago > 0:
                    change_raw = (c_now - c_ago) / c_ago
            prices[p] = {
                "bid": price * 0.999,
                "ask": price * 1.001,
                "last": price,
                "change": change_raw,
            }

        return {
            "pair": pair,
            "ohlcv": window,
            "change_24h": change_24h,
            "fear_greed": fear_greed,
            "prices": prices,
        }

    def _execute_fill(
        self,
        action: str,
        pair: str,
        quantity: float,
        fill_price: float,
        timestamp_ms: int,
    ) -> None:
        """Execute a simulated fill and update portfolio."""
        coin = pair.split("/")[0]
        fee = quantity * fill_price * FEE_RATE

        if action == "BUY":
            cost = quantity * fill_price + fee
            self._update_balance("USD", -cost)
            self._update_balance(coin, quantity)
            self.entry_prices[pair] = fill_price
        else:
            proceeds = quantity * fill_price - fee
            self._update_balance(coin, -quantity)
            self._update_balance("USD", proceeds)
            self.entry_prices.pop(pair, None)

        self.trades.append(
            {
                "timestamp": timestamp_ms,
                "pair": pair,
                "action": action,
                "quantity": quantity,
                "fill_price": fill_price,
                "fee": fee,
            }
        )

    def run(self) -> dict[str, Any]:
        """Run the backtest simulation."""
        self._fetch_data()
        self._init_portfolio()

        # Find common index range across all pairs
        min_len = min(len(df) for df in self.ohlcv_data.values())
        if min_len <= WARMUP_CANDLES + 1:
            logger.error("Not enough data for backtest (%d candles).", min_len)
            return {}

        # Trim all DataFrames to the same length (aligned from the end)
        for pair in self.pairs:
            df = self.ohlcv_data[pair]
            if len(df) > min_len:
                self.ohlcv_data[pair] = df.tail(min_len).reset_index(drop=True)

        total_steps = min_len - WARMUP_CANDLES - 1
        logger.info(
            "Starting backtest: %d pairs, %d candle steps after warmup.",
            len(self.pairs),
            total_steps,
        )

        for i in range(WARMUP_CANDLES, min_len - 1):
            candle_ts = int(self.ohlcv_data[self.pairs[0]].iloc[i]["timestamp"])

            # Current prices for all pairs
            current_prices: dict[str, float] = {}
            for pair in self.pairs:
                current_prices[pair] = float(self.ohlcv_data[pair].iloc[i]["close"])

            # Portfolio snapshot
            portfolio_value = self._get_portfolio_value(current_prices)
            self.peak_value = max(self.peak_value, portfolio_value)
            self.snapshots.append(
                {"timestamp_ms": candle_ts, "portfolio_value_usd": portfolio_value}
            )

            # Kill switch (engine-managed cooldown)
            if candle_ts < self.kill_switch_until:
                continue

            # Reset RiskManager's internal wall-clock state before checking
            self.risk_manager._kill_switch_triggered_at = 0.0
            if self.risk_manager.check_kill_switch(portfolio_value, self.peak_value):
                self.kill_switch_until = candle_ts + self.kill_pause_ms
                continue

            # Stop-loss check
            stop_signals = self.risk_manager.check_stop_losses(
                self.portfolio, self.entry_prices, current_prices
            )
            for sig in stop_signals:
                qty = self.risk_manager.size_sell_position(self.portfolio, sig)
                if qty <= 0:
                    continue
                limit_price = current_prices[sig.pair] * (1 + self.limit_offset)
                next_candle = self.ohlcv_data[sig.pair].iloc[i + 1]
                if float(next_candle["high"]) >= limit_price:
                    self._execute_fill("SELL", sig.pair, qty, limit_price, candle_ts)

            # Strategy signals
            for pair in self.pairs:
                market_data = self._build_market_data(pair, i, current_prices)
                signal = self.strategy.generate_signal(market_data)

                if signal.action == "HOLD":
                    continue

                price = current_prices[pair]
                can_trade, _ = self.risk_manager.check_can_trade(
                    self.portfolio, signal, portfolio_value, price
                )
                if not can_trade:
                    continue

                next_candle = self.ohlcv_data[pair].iloc[i + 1]

                if signal.action == "BUY":
                    qty = self.risk_manager.size_position(
                        portfolio_value, signal, price
                    )
                    limit_price = price * (1 - self.limit_offset)
                    # Check notional
                    if qty * limit_price < self.min_trade_usd:
                        continue
                    # Check we have enough USD
                    cost = qty * limit_price * (1 + FEE_RATE)
                    usd_free = float(self.portfolio["USD"]["Free"])
                    if cost > usd_free:
                        qty = usd_free / (limit_price * (1 + FEE_RATE))
                    if qty * limit_price < self.min_trade_usd:
                        continue
                    if float(next_candle["low"]) <= limit_price:
                        self._execute_fill("BUY", pair, qty, limit_price, candle_ts)

                elif signal.action == "SELL":
                    qty = self.risk_manager.size_sell_position(self.portfolio, signal)
                    if qty <= 0:
                        continue
                    limit_price = price * (1 + self.limit_offset)
                    if qty * limit_price < self.min_trade_usd:
                        continue
                    if float(next_candle["high"]) >= limit_price:
                        self._execute_fill("SELL", pair, qty, limit_price, candle_ts)

        # Final snapshot
        final_prices = {
            pair: float(self.ohlcv_data[pair].iloc[min_len - 1]["close"])
            for pair in self.pairs
        }
        final_value = self._get_portfolio_value(final_prices)
        final_ts = int(self.ohlcv_data[self.pairs[0]].iloc[min_len - 1]["timestamp"])
        self.snapshots.append(
            {"timestamp_ms": final_ts, "portfolio_value_usd": final_value}
        )

        metrics = self._compute_metrics()
        self._print_summary(metrics)
        return metrics

    def _compute_metrics(self) -> dict[str, Any]:
        """Compute performance metrics from snapshots."""
        df = pd.DataFrame(self.snapshots)
        if df.empty or len(df) < 2:
            return {}

        df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms")
        daily = (
            df.set_index("timestamp")["portfolio_value_usd"]
            .resample("1D")
            .last()
            .dropna()
        )
        returns = daily.pct_change().dropna()

        start_val = df["portfolio_value_usd"].iloc[0]
        end_val = df["portfolio_value_usd"].iloc[-1]
        total_return = (end_val - start_val) / start_val if start_val else 0

        # Sharpe
        sharpe = None
        if len(returns) > 1 and returns.std() > 0:
            excess = returns.mean() - (RISK_FREE_RATE / ANNUALIZATION_FACTOR)
            sharpe = float((excess / returns.std()) * math.sqrt(ANNUALIZATION_FACTOR))

        # Sortino
        sortino = None
        downside = returns[returns < 0]
        if len(downside) > 1 and downside.std() > 0:
            excess = returns.mean() - (RISK_FREE_RATE / ANNUALIZATION_FACTOR)
            sortino = float((excess / downside.std()) * math.sqrt(ANNUALIZATION_FACTOR))

        # Max drawdown
        values = df["portfolio_value_usd"].values
        peak = values[0]
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        # Calmar
        calmar = None
        if max_dd > 0 and len(returns) > 0:
            ann_return = returns.mean() * ANNUALIZATION_FACTOR
            calmar = float(ann_return / max_dd)

        # Win rate
        winning = [t for t in self.trades if t["action"] == "SELL"]
        wins = 0
        for trade in winning:
            pair = trade["pair"]
            buys = [
                t
                for t in self.trades
                if t["pair"] == pair
                and t["action"] == "BUY"
                and t["timestamp"] <= trade["timestamp"]
            ]
            if buys:
                entry = buys[-1]["fill_price"]
                if trade["fill_price"] > entry:
                    wins += 1
        win_rate = wins / len(winning) if winning else None

        return {
            "start_value": start_val,
            "end_value": end_val,
            "total_return": total_return,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "total_trades": len(self.trades),
            "win_rate": win_rate,
        }

    def _print_summary(self, metrics: dict[str, Any]) -> None:
        """Print a formatted metrics summary."""
        if not metrics:
            print("\nNo metrics to display (insufficient data).")
            return

        print("\n" + "=" * 60)
        print("  BACKTEST RESULTS")
        print("=" * 60)
        print(f"  Period:          {self.days} days")
        print(f"  Pairs:           {', '.join(self.pairs)}")
        print(f"  Start Value:     ${metrics['start_value']:>14,.2f}")
        print(f"  End Value:       ${metrics['end_value']:>14,.2f}")
        print(f"  Total Return:    {metrics['total_return']:>14.2%}")
        print(f"  Total Trades:    {metrics['total_trades']:>14d}")
        if metrics["win_rate"] is not None:
            print(f"  Win Rate:        {metrics['win_rate']:>14.1%}")
        else:
            print(f"  Win Rate:        {'N/A':>14s}")
        print("-" * 60)

        for name, key, is_pct in [
            ("Sharpe Ratio", "sharpe", False),
            ("Sortino Ratio", "sortino", False),
            ("Calmar Ratio", "calmar", False),
            ("Max Drawdown", "max_drawdown", True),
        ]:
            val = metrics.get(key)
            if val is None:
                print(f"  {name:<18s} {'N/A':>14s}")
            elif is_pct:
                print(f"  {name:<18s} {val:>14.2%}")
            else:
                print(f"  {name:<18s} {val:>14.4f}")

        print("=" * 60)

        if self.trades:
            print("\n  Recent trades:")
            for t in self.trades[-10:]:
                dt = datetime.fromtimestamp(t["timestamp"] / 1000, tz=timezone.utc)
                print(
                    f"    {dt:%Y-%m-%d %H:%M} {t['action']:4s} "
                    f"{t['pair']:8s} qty={t['quantity']:.6f} "
                    f"@ ${t['fill_price']:,.2f}  fee=${t['fee']:.2f}"
                )
        print()

    def export_csv(self, path: str) -> None:
        """Write trade log and equity curve to CSV files."""
        trades_path = Path(path)
        trades_path.parent.mkdir(parents=True, exist_ok=True)

        with trades_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "pair",
                    "action",
                    "quantity",
                    "fill_price",
                    "fee",
                ],
            )
            writer.writeheader()
            writer.writerows(self.trades)
        logger.info("Trades written to %s", trades_path)

        equity_path = trades_path.with_name(
            trades_path.stem + "_equity" + trades_path.suffix
        )
        with equity_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp_ms", "portfolio_value_usd"]
            )
            writer.writeheader()
            writer.writerows(self.snapshots)
        logger.info("Equity curve written to %s", equity_path)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Backtest trading strategies against historical data."
    )
    parser.add_argument(
        "--days", type=int, default=30, help="Number of days to backtest (default: 30)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=50_000.0,
        help="Starting capital in USD (default: 50000)",
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml", help="Path to config file"
    )
    parser.add_argument(
        "--csv", type=str, default=None, help="Path to export trades CSV"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    engine = BacktestEngine(
        config_path=args.config,
        days=args.days,
        starting_capital=args.capital,
    )
    engine.run()

    if args.csv:
        engine.export_csv(args.csv)


if __name__ == "__main__":
    main()
