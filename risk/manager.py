"""Risk management module.

Enforces position limits, stop-losses, and a portfolio drawdown kill switch.
All thresholds are configurable via config.yaml.
"""

import logging
import time
from typing import Any

from strategy.base import Signal

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages position sizing, stop-losses, and kill switch logic.

    Reads all thresholds from config and enforces risk rules
    before any order is placed.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize risk manager with trading config.

        Args:
            config: Trading config section from config.yaml.
        """
        self.max_position_pct: float = config.get("max_position_pct", 0.20)
        self.stop_loss_pct: float = config.get("stop_loss_pct", 0.05)
        self.kill_switch_drawdown: float = config.get("kill_switch_drawdown", 0.15)
        self.kill_switch_pause_minutes: int = config.get(
            "kill_switch_pause_minutes", 240
        )
        self.min_trade_usd: float = config.get("min_trade_usd", 10.0)
        self._kill_switch_triggered_at: float = 0.0

    def check_can_trade(
        self,
        portfolio: dict[str, Any],
        signal: Signal,
        portfolio_value_usd: float,
        current_price: float,
    ) -> tuple[bool, str]:
        """Check whether a trade is allowed by risk rules.

        Args:
            portfolio: Current balance dict {coin: {Free, Lock}}.
            signal: The proposed trading signal.
            portfolio_value_usd: Total portfolio value in USD.
            current_price: Current price of the asset.

        Returns:
            Tuple of (allowed: bool, reason: str).
        """
        if signal.action == "HOLD":
            return False, "Signal is HOLD"

        base_coin = signal.pair.split("/")[0]

        if signal.action == "BUY":
            max_position_usd = portfolio_value_usd * self.max_position_pct
            current_holding = _get_coin_balance(portfolio, base_coin)
            current_position_usd = current_holding * current_price

            if current_position_usd >= max_position_usd:
                return False, (
                    f"Position in {base_coin} (${current_position_usd:,.2f}) "
                    f"already at max ({self.max_position_pct:.0%} = "
                    f"${max_position_usd:,.2f})"
                )

        if signal.action == "SELL":
            current_holding = _get_coin_balance(portfolio, base_coin)
            notional = current_holding * current_price
            if notional < self.min_trade_usd:
                return False, (
                    f"Holding of {base_coin} (${notional:,.2f}) "
                    f"below min trade size ${self.min_trade_usd}"
                )

        return True, "Trade approved"

    def size_position(
        self,
        portfolio_usd: float,
        signal: Signal,
        current_price: float,
    ) -> float:
        """Calculate position size for a trade.

        For BUY: allocates up to max_position_pct of portfolio, scaled
        by signal confidence. For SELL: sells the full position.

        Args:
            portfolio_usd: Total portfolio value in USD.
            signal: The trading signal.
            current_price: Current price of the asset.

        Returns:
            Quantity to trade (in base coin units).
        """
        if signal.action == "BUY":
            max_usd = portfolio_usd * self.max_position_pct
            target_usd = max_usd * signal.confidence
            target_usd = max(target_usd, self.min_trade_usd)
            quantity = target_usd / current_price
            return quantity

        return 0.0

    def size_sell_position(
        self,
        portfolio: dict[str, Any],
        signal: Signal,
    ) -> float:
        """Calculate quantity to sell for a SELL signal.

        Sells the entire free balance of the coin.

        Args:
            portfolio: Current balance dict.
            signal: The SELL signal.

        Returns:
            Quantity to sell.
        """
        base_coin = signal.pair.split("/")[0]
        return _get_coin_balance(portfolio, base_coin)

    def check_stop_losses(
        self,
        portfolio: dict[str, Any],
        entry_prices: dict[str, float],
        current_prices: dict[str, float],
    ) -> list[Signal]:
        """Check all positions for stop-loss triggers.

        Args:
            portfolio: Current balance dict.
            entry_prices: Dict mapping coin to entry price.
            current_prices: Dict mapping pair to current price.

        Returns:
            List of SELL signals for positions that hit stop-loss.
        """
        signals: list[Signal] = []
        for pair, entry_price in entry_prices.items():
            base_coin = pair.split("/")[0]
            holding = _get_coin_balance(portfolio, base_coin)
            if holding <= 0:
                continue

            current_price = current_prices.get(pair, 0.0)
            if current_price <= 0:
                continue

            loss_pct = (entry_price - current_price) / entry_price
            if loss_pct >= self.stop_loss_pct:
                signals.append(
                    Signal(
                        pair=pair,
                        action="SELL",
                        confidence=1.0,
                        reason=(
                            f"Stop-loss triggered: {loss_pct:.1%} drop "
                            f"from entry ${entry_price:,.2f} "
                            f"to ${current_price:,.2f}"
                        ),
                    )
                )
                logger.warning(
                    "Stop-loss for %s: %.1f%% drop from $%.2f to $%.2f",
                    pair,
                    loss_pct * 100,
                    entry_price,
                    current_price,
                )
        return signals

    def check_kill_switch(
        self,
        portfolio_value_usd: float,
        peak_value: float,
    ) -> bool:
        """Check if the portfolio drawdown kill switch should activate.

        Args:
            portfolio_value_usd: Current total portfolio value.
            peak_value: Historical peak portfolio value.

        Returns:
            True if trading should be paused.
        """
        if self._is_in_cooldown():
            remaining = self._cooldown_remaining_minutes()
            logger.info(
                "Kill switch cooldown active, %.0f minutes remaining.",
                remaining,
            )
            return True

        if peak_value <= 0:
            return False

        drawdown = (peak_value - portfolio_value_usd) / peak_value
        if drawdown >= self.kill_switch_drawdown:
            self._kill_switch_triggered_at = time.time()
            logger.warning(
                "KILL SWITCH: Portfolio drawdown %.1f%% "
                "(peak=$%.2f, current=$%.2f). "
                "Pausing trading for %d minutes.",
                drawdown * 100,
                peak_value,
                portfolio_value_usd,
                self.kill_switch_pause_minutes,
            )
            return True
        return False

    def _is_in_cooldown(self) -> bool:
        """Check if kill switch cooldown is still active."""
        if self._kill_switch_triggered_at == 0:
            return False
        elapsed = time.time() - self._kill_switch_triggered_at
        cooldown_seconds = self.kill_switch_pause_minutes * 60
        return elapsed < cooldown_seconds

    def _cooldown_remaining_minutes(self) -> float:
        """Get remaining kill switch cooldown time in minutes."""
        elapsed = time.time() - self._kill_switch_triggered_at
        cooldown_seconds = self.kill_switch_pause_minutes * 60
        remaining = max(0, cooldown_seconds - elapsed)
        return remaining / 60


def _get_coin_balance(portfolio: dict[str, Any], coin: str) -> float:
    """Extract free balance for a coin from portfolio dict.

    Args:
        portfolio: Balance dict from API {coin: {Free, Lock}}.
        coin: Coin name (e.g. "BTC").

    Returns:
        Free balance as float, or 0.0 if not found.
    """
    coin_data = portfolio.get(coin, {})
    if isinstance(coin_data, dict):
        return float(coin_data.get("Free", 0))
    return 0.0
