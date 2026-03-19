"""Unit tests for the Roostoo API client.

Uses unittest.mock to simulate HTTP responses without hitting
the real API.
"""

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from api.client import RoostooClient


@pytest.fixture
def client() -> RoostooClient:
    """Create a test client with dummy credentials."""
    return RoostooClient(
        api_key="test_key",
        secret_key="test_secret",
        base_url="https://mock-api.roostoo.com",
    )


class TestSign:
    """Tests for the _sign method."""

    def test_sign_sorts_params_alphabetically(self, client: RoostooClient) -> None:
        """Parameters should be sorted by key before signing."""
        params = {"z_param": "3", "a_param": "1", "m_param": "2"}
        headers, encoded = client._sign(params)

        expected_string = "a_param=1&m_param=2&z_param=3"
        expected_sig = hmac.new(
            b"test_secret",
            expected_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert encoded == expected_string
        assert headers["RST-API-KEY"] == "test_key"
        assert headers["MSG-SIGNATURE"] == expected_sig

    def test_sign_single_param(self, client: RoostooClient) -> None:
        """Single parameter should produce valid signature."""
        params = {"timestamp": "1234567890000"}
        headers, encoded = client._sign(params)
        assert encoded == "timestamp=1234567890000"
        assert "MSG-SIGNATURE" in headers


class TestSyncTime:
    """Tests for server time sync."""

    @patch("api.client.RoostooClient._request_with_retry")
    def test_sync_time_updates_offset(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """sync_time should compute and store clock offset."""
        mock_request.return_value = {"ServerTime": 1700000000000}
        result = client.sync_time()
        assert result == 1700000000000
        assert client._server_time_offset_ms != 0

    @patch("api.client.RoostooClient._request_with_retry")
    def test_sync_time_returns_none_on_failure(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """sync_time should return None if request fails."""
        mock_request.return_value = None
        assert client.sync_time() is None


class TestGetBalance:
    """Tests for balance fetching."""

    @patch("api.client.RoostooClient._request_with_retry")
    def test_get_balance_returns_data(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """get_balance should return parsed balance dict."""
        mock_response = {
            "Success": True,
            "BTC": {"Free": "0.5", "Lock": "0.0"},
            "USD": {"Free": "50000", "Lock": "0"},
        }
        mock_request.return_value = mock_response
        result = client.get_balance()
        assert result is not None
        assert "BTC" in result

    @patch("api.client.RoostooClient._request_with_retry")
    def test_get_balance_returns_none_on_failure(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """get_balance should return None when request fails."""
        mock_request.return_value = None
        assert client.get_balance() is None


class TestPlaceOrder:
    """Tests for order placement."""

    @patch("api.client.RoostooClient._request_with_retry")
    def test_place_limit_order(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """place_order should send correct params for LIMIT order."""
        mock_request.return_value = {"Success": True, "OrderId": "12345"}
        result = client.place_order(
            pair="BTC/USD",
            side="BUY",
            order_type="LIMIT",
            quantity=0.01,
            price=50000.0,
        )
        assert result is not None
        assert result["OrderId"] == "12345"

        call_args = mock_request.call_args
        params = call_args[1].get("params") or call_args[0][2]
        assert params["pair"] == "BTC/USD"
        assert params["side"] == "BUY"
        assert params["type"] == "LIMIT"
        assert params["price"] == 50000.0

    @patch("api.client.RoostooClient._request_with_retry")
    def test_place_market_order_no_price(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """MARKET order should not include price param."""
        mock_request.return_value = {"Success": True}
        client.place_order(
            pair="ETH/USD",
            side="SELL",
            order_type="MARKET",
            quantity=1.0,
        )
        call_args = mock_request.call_args
        params = call_args[1].get("params") or call_args[0][2]
        assert "price" not in params


class TestGetTicker:
    """Tests for ticker endpoint."""

    @patch("api.client.RoostooClient._request_with_retry")
    def test_get_ticker_all_pairs(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """get_ticker with no pair should fetch all tickers."""
        mock_request.return_value = {
            "Success": True,
            "Tickers": {"BTC/USD": {"Last": "50000"}},
        }
        result = client.get_ticker()
        assert result is not None

    @patch("api.client.RoostooClient._request_with_retry")
    def test_get_ticker_specific_pair(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """get_ticker with pair should include pair in params."""
        mock_request.return_value = {"Success": True}
        client.get_ticker(pair="BTC/USD")
        call_args = mock_request.call_args
        params = call_args[1].get("params") or call_args[0][2]
        assert params.get("pair") == "BTC/USD"


class TestCancelOrder:
    """Tests for order cancellation."""

    @patch("api.client.RoostooClient._request_with_retry")
    def test_cancel_specific_order(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """cancel_order with order_id should cancel that specific order."""
        mock_request.return_value = {"Success": True}
        result = client.cancel_order(order_id="abc123")
        assert result is not None

    @patch("api.client.RoostooClient._request_with_retry")
    def test_cancel_all_orders(
        self, mock_request: MagicMock, client: RoostooClient
    ) -> None:
        """cancel_order with no args should cancel all pending orders."""
        mock_request.return_value = {"Success": True}
        result = client.cancel_order()
        assert result is not None
        call_args = mock_request.call_args
        params = call_args[1].get("params") or (
            call_args[0][2] if len(call_args[0]) > 2 else {}
        )
        assert "order_id" not in params
        assert "pair" not in params
