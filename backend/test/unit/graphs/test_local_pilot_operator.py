"""本地 Pilot 运维身份的网络边界测试。"""

import pytest

from platform_core.knowledge.training.local_pilot_operator import local_operator_headers, require_loopback_api_base


@pytest.mark.parametrize(
    "api_base",
    [
        "http://127.0.0.1:5050/api",
        "http://localhost:5050/api",
        "http://[::1]:5050/api",
    ],
)
def test_local_operator_accepts_loopback_api(api_base: str):
    require_loopback_api_base(api_base)


@pytest.mark.parametrize(
    "api_base",
    [
        "https://example.com/api",
        "http://10.0.0.8:5050/api",
        "not-a-url",
    ],
)
def test_local_operator_rejects_remote_or_invalid_api(api_base: str):
    with pytest.raises(ValueError, match="loopback"):
        require_loopback_api_base(api_base)


@pytest.mark.asyncio
@pytest.mark.parametrize("expires_minutes", [0, 181, True])
async def test_local_operator_rejects_unbounded_token_lifetime(expires_minutes: int):
    with pytest.raises(ValueError, match="1 到 180"):
        await local_operator_headers(
            "http://127.0.0.1:5050/api",
            expires_minutes=expires_minutes,
        )
