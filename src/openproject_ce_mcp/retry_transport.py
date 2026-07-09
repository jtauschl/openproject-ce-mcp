"""HTTP transport wrapper with exponential backoff retry logic for transient failures."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from email.utils import parsedate_to_datetime

import httpx

LOGGER = logging.getLogger(__name__)


class RetryTransport(httpx.AsyncBaseTransport):
    """HTTP transport wrapper that retries transient failures with exponential backoff.

    Automatically retries requests that fail with transient errors (429 rate limit,
    502/503/504 server errors, timeout/connection errors) using exponential backoff
    with jitter. Honors Retry-After headers when present.

    Only idempotent methods (GET, HEAD, OPTIONS, PUT) are retried. POST and DELETE
    are never retried automatically.
    """

    def __init__(
        self,
        wrapped_transport: httpx.AsyncBaseTransport,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ):
        """Initialize retry transport.

        Args:
            wrapped_transport: The underlying transport to wrap
            max_retries: Maximum number of retry attempts (0 disables retries)
            base_delay: Base delay in seconds for exponential backoff
            max_delay: Maximum delay in seconds between retries
        """
        self._transport = wrapped_transport
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Handle a request with automatic retry on transient failures.

        Args:
            request: The HTTP request to execute

        Returns:
            The HTTP response

        Raises:
            httpx.HTTPStatusError: For non-retryable errors or after max retries
            httpx.HTTPError: For transport errors after max retries
        """
        # Only retry idempotent methods
        if request.method not in {"GET", "HEAD", "OPTIONS", "PUT"}:
            return await self._transport.handle_async_request(request)

        last_exception: Exception | None = None
        attempt = 0

        while attempt <= self._max_retries:
            try:
                response = await self._transport.handle_async_request(request)

                # Check if response status is retryable
                if not self._is_retryable_status(response.status_code):
                    return response

                # Check if we should retry
                if attempt >= self._max_retries:
                    return response

                # Calculate delay and retry
                delay = self._calculate_delay(attempt, response)
                LOGGER.info(
                    "Retrying request (attempt %d/%d) after %.1fs: %s %s (status %d)",
                    attempt + 1,
                    self._max_retries,
                    delay,
                    request.method,
                    request.url,
                    response.status_code,
                )
                await asyncio.sleep(delay)
                attempt += 1

            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout) as exc:
                # Transport errors are retryable
                last_exception = exc

                if attempt >= self._max_retries:
                    LOGGER.warning(
                        "Max retries (%d) exceeded for %s %s: %s",
                        self._max_retries,
                        request.method,
                        request.url,
                        exc,
                    )
                    raise

                delay = self._calculate_delay(attempt, None)
                LOGGER.info(
                    "Retrying request after transport error (attempt %d/%d) after %.1fs: %s %s",
                    attempt + 1,
                    self._max_retries,
                    delay,
                    request.method,
                    request.url,
                )
                await asyncio.sleep(delay)
                attempt += 1

        # Should not reach here, but if we do, raise the last exception
        if last_exception:
            raise last_exception

        # Fallback: make one final attempt
        return await self._transport.handle_async_request(request)

    def _is_retryable_status(self, status_code: int) -> bool:
        """Check if a status code should trigger a retry.

        Args:
            status_code: HTTP status code

        Returns:
            True if the status is retryable
        """
        return status_code in {429, 502, 503, 504}

    def _calculate_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Calculate delay before next retry attempt.

        Args:
            attempt: Current attempt number (0-indexed)
            response: HTTP response (if available)

        Returns:
            Delay in seconds
        """
        # Check for Retry-After header
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                delay = self._parse_retry_after(retry_after)
                if delay is not None:
                    return min(delay, self._max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self._base_delay * (2**attempt)
        delay = min(delay, self._max_delay)

        # Add jitter: ±20%
        jitter = delay * random.uniform(0.8, 1.2)
        return jitter

    def _parse_retry_after(self, value: str) -> float | None:
        """Parse Retry-After header value.

        Args:
            value: Retry-After header value (seconds or HTTP-date)

        Returns:
            Delay in seconds, or None if parsing fails
        """
        # Try parsing as integer (seconds)
        try:
            return float(value)
        except ValueError:
            pass

        # Try parsing as HTTP-date
        try:
            retry_date = parsedate_to_datetime(value)
            now = time.time()
            delay = retry_date.timestamp() - now
            return max(0, delay)
        except (ValueError, TypeError, OverflowError):
            return None

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._transport.aclose()
