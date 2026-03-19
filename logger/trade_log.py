"""Structured JSON logging for trades, signals, and portfolio snapshots.

All records are written as newline-delimited JSON (one object per line).
Key events are also streamed to stdout in human-readable format.
Supports automatic log rotation when file exceeds configured size.
"""

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TradeLogger:
    """Structured trade and portfolio logger.

    Writes newline-delimited JSON to a log file, with automatic
    rotation when the file exceeds max_size_mb.
    """

    def __init__(
        self,
        log_file_path: str,
        max_size_mb: float = 50.0,
    ) -> None:
        """Initialize the trade logger.

        Args:
            log_file_path: Path to the JSONL log file.
            max_size_mb: Max log file size before rotation.
        """
        self.log_path = Path(log_file_path)
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_record(self, record: dict[str, Any]) -> None:
        """Write a single JSON record to the log file.

        Handles log rotation if the file exceeds max size.

        Args:
            record: Dictionary to serialize as JSON.
        """
        self._rotate_if_needed()
        record["logged_at"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(record, default=str)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _rotate_if_needed(self) -> None:
        """Rotate the log file if it exceeds the max size."""
        if not self.log_path.exists():
            return
        if self.log_path.stat().st_size < self.max_size_bytes:
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rotated = self.log_path.with_suffix(f".{timestamp}.jsonl")
        shutil.move(str(self.log_path), str(rotated))
        logger.info("Rotated log file to %s", rotated)

    def log_signal(
        self,
        signal: Any,
        market_data: dict[str, Any],
    ) -> None:
        """Record a trading signal and the data that drove it.

        Args:
            signal: Signal dataclass with pair, action, confidence, reason.
            market_data: Market data snapshot at signal generation time.
        """
        record = {
            "type": "signal",
            "pair": signal.pair,
            "action": signal.action,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "market_data_summary": _summarize_market_data(market_data),
            "timestamp_ms": int(time.time() * 1000),
        }
        self._write_record(record)
        _print_event(
            f"SIGNAL {signal.pair}: {signal.action} "
            f"(confidence={signal.confidence:.2f}) - {signal.reason}"
        )

    def log_order(
        self,
        signal: Any,
        api_response: Optional[dict[str, Any]],
    ) -> None:
        """Record a placed order and its API response.

        Args:
            signal: The signal that triggered this order.
            api_response: Raw API response from place_order, or None.
        """
        record = {
            "type": "order",
            "pair": signal.pair,
            "action": signal.action,
            "confidence": signal.confidence,
            "api_response": api_response,
            "timestamp_ms": int(time.time() * 1000),
        }
        self._write_record(record)
        status = "SUCCESS" if api_response else "FAILED"
        _print_event(f"ORDER {status} {signal.pair}: {signal.action}")

    def log_portfolio_snapshot(
        self,
        balance: dict[str, Any],
        prices: dict[str, Any],
        portfolio_value_usd: float,
    ) -> None:
        """Record a portfolio value snapshot.

        Args:
            balance: Current wallet balances.
            prices: Current market prices.
            portfolio_value_usd: Total portfolio value in USD.
        """
        record = {
            "type": "portfolio_snapshot",
            "balance": balance,
            "prices": prices,
            "portfolio_value_usd": portfolio_value_usd,
            "timestamp_ms": int(time.time() * 1000),
        }
        self._write_record(record)
        _print_event(f"PORTFOLIO: ${portfolio_value_usd:,.2f}")

    def log_error(self, context: str, error: Exception) -> None:
        """Record a structured error.

        Args:
            context: Description of what was happening when error occurred.
            error: The exception that was raised.
        """
        record = {
            "type": "error",
            "context": context,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp_ms": int(time.time() * 1000),
        }
        self._write_record(record)
        _print_event(f"ERROR [{context}]: {error}")

    def log_event(self, event_name: str, details: dict[str, Any]) -> None:
        """Record a generic event.

        Args:
            event_name: Name of the event (e.g. "kill_switch", "stale_cancel").
            details: Event-specific data.
        """
        record = {
            "type": "event",
            "event": event_name,
            **details,
            "timestamp_ms": int(time.time() * 1000),
        }
        self._write_record(record)
        _print_event(f"EVENT {event_name}: {json.dumps(details, default=str)}")


def _summarize_market_data(market_data: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of market data for logging.

    Args:
        market_data: Full market data dict.

    Returns:
        Summarized dict with key fields only.
    """
    summary: dict[str, Any] = {}
    for key in ("fear_greed", "prices"):
        if key in market_data:
            summary[key] = market_data[key]
    return summary


def _print_event(message: str) -> None:
    """Print a human-readable event to stdout.

    Args:
        message: Formatted event message.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {message}")
