from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest
from redis.exceptions import ConnectionError

from platform_core.services import web_search_coordinator as coordinator_module


@pytest.mark.parametrize("header", ["7", format_datetime(datetime(2030, 1, 1, tzinfo=UTC))])
def test_http_429_preserves_numeric_and_date_retry_after(header):
    request = httpx.Request("GET", "https://example.org/search")
    response = httpx.Response(429, headers={"Retry-After": header}, request=request)
    failure = coordinator_module.search_failure(
        httpx.HTTPStatusError("rate limited", request=request, response=response)
    )
    assert failure["status"] == "rate_limited"
    assert coordinator_module.rate_limit_delay(failure) >= 7


def test_successful_paper_title_cannot_trigger_rate_limit():
    assert coordinator_module.rate_limit_delay({"results": [{"title": "System 429 rate limits"}]}) == 0


def test_api_throttling_code_is_not_lost_when_message_is_generic():
    assert coordinator_module.rate_limit_delay({"error": "service busy", "code": "ThrottlingException"}) == 30


def test_redis_failure_does_not_send_uncoordinated_requests(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise ConnectionError("test outage")

    monkeypatch.setattr(coordinator_module, "sync_redis_client", unavailable)
    result = coordinator_module.coordinated_search("public", {}, lambda: pytest.fail("request bypassed scheduler"))
    assert result["status"] == "unavailable"
