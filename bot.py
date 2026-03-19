"""Main bot loop — orchestrates all modules.

Reads config, instantiates all components, and runs the autonomous
trading loop. Supports DRY_RUN mode and graceful shutdown.
"""

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from api.client import RoostooClient
from data.feeds import DataFeed
from logger.trade_log import TradeLogger
from risk.manager import RiskManager
from strategy.base import BaseStrategy, Signal
from strategy import STRATEGY_REGISTRY
from strategy.multi_signal import MultiSignalStrategy

load_dotenv()

logger = logging.getLogger("bot")


class TradingBot:
    """Autonomous crypto trading bot.

    Orchestrates data fetching, signal generation, risk management,
    order execution, and logging in a continuous loop.
    """

    def __init__(self, config_path: str = "config.yaml") -> None:
        """Initialize the bot from config file and environment.

        Args:
            config_path: Path to the YAML config file.
        """
        self.config = self._load_config(config_path)
        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self._shutdown = False

        api_key, secret_key = self._load_credentials()
        base_url = self.config["exchange"]["base_url"]

        self.client = RoostooClient(api_key, secret_key, base_url)
        self.data_feed = DataFeed(self.config["data"])
        self.strategy = self._load_strategy()
        self.risk_manager = RiskManager(self.config["trading"])
        self.trade_logger = TradeLogger(
            self.config["logging"]["log_file"],
            max_size_mb=self.config["logging"].get("max_log_size_mb", 50),
        )

        self.pairs: list[str] = self.config["trading"]["pairs"]
        self.poll_interval: int = self.config["exchange"]["poll_interval_seconds"]
        self.stale_minutes: int = self.config["exchange"]["stale_order_minutes"]
        self.limit_offset: float = self.config["trading"]["limit_offset_pct"]

        self.positions_file = Path(
            self.config.get("state", {}).get("positions_file", "state/positions.json")
        )
        self.state_file = Path("state/bot_state.json")
        self.entry_prices: dict[str, float] = self._load_positions()
        self._load_bot_state()
        self.exchange_info: Optional[dict] = None
        self._exchange_info_fetched_at: float = 0.0
        self._cycle_count: int = 0

        self._setup_signal_handlers()

    def _load_strategy(self) -> BaseStrategy:
        """Load the strategy selected by training, or fall back to default.

        Checks state/selected_strategy.json first. If not found or invalid,
        falls back to MultiSignalStrategy.

        Returns:
            Strategy instance.
        """
        selection_file = Path("state/selected_strategy.json")
        strategy_config = self.config.get("strategy", {})

        if selection_file.exists():
            try:
                with selection_file.open("r", encoding="utf-8") as f:
                    selection = json.load(f)
                name = selection.get("selected_strategy", "multi_signal")
                cls = STRATEGY_REGISTRY.get(name)
                if cls is not None:
                    logger.info(
                        "Loaded trained strategy: %s (score=%.4f)",
                        name,
                        selection.get("composite_score", 0),
                    )
                    return cls(strategy_config)
                logger.warning("Unknown strategy '%s' in selection file.", name)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load strategy selection: %s", exc)

        logger.info("Using default strategy: multi_signal")
        return MultiSignalStrategy(strategy_config)

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load and parse YAML config file.

        Args:
            config_path: Path to config.yaml.

        Returns:
            Parsed config dict.
        """
        path = Path(config_path)
        if not path.exists():
            logger.error("Config file not found: %s", path)
            sys.exit(1)
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_credentials(self) -> tuple[str, str]:
        """Load API credentials from environment variables.

        Returns:
            Tuple of (api_key, secret_key).
        """
        api_key = os.getenv("API_KEY")
        secret_key = os.getenv("SECRET_KEY")
        if not api_key or not secret_key:
            logger.error(
                "Missing API_KEY or SECRET_KEY environment variables. "
                "Copy .env.example to .env and fill in your credentials."
            )
            sys.exit(1)
        return api_key, secret_key

    def _load_positions(self) -> dict[str, float]:
        """Load entry prices from state file for stop-loss tracking.

        Returns:
            Dict mapping pair to entry price.
        """
        if self.positions_file.exists():
            try:
                with self.positions_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(
                    "Loaded %d position entries from %s",
                    len(data),
                    self.positions_file,
                )
                return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load positions state: %s", exc)
        return {}

    def _load_bot_state(self) -> None:
        """Load persistent bot state (peak_value) from disk."""
        self.peak_value: float = 0.0
        if self.state_file.exists():
            try:
                with self.state_file.open("r", encoding="utf-8") as f:
                    state = json.load(f)
                self.peak_value = state.get("peak_value", 0.0)
                logger.info("Restored peak_value=$%.2f from state file.", self.peak_value)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load bot state: %s", exc)

    def _save_bot_state(self) -> None:
        """Persist bot state to disk so it survives restarts."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "peak_value": self.peak_value,
            "saved_at": time.time(),
        }
        with self.state_file.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def _save_positions(self) -> None:
        """Persist entry prices to state file."""
        self.positions_file.parent.mkdir(parents=True, exist_ok=True)
        with self.positions_file.open("w", encoding="utf-8") as f:
            json.dump(self.entry_prices, f, indent=2)

    def _setup_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM for graceful shutdown."""
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Handle shutdown signal.

        Args:
            signum: Signal number.
            frame: Current stack frame.
        """
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, initiating graceful shutdown...", sig_name)
        self._shutdown = True

    def run(self) -> None:
        """Run the main trading loop.

        Runs continuously until SIGINT/SIGTERM. On consecutive errors,
        applies exponential backoff (up to 30 min) to avoid hammering
        the API when it's down.
        """
        logger.info(
            "Starting trading bot (DRY_RUN=%s, pairs=%s, interval=%ds)",
            self.dry_run,
            self.pairs,
            self.poll_interval,
        )
        self._initialize()

        consecutive_errors = 0
        max_error_backoff = 1800  # 30 minutes max

        while not self._shutdown:
            try:
                self._run_cycle()
                consecutive_errors = 0  # Reset on success
            except Exception as exc:
                consecutive_errors += 1
                self.trade_logger.log_error("trading_cycle", exc)
                logger.exception("Error in trading cycle (%d consecutive)", consecutive_errors)

                if consecutive_errors >= 3:
                    error_backoff = min(
                        self.poll_interval * (2 ** (consecutive_errors - 3)),
                        max_error_backoff,
                    )
                    logger.warning(
                        "Multiple consecutive errors. Extra backoff: %ds", error_backoff
                    )
                    self._interruptible_sleep(int(error_backoff))

            if not self._shutdown:
                logger.info(
                    "Sleeping %d seconds until next cycle...",
                    self.poll_interval,
                )
                self._interruptible_sleep(self.poll_interval)

        self._graceful_shutdown()

    def _initialize(self) -> None:
        """Run one-time initialization tasks."""
        server_time = self.client.sync_time()
        if server_time:
            logger.info("Server time synced: %d", server_time)

        self.exchange_info = self.client.get_exchange_info()
        if self.exchange_info:
            self._exchange_info_fetched_at = time.time()
            logger.info("Exchange info loaded.")

        logger.info(
            "Bot initialized. Strategy: %s. Pairs: %s. Cycle: %ds.",
            type(self.strategy).__name__,
            self.pairs,
            self.poll_interval,
        )

    def _run_cycle(self) -> None:
        """Execute one full trading cycle."""
        self._cycle_count += 1
        logger.info("=== Cycle %d starting ===", self._cycle_count)

        self.client.sync_time()

        # Re-fetch exchange info every 6 hours (24 cycles at 15min interval)
        if (
            self.exchange_info is None
            or time.time() - self._exchange_info_fetched_at > 6 * 3600
        ):
            info = self.client.get_exchange_info()
            if info:
                self.exchange_info = info
                self._exchange_info_fetched_at = time.time()
                logger.info("Refreshed exchange info.")

        ohlcv_data = self._fetch_ohlcv_for_pairs()
        fear_greed = self.data_feed.get_fear_greed()
        roostoo_prices = self.data_feed.get_roostoo_prices(self.client)

        if roostoo_prices is None:
            logger.warning("Failed to fetch Roostoo prices, skipping cycle.")
            return

        raw_balance = self.client.get_balance()
        if raw_balance is None:
            logger.warning("Failed to fetch balance, skipping cycle.")
            return
        balance = self._normalize_balance(raw_balance)

        portfolio_value = self._compute_portfolio_value(balance, roostoo_prices)
        self.peak_value = max(self.peak_value, portfolio_value)
        self.trade_logger.log_portfolio_snapshot(
            balance, roostoo_prices, portfolio_value
        )

        if self.risk_manager.check_kill_switch(portfolio_value, self.peak_value):
            self.trade_logger.log_event(
                "kill_switch",
                {
                    "portfolio_value": portfolio_value,
                    "peak_value": self.peak_value,
                },
            )
            return

        current_prices = self._extract_last_prices(roostoo_prices)
        stop_signals = self.risk_manager.check_stop_losses(
            balance, self.entry_prices, current_prices
        )
        for stop_signal in stop_signals:
            self._execute_signal(stop_signal, balance, portfolio_value, current_prices)

        for pair in self.pairs:
            if self._shutdown:
                break
            market_data = self._build_market_data(
                pair, ohlcv_data, roostoo_prices, fear_greed
            )
            sig = self.strategy.generate_signal(market_data)
            self.trade_logger.log_signal(sig, market_data)

            if sig.action == "HOLD":
                continue

            price = current_prices.get(pair, 0.0)
            can_trade, reason = self.risk_manager.check_can_trade(
                balance, sig, portfolio_value, price
            )
            if not can_trade:
                logger.info("Risk check blocked %s %s: %s", sig.action, pair, reason)
                continue

            self._execute_signal(sig, balance, portfolio_value, current_prices)

        self._cancel_stale_orders()
        self._save_bot_state()
        logger.info(
            "=== Cycle %d complete | portfolio=$%.2f | peak=$%.2f ===",
            self._cycle_count,
            portfolio_value,
            self.peak_value,
        )

    def _fetch_ohlcv_for_pairs(self) -> dict[str, Any]:
        """Fetch OHLCV data for all configured pairs.

        Returns:
            Dict mapping pair to OHLCV DataFrame.
        """
        ohlcv_data: dict[str, Any] = {}
        for pair in self.pairs:
            binance_symbol = self.data_feed.get_binance_symbol(pair)
            df = self.data_feed.get_ohlcv(binance_symbol)
            if df is not None:
                ohlcv_data[pair] = df
        return ohlcv_data

    @staticmethod
    def _normalize_balance(raw_balance: dict[str, Any]) -> dict[str, Any]:
        """Extract the coin balance dict from the API response.

        The Roostoo API nests balances under SpotWallet. This method
        unwraps that nesting so callers get {coin: {Free, Lock}}.

        Args:
            raw_balance: Raw API response from get_balance().

        Returns:
            Flat dict mapping coin to {Free, Lock}.
        """
        if "SpotWallet" in raw_balance:
            return raw_balance["SpotWallet"]
        return raw_balance

    def _compute_portfolio_value(
        self,
        balance: dict[str, Any],
        prices: dict[str, dict[str, float]],
    ) -> float:
        """Compute total portfolio value in USD.

        Args:
            balance: Wallet balances {coin: {Free, Lock}}.
            prices: Ticker data {pair: {last, ...}}.

        Returns:
            Total portfolio value in USD.
        """
        total = 0.0
        for coin, amounts in balance.items():
            if not isinstance(amounts, dict):
                continue
            holding = float(amounts.get("Free", 0)) + float(amounts.get("Lock", 0))
            if holding <= 0:
                continue

            if coin in ("USD", "USDT", "USDC"):
                total += holding
                continue

            pair_key = f"{coin}/USD"
            price_data = prices.get(pair_key, {})
            last_price = (
                price_data.get("last", 0.0) if isinstance(price_data, dict) else 0.0
            )
            total += holding * last_price

        return total

    def _extract_last_prices(
        self, prices: dict[str, dict[str, float]]
    ) -> dict[str, float]:
        """Extract last price for each pair.

        Args:
            prices: Ticker data from Roostoo.

        Returns:
            Dict mapping pair to last price.
        """
        return {
            pair: data.get("last", 0.0)
            for pair, data in prices.items()
            if isinstance(data, dict)
        }

    def _build_market_data(
        self,
        pair: str,
        ohlcv_data: dict[str, Any],
        prices: dict[str, dict[str, float]],
        fear_greed: Optional[int],
    ) -> dict[str, Any]:
        """Build market data dict for strategy consumption.

        Args:
            pair: Trading pair.
            ohlcv_data: OHLCV DataFrames by pair.
            prices: Roostoo ticker prices.
            fear_greed: Fear & Greed index value.

        Returns:
            Market data dict ready for generate_signal().
        """
        price_data = prices.get(pair, {})
        change_raw = (
            price_data.get("change", 0.0) if isinstance(price_data, dict) else 0.0
        )
        # Roostoo returns change as decimal (0.02 = 2%), strategy expects %
        change_pct = change_raw * 100

        return {
            "pair": pair,
            "ohlcv": ohlcv_data.get(pair),
            "change_24h": change_pct,
            "fear_greed": fear_greed,
            "prices": prices,
        }

    def _execute_signal(
        self,
        sig: Signal,
        balance: dict[str, Any],
        portfolio_value: float,
        current_prices: dict[str, float],
    ) -> None:
        """Execute a trading signal by placing an order.

        Args:
            sig: Trading signal to execute.
            balance: Current wallet balances.
            portfolio_value: Total portfolio value in USD.
            current_prices: Current prices by pair.
        """
        price = current_prices.get(sig.pair, 0.0)
        if price <= 0:
            logger.warning("No price for %s, skipping.", sig.pair)
            return

        if sig.action == "BUY":
            quantity = self.risk_manager.size_position(portfolio_value, sig, price)
            limit_price = price * (1 - self.limit_offset)
        elif sig.action == "SELL":
            quantity = self.risk_manager.size_sell_position(balance, sig)
            limit_price = price * (1 + self.limit_offset)
        else:
            return

        quantity, limit_price = self._apply_precision(sig.pair, quantity, limit_price)

        if quantity <= 0:
            logger.info("Quantity zero after precision for %s, skipping.", sig.pair)
            return

        min_trade = self.config["trading"]["min_trade_usd"]
        if quantity * limit_price < min_trade:
            logger.info(
                "Order notional $%.2f below min $%.2f for %s.",
                quantity * limit_price,
                min_trade,
                sig.pair,
            )
            return

        if self.dry_run:
            logger.info(
                "DRY RUN: Would place %s LIMIT %s qty=%.8f price=%.2f",
                sig.action,
                sig.pair,
                quantity,
                limit_price,
            )
            self.trade_logger.log_order(sig, {"dry_run": True})
            return

        response = self.client.place_order(
            pair=sig.pair,
            side=sig.action,
            order_type="LIMIT",
            quantity=quantity,
            price=limit_price,
        )
        self.trade_logger.log_order(sig, response)

        if response and sig.action == "BUY":
            self.entry_prices[sig.pair] = price
            self._save_positions()
        elif response and sig.action == "SELL":
            self.entry_prices.pop(sig.pair, None)
            self._save_positions()

    def _apply_precision(
        self, pair: str, quantity: float, price: float
    ) -> tuple[float, float]:
        """Round quantity and price to exchange precision rules.

        Args:
            pair: Trading pair.
            quantity: Raw quantity.
            price: Raw price.

        Returns:
            Tuple of (rounded_quantity, rounded_price).
        """
        if self.exchange_info is None:
            return round(quantity, 8), round(price, 2)

        pairs_info = self.exchange_info.get(
            "TradePairs", self.exchange_info.get("Pairs", self.exchange_info)
        )
        pair_info = pairs_info.get(pair, {}) if isinstance(pairs_info, dict) else {}

        amount_prec = int(pair_info.get("AmountPrecision", 8))
        price_prec = int(pair_info.get("PricePrecision", 2))

        return round(quantity, amount_prec), round(price, price_prec)

    def _cancel_stale_orders(self) -> None:
        """Cancel pending limit orders older than stale_order_minutes."""
        for pair in self.pairs:
            result = self.client.query_order(pair=pair, pending_only=True)
            if result is None:
                continue

            orders = result.get("Orders", [])
            if not isinstance(orders, list):
                continue

            now_ms = int(time.time() * 1000)
            stale_ms = self.stale_minutes * 60 * 1000

            for order in orders:
                if not isinstance(order, dict):
                    continue
                order_time = order.get("Time", 0)
                order_id = order.get("OrderId", "")
                if now_ms - order_time > stale_ms:
                    logger.info(
                        "Cancelling stale order %s for %s",
                        order_id,
                        pair,
                    )
                    self.client.cancel_order(order_id=order_id)
                    self.trade_logger.log_event(
                        "stale_cancel",
                        {
                            "order_id": order_id,
                            "pair": pair,
                            "age_minutes": (now_ms - order_time) / 60000,
                        },
                    )

    def _graceful_shutdown(self) -> None:
        """Cancel all pending orders and log final snapshot."""
        logger.info("Graceful shutdown: cancelling all pending orders...")
        self.client.cancel_order()

        raw_balance = self.client.get_balance()
        prices = self.data_feed.get_roostoo_prices(self.client)
        if raw_balance and prices:
            balance = self._normalize_balance(raw_balance)
            value = self._compute_portfolio_value(balance, prices)
            self.trade_logger.log_portfolio_snapshot(balance, prices, value)

        self._save_positions()
        self.trade_logger.log_event("shutdown", {"reason": "signal"})
        logger.info("Shutdown complete.")

    def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep in small increments to allow quick shutdown response.

        Args:
            seconds: Total seconds to sleep.
        """
        elapsed = 0
        while elapsed < seconds and not self._shutdown:
            time.sleep(min(1, seconds - elapsed))
            elapsed += 1


def _setup_logging(level: str) -> None:
    """Configure logging for the application.

    Args:
        level: Log level string (e.g. "INFO", "DEBUG").
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    """Bot entrypoint."""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    _setup_logging(log_level)

    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
