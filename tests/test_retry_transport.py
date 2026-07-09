"""Tests for retry transport with exponential backoff."""

from __future__ import annotations

from email.utils import formatdate
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
async def test_patch_not_retried():
    """PATCH requests should not be retried (OpenProject has toggle endpoints)."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.return_value = httpx.Response(
        503, request=httpx.Request("PATCH", "http://test")
    )

    retry_transport = RetryTransport(mock_transport, max_retries=3)
    request = httpx.Request("PATCH", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    # PATCH should not retry (even on 503)
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
async def test_retry_after_header_seconds(monkeypatch):
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
    sleep_delays = []

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    monkeypatch.setattr("openproject_ce_mcp.retry_transport.asyncio.sleep", fake_sleep)

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert sleep_delays == [0.01]


@pytest.mark.asyncio
async def test_retry_after_header_http_date(monkeypatch):
    """Should honor Retry-After header with HTTP-date format."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)

    fixed_now = 1_700_000_000.0
    retry_time = fixed_now + 2.0
    retry_date = formatdate(retry_time, usegmt=True)

    response_429 = httpx.Response(429, headers={"Retry-After": retry_date}, request=httpx.Request("GET", "http://test"))
    mock_transport.handle_async_request.side_effect = [
        response_429,
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3)
    request = httpx.Request("GET", "http://test/api")
    sleep_delays = []

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    monkeypatch.setattr("openproject_ce_mcp.retry_transport.time.time", lambda: fixed_now)
    monkeypatch.setattr("openproject_ce_mcp.retry_transport.asyncio.sleep", fake_sleep)

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert sleep_delays == [2.0]


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
async def test_exponential_backoff_calculation(monkeypatch):
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
    sleep_delays = []
    jitter_bounds = []

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    def fake_uniform(lower, upper):
        jitter_bounds.append((lower, upper))
        return 1.0

    monkeypatch.setattr("openproject_ce_mcp.retry_transport.random.uniform", fake_uniform)
    monkeypatch.setattr("openproject_ce_mcp.retry_transport.asyncio.sleep", fake_sleep)

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    # With base_delay=0.01, attempts should wait roughly:
    # 0.01 * 2^0 = 0.01s (with jitter ±20%)
    # 0.01 * 2^1 = 0.02s (with jitter ±20%)
    # 0.01 * 2^2 = 0.04s (with jitter ±20%)
    assert sleep_delays == [0.01, 0.02, 0.04]
    assert jitter_bounds == [(0.8, 1.2), (0.8, 1.2), (0.8, 1.2)]


@pytest.mark.asyncio
async def test_max_delay_cap(monkeypatch):
    """Delay should not exceed max_delay."""
    retry_transport = RetryTransport(None, max_retries=10, base_delay=10.0, max_delay=0.05)
    monkeypatch.setattr("openproject_ce_mcp.retry_transport.random.uniform", lambda _lower, _upper: 1.2)

    # Calculate delay for attempt 5 (should be capped at max_delay)
    delay = retry_transport._calculate_delay(5, None)

    # With base_delay=10 and attempt=5: 10 * 2^5 = 320s
    # Jitter is applied, then the result is capped at max_delay=0.05.
    assert delay == 0.05


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


@pytest.mark.asyncio
async def test_jitter_respects_max_delay():
    """Jitter should not violate max_delay contract."""
    retry_transport = RetryTransport(None, max_retries=10, base_delay=100.0, max_delay=60.0)

    # Test many iterations to catch jitter violations
    for _ in range(100):
        delay = retry_transport._calculate_delay(50, None)
        assert delay <= 60.0, f"Jitter produced {delay}s > max_delay 60.0s"


@pytest.mark.asyncio
async def test_network_io_errors_retried():
    """ReadError and WriteError should trigger retry."""
    for error_class in [httpx.ReadError, httpx.WriteError]:
        mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
        mock_transport.handle_async_request.side_effect = [
            error_class("Network I/O error"),
            httpx.Response(200, request=httpx.Request("GET", "http://test")),
        ]

        retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01)
        request = httpx.Request("GET", "http://test/api")

        response = await retry_transport.handle_async_request(request)

        assert response.status_code == 200
        assert mock_transport.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_retryable_response_closed_before_retry():
    """Retryable responses should be closed before waiting for retry."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)

    # Track if response was closed
    close_called = False

    async def mock_aclose():
        nonlocal close_called
        close_called = True

    # First call returns 503 with trackable aclose, second returns 200
    response_503 = httpx.Response(503, request=httpx.Request("GET", "http://test"))
    response_503.aclose = mock_aclose

    mock_transport.handle_async_request.side_effect = [
        response_503,
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    retry_transport = RetryTransport(mock_transport, max_retries=3, base_delay=0.01)
    request = httpx.Request("GET", "http://test/api")

    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert mock_transport.handle_async_request.call_count == 2
    assert close_called, "Response should have been closed before retry"
