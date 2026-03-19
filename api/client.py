"""Roostoo Mock Exchange API client.

Wraps all 7 REST API endpoints with HMAC SHA256 authentication,
exponential backoff retry on network errors, and structured logging.
"""

import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class RoostooAPIError(Exception):
    """Raised when the Roostoo API returns a logical error (Success=false)."""

    def __init__(self, message: str, response: Optional[dict] = None) -> None:
        super().__init__(message)
        self.response = response


class RoostooClient:
    """HTTP client for the Roostoo mock exchange REST API.

    Handles HMAC SHA256 signing, request retry with exponential backoff,
    and parsing of all 7 API endpoints.
    """

    MAX_RETRIES: int = 3
    BACKOFF_BASE: float = 1.0
    CLOCK_DRIFT_MS: int = 60_000

    def __init__(self, api_key: str, secret_key: str, base_url: str) -> None:
        """Initialize the Roostoo API client.

        Args:
            api_key: Roostoo API key.
            secret_key: Roostoo secret key for HMAC signing.
            base_url: Base URL for the API (e.g. https://mock-api.roostoo.com).
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._server_time_offset_ms: int = 0

    def _timestamp_ms(self) -> int:
        """Return current timestamp in milliseconds, adjusted for server drift."""
        return int(time.time() * 1000) + self._server_time_offset_ms

    def _sign(self, params: dict[str, Any]) -> tuple[dict[str, str], str]:
        """Compute HMAC SHA256 signature for request parameters.

        Args:
            params: Request parameters to sign.

        Returns:
            Tuple of (headers dict, URL-encoded params string).
        """
        sorted_keys = sorted(params.keys())
        param_string = "&".join(f"{k}={params[k]}" for k in sorted_keys)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            param_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "RST-API-KEY": self.api_key,
            "MSG-SIGNATURE": signature,
        }
        return headers, param_string

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        signed: bool = False,
    ) -> Optional[dict]:
        """Execute an HTTP request with exponential backoff on network errors.

        Args:
            method: HTTP method ("GET" or "POST").
            endpoint: API endpoint path (e.g. "/v3/balance").
            params: Request parameters.
            signed: Whether to include HMAC signature headers.

        Returns:
            Parsed JSON response dict, or None on unrecoverable error.
        """
        params = params or {}
        url = f"{self.base_url}{endpoint}"

        for attempt in range(self.MAX_RETRIES):
            try:
                return self._execute_request(method, url, params, signed)
            except requests.RequestException as exc:
                wait_time = self.BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Network error on %s %s (attempt %d/%d): %s. " "Retrying in %.1fs.",
                    method,
                    endpoint,
                    attempt + 1,
                    self.MAX_RETRIES,
                    exc,
                    wait_time,
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(wait_time)
            except RoostooAPIError as exc:
                err_msg = str(exc)
                if "no order matched" in err_msg.lower():
                    logger.debug("No orders found on %s %s", method, endpoint)
                else:
                    logger.error("API error on %s %s: %s", method, endpoint, exc)
                return None

        logger.error(
            "All %d retries exhausted for %s %s.",
            self.MAX_RETRIES,
            method,
            endpoint,
        )
        return None

    def _execute_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any],
        signed: bool,
    ) -> dict:
        """Execute a single HTTP request.

        Args:
            method: HTTP method.
            url: Full request URL.
            params: Request parameters.
            signed: Whether to sign the request.

        Returns:
            Parsed JSON response dict.

        Raises:
            requests.RequestException: On network-level errors.
            RoostooAPIError: On API-level logical errors.
        """
        headers: dict[str, str] = {}
        if signed:
            params["timestamp"] = self._timestamp_ms()
            headers, encoded_params = self._sign(params)

        if method == "GET":
            if signed:
                query = encoded_params
            else:
                query = urllib.parse.urlencode(params) if params else ""
            full_url = f"{url}?{query}" if query else url
            logger.debug("GET %s", full_url)
            resp = self.session.get(full_url, headers=headers, timeout=10)
        else:
            if signed:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body = encoded_params
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body = urllib.parse.urlencode(params)
            logger.debug("POST %s body=%s", url, body)
            resp = self.session.post(url, data=body, headers=headers, timeout=10)

        resp.raise_for_status()
        data = resp.json()
        logger.debug("Response: %s", data)

        if isinstance(data, dict) and data.get("Success") is False:
            raise RoostooAPIError(
                f"API returned error: {data.get('ErrMsg', 'unknown')}",
                response=data,
            )
        return data

    def sync_time(self) -> Optional[int]:
        """Sync local clock with the server and compute offset.

        Returns:
            Server time in milliseconds, or None on failure.
        """
        data = self._request_with_retry("GET", "/v3/serverTime")
        if data is None:
            return None
        server_time = data.get("ServerTime")
        if server_time is not None:
            local_time = int(time.time() * 1000)
            self._server_time_offset_ms = server_time - local_time
            drift = abs(self._server_time_offset_ms)
            if drift > self.CLOCK_DRIFT_MS:
                logger.warning(
                    "Clock drift of %dms exceeds %dms threshold.",
                    drift,
                    self.CLOCK_DRIFT_MS,
                )
        return server_time

    def get_exchange_info(self) -> Optional[dict]:
        """Fetch available trading pairs and precision rules.

        Returns:
            Exchange info dict with pair metadata, or None on failure.
        """
        return self._request_with_retry("GET", "/v3/exchangeInfo")

    def get_ticker(self, pair: Optional[str] = None) -> Optional[dict]:
        """Fetch current ticker data for one or all pairs.

        Args:
            pair: Trading pair (e.g. "BTC/USD"). Omit for all pairs.

        Returns:
            Ticker data dict, or None on failure.
        """
        params: dict[str, Any] = {}
        if pair is not None:
            params["pair"] = pair
        return self._request_with_retry("GET", "/v3/ticker", params=params, signed=True)

    def get_balance(self) -> Optional[dict]:
        """Fetch current wallet balances.

        Returns:
            Dict mapping coin name to {Free, Lock} amounts, or None.
        """
        return self._request_with_retry("GET", "/v3/balance", signed=True)

    def get_pending_count(self) -> Optional[dict]:
        """Fetch count of pending orders.

        Returns:
            Dict with pending order count, or None on failure.
        """
        return self._request_with_retry("GET", "/v3/pending_count", signed=True)

    def place_order(
        self,
        pair: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> Optional[dict]:
        """Place a buy or sell order.

        Args:
            pair: Trading pair (e.g. "BTC/USD").
            side: "BUY" or "SELL".
            order_type: "LIMIT" or "MARKET".
            quantity: Order quantity.
            price: Limit price (required for LIMIT orders).

        Returns:
            Order response dict, or None on failure.
        """
        params: dict[str, Any] = {
            "pair": pair,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }
        if price is not None:
            params["price"] = price
        return self._request_with_retry(
            "POST", "/v3/place_order", params=params, signed=True
        )

    def query_order(
        self,
        order_id: Optional[str] = None,
        pair: Optional[str] = None,
        pending_only: Optional[bool] = None,
    ) -> Optional[dict]:
        """Query order status.

        Args:
            order_id: Specific order ID to query.
            pair: Query all orders for a pair.
            pending_only: If True, return only pending orders.

        Returns:
            Order query response dict, or None on failure.
        """
        params: dict[str, Any] = {}
        if order_id is not None:
            params["order_id"] = order_id
        if pair is not None:
            params["pair"] = pair
        if pending_only is not None:
            params["pending_only"] = str(pending_only).lower()
        return self._request_with_retry(
            "POST", "/v3/query_order", params=params, signed=True
        )

    def cancel_order(
        self,
        order_id: Optional[str] = None,
        pair: Optional[str] = None,
    ) -> Optional[dict]:
        """Cancel one or all pending orders.

        Args:
            order_id: Specific order to cancel.
            pair: Cancel all orders for this pair.
            If neither provided, cancels all pending orders.

        Returns:
            Cancellation response dict, or None on failure.
        """
        params: dict[str, Any] = {}
        if order_id is not None:
            params["order_id"] = order_id
        if pair is not None:
            params["pair"] = pair
        return self._request_with_retry(
            "POST", "/v3/cancel_order", params=params, signed=True
        )
