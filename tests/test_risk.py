"""Unit tests for the RiskManager.

Tests position sizing, stop-loss triggers, kill switch logic,
and trade approval checks.
"""

import time

import pytest

from risk.manager import RiskManager
from strategy.base import Signal


@pytest.fixture
def risk_manager() -> RiskManager:
    """Create a risk manager with default test config."""
    return RiskManager(
        {
            "max_position_pct": 0.20,
            "stop_loss_pct": 0.05,
            "kill_switch_drawdown": 0.15,
            "kill_switch_pause_minutes": 240,
            "min_trade_usd": 10.0,
        }
    )


@pytest.fixture
def portfolio() -> dict:
    """Sample portfolio balance."""
    return {
        "USD": {"Free": "800000", "Lock": "0"},
        "BTC": {"Free": "2.0", "Lock": "0"},
        "ETH": {"Free": "10.0", "Lock": "0"},
    }


class TestCheckCanTrade:
    """Tests for trade approval logic."""

    def test_hold_signal_blocked(
        self, risk_manager: RiskManager, portfolio: dict
    ) -> None:
        """HOLD signals should always be blocked."""
        signal = Signal("BTC/USD", "HOLD", 0.5, "test")
        allowed, reason = risk_manager.check_can_trade(
            portfolio, signal, 1_000_000, 50_000
        )
        assert not allowed
        assert "HOLD" in reason

    def test_buy_within_limits(
        self, risk_manager: RiskManager, portfolio: dict
    ) -> None:
        """BUY should be allowed when position is under max."""
        signal = Signal("BTC/USD", "BUY", 0.8, "test")
        # BTC position: 2.0 * 50000 = 100k, max = 20% of 1M = 200k
        allowed, reason = risk_manager.check_can_trade(
            portfolio, signal, 1_000_000, 50_000
        )
        assert allowed
        assert "approved" in reason.lower()

    def test_buy_blocked_at_max_position(self, risk_manager: RiskManager) -> None:
        """BUY should be blocked when position at max allocation."""
        portfolio = {
            "USD": {"Free": "600000", "Lock": "0"},
            "BTC": {"Free": "4.0", "Lock": "0"},
        }
        signal = Signal("BTC/USD", "BUY", 0.8, "test")
        # BTC position: 4.0 * 50000 = 200k, max = 20% of 1M = 200k
        allowed, reason = risk_manager.check_can_trade(
            portfolio, signal, 1_000_000, 50_000
        )
        assert not allowed
        assert "max" in reason.lower()

    def test_sell_blocked_below_min_trade(self, risk_manager: RiskManager) -> None:
        """SELL should be blocked when holding is below min trade size."""
        portfolio = {"BTC": {"Free": "0.0001", "Lock": "0"}}
        signal = Signal("BTC/USD", "SELL", 0.8, "test")
        # Holding: 0.0001 * 50000 = $5, below $10 min
        allowed, reason = risk_manager.check_can_trade(
            portfolio, signal, 1_000_000, 50_000
        )
        assert not allowed
        assert "min" in reason.lower()

    def test_sell_allowed_with_sufficient_holding(
        self, risk_manager: RiskManager, portfolio: dict
    ) -> None:
        """SELL should be allowed with holdings above min trade."""
        signal = Signal("BTC/USD", "SELL", 0.8, "test")
        allowed, reason = risk_manager.check_can_trade(
            portfolio, signal, 1_000_000, 50_000
        )
        assert allowed


class TestSizePosition:
    """Tests for position sizing."""

    def test_buy_size_scales_with_confidence(self, risk_manager: RiskManager) -> None:
        """Higher confidence should produce larger position size."""
        low_conf = Signal("BTC/USD", "BUY", 0.3, "test")
        high_conf = Signal("BTC/USD", "BUY", 0.9, "test")

        qty_low = risk_manager.size_position(1_000_000, low_conf, 50_000)
        qty_high = risk_manager.size_position(1_000_000, high_conf, 50_000)

        assert qty_high > qty_low

    def test_buy_size_respects_max_position(self, risk_manager: RiskManager) -> None:
        """Position size should not exceed max_position_pct of portfolio."""
        signal = Signal("BTC/USD", "BUY", 1.0, "test")
        qty = risk_manager.size_position(1_000_000, signal, 50_000)
        usd_value = qty * 50_000
        max_usd = 1_000_000 * 0.20
        assert usd_value <= max_usd + 1  # +1 for float rounding

    def test_sell_size_is_full_holding(
        self, risk_manager: RiskManager, portfolio: dict
    ) -> None:
        """SELL should liquidate the full free balance."""
        signal = Signal("BTC/USD", "SELL", 1.0, "test")
        qty = risk_manager.size_sell_position(portfolio, signal)
        assert qty == 2.0


class TestStopLoss:
    """Tests for stop-loss checking."""

    def test_stop_loss_triggers_on_drop(
        self, risk_manager: RiskManager, portfolio: dict
    ) -> None:
        """Stop-loss should fire when price drops below threshold."""
        entry_prices = {"BTC/USD": 50_000.0}
        current_prices = {"BTC/USD": 47_000.0}  # 6% drop > 5% threshold

        signals = risk_manager.check_stop_losses(
            portfolio, entry_prices, current_prices
        )
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert signals[0].pair == "BTC/USD"
        assert "Stop-loss" in signals[0].reason

    def test_no_stop_loss_within_threshold(
        self, risk_manager: RiskManager, portfolio: dict
    ) -> None:
        """No stop-loss when price is within acceptable range."""
        entry_prices = {"BTC/USD": 50_000.0}
        current_prices = {"BTC/USD": 48_000.0}  # 4% drop < 5% threshold

        signals = risk_manager.check_stop_losses(
            portfolio, entry_prices, current_prices
        )
        assert len(signals) == 0

    def test_stop_loss_ignores_zero_holdings(self, risk_manager: RiskManager) -> None:
        """Stop-loss should not trigger for coins with no holdings."""
        portfolio = {"BTC": {"Free": "0", "Lock": "0"}}
        entry_prices = {"BTC/USD": 50_000.0}
        current_prices = {"BTC/USD": 40_000.0}

        signals = risk_manager.check_stop_losses(
            portfolio, entry_prices, current_prices
        )
        assert len(signals) == 0


class TestKillSwitch:
    """Tests for the drawdown kill switch."""

    def test_kill_switch_triggers_on_drawdown(self, risk_manager: RiskManager) -> None:
        """Kill switch should activate at 15% drawdown from peak."""
        peak = 1_000_000
        current = 840_000  # 16% drawdown
        assert risk_manager.check_kill_switch(current, peak)

    def test_kill_switch_inactive_within_threshold(
        self, risk_manager: RiskManager
    ) -> None:
        """Kill switch should not trigger within acceptable drawdown."""
        peak = 1_000_000
        current = 900_000  # 10% drawdown
        assert not risk_manager.check_kill_switch(current, peak)

    def test_kill_switch_cooldown(self, risk_manager: RiskManager) -> None:
        """Kill switch should enforce cooldown period."""
        # Trigger the kill switch
        risk_manager.check_kill_switch(800_000, 1_000_000)

        # Should still be in cooldown even with recovered portfolio
        assert risk_manager.check_kill_switch(1_000_000, 1_000_000)

    def test_kill_switch_cooldown_expires(self, risk_manager: RiskManager) -> None:
        """Kill switch should allow trading after cooldown expires."""
        risk_manager._kill_switch_triggered_at = time.time() - 300 * 60
        assert not risk_manager.check_kill_switch(1_000_000, 1_000_000)
