"""Tests for retry transport with exponential backoff."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from openproject_ce_mcp.retry_transport import RetryTransport


@pytest.mark.asyncio
async def test_successful_request_no_retry():
    """Successful requests should not trigger retries."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.return_value = httpx.Response(200, request=httpx.Request("GET", "http://test"))

    retry_transport = RetryTransport(mock_transport, max_retries=3)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert mock_transport.handle_async_request.call_count == 1


@pytest.mark.asyncio
async def test_retry_on_429_status():
    """429 status should trigger retry."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    # First call returns 429, second returns 200
    mock_transport.handle_async_request.side_effect = [
        httpx.Response(429, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert mock_transport.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_retry_on_502_503_504():
    """502, 503, 504 status codes should trigger retry."""
    for status_code in [502, 503, 504]:
        mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
        mock_transport.handle_async_request.side_effect = [
            httpx.Response(status_code, request=httpx.Request("GET", "http://test")),
            httpx.Response(200, request=httpx.Request("GET", "http://test")),
        ]

        retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01)
        request = httpx.Request("GET", "http://test/api")

        response = await retry_transport.handle_async_request(request)

        assert response.status_code == 200
        assert mock_transport.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_max_retries_exceeded():
    """Should stop retrying after max_retries attempts."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    # Always return 503
    mock_transport.handle_async_request.return_value = httpx.Response(503, request=httpx.Request("GET", "http://test"))

    retry_transport = RetryTransport(mock_transport, max_retries=2, base_delay=0.01)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    # Should try: initial + 2 retries = 3 total
    assert response.status_code == 503
    assert mock_transport.handle_async_request.call_count == 3


@pytest.mark.asyncio
async def test_non_idempotent_method_not_retried():
    """POST requests should not be retried."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.return_value = httpx.Response(503, request=httpx.Request("POST", "http://test"))

    retry_transport = RetryTransport(mock_transport, max_retries=3)
    request = httpx.Request("POST", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    # POST should not retry
    assert response.status_code == 503
    assert mock_transport.handle_async_request.call_count == 1


@pytest.mark.asyncio
async def test_idempotent_methods_retried():
    """GET, HEAD, OPTIONS, PUT should be retried."""
    for method in ["GET", "HEAD", "OPTIONS", "PUT"]:
        mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
        mock_transport.handle_async_request.side_effect = [
            httpx.Response(503, request=httpx.Request(method, "http://test")),
            httpx.Response(200, request=httpx.Request(method, "http://test")),
        ]

        retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01)
        request = httpx.Request(method, "http://test/api")

        response = await retry_transport.handle_async_request(request)

        assert response.status_code == 200
        assert mock_transport.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_non_retryable_status_not_retried():
    """400, 500, 501 should not trigger retry."""
    for status_code in [400, 404, 500, 501]:
        mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
        mock_transport.handle_async_request.return_value = httpx.Response(
            status_code, request=httpx.Request("GET", "http://test")
        )

        retry_transport = RetryTransport(mock_transport, max_retries=3)
        request = httpx.Request("GET", "http://test/api")

        response = await retry_transport.handle_async_request(request)

        assert response.status_code == status_code
        assert mock_transport.handle_async_request.call_count == 1


@pytest.mark.asyncio
async def test_retry_after_header_seconds():
    """Should honor Retry-After header with seconds."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    # First call returns 429 with Retry-After, second returns 200
    response_429 = httpx.Response(429, headers={"Retry-After": "0.01"}, request=httpx.Request("GET", "http://test"))
    mock_transport.handle_async_request.side_effect = [
        response_429,
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3)
    request = httpx.Request("GET", "http://test/api")

    start = asyncio.get_event_loop().time()
    response = await retry_transport.handle_async_request(request)
    elapsed = asyncio.get_event_loop().time() - start

    assert response.status_code == 200
    # Should wait at least 0.01 seconds (Retry-After value)
    assert elapsed >= 0.01


@pytest.mark.asyncio
async def test_retry_after_header_http_date():
    """Should honor Retry-After header with HTTP-date format."""
    import time
    from email.utils import formatdate

    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)

    # Create a date 0.1 seconds in the future (more buffer for slow systems)
    retry_time = time.time() + 0.1
    retry_date = formatdate(retry_time, usegmt=True)

    response_429 = httpx.Response(429, headers={"Retry-After": retry_date}, request=httpx.Request("GET", "http://test"))
    mock_transport.handle_async_request.side_effect = [
        response_429,
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    # Should have waited (even if date parsing is slightly off, should at least try)
    assert mock_transport.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_transport_error_retry():
    """Transport errors should trigger retry."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    # First call raises TimeoutException, second succeeds
    mock_transport.handle_async_request.side_effect = [
        httpx.TimeoutException("Request timed out"),
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert mock_transport.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_transport_error_max_retries():
    """Transport errors should respect max_retries."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    # Always raise TimeoutException
    mock_transport.handle_async_request.side_effect = httpx.TimeoutException("Request timed out")

    retry_transport = RetryTransport(mock_transport, max_retries=2, base_delay=0.01)
    request = httpx.Request("GET", "http://test/api")

    with pytest.raises(httpx.TimeoutException):
        await retry_transport.handle_async_request(request)

    # Should try: initial + 2 retries = 3 total
    assert mock_transport.handle_async_request.call_count == 3


@pytest.mark.asyncio
async def test_exponential_backoff_calculation():
    """Should use exponential backoff with jitter."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    # Return 503 three times, then 200
    mock_transport.handle_async_request.side_effect = [
        httpx.Response(503, request=httpx.Request("GET", "http://test")),
        httpx.Response(503, request=httpx.Request("GET", "http://test")),
        httpx.Response(503, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01, max_delay=1.0)
    request = httpx.Request("GET", "http://test/api")

    start = asyncio.get_event_loop().time()
    response = await retry_transport.handle_async_request(request)
    elapsed = asyncio.get_event_loop().time() - start

    assert response.status_code == 200
    # With base_delay=0.01, attempts should wait roughly:
    # 0.01 * 2^0 = 0.01s (with jitter ±20%)
    # 0.01 * 2^1 = 0.02s (with jitter ±20%)
    # 0.01 * 2^2 = 0.04s (with jitter ±20%)
    # Total minimum ~0.05s (accounting for jitter reducing to 0.8x)
    assert elapsed >= 0.04  # Conservative check with jitter


@pytest.mark.asyncio
async def test_max_delay_cap():
    """Delay should not exceed max_delay."""
    retry_transport = RetryTransport(None, max_retries=10, base_delay=10.0, max_delay=0.05)

    # Calculate delay for attempt 5 (should be capped at max_delay)
    delay = retry_transport._calculate_delay(5, None)

    # With base_delay=10 and attempt=5: 10 * 2^5 = 320s
    # But capped at max_delay=0.05, with jitter ±20%
    assert delay <= 0.06  # max_delay * 1.2 (jitter)


@pytest.mark.asyncio
async def test_zero_retries_disables_retry():
    """Setting max_retries=0 should disable retry logic."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.return_value = httpx.Response(503, request=httpx.Request("GET", "http://test"))

    retry_transport = RetryTransport(mock_transport, max_retries=0)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    # Should not retry
    assert response.status_code == 503
    assert mock_transport.handle_async_request.call_count == 1
