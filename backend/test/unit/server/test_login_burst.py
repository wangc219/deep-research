"""同一办公出口的登录并发与节流边界。"""

import asyncio
from collections import defaultdict, deque

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from server import main


@pytest.mark.asyncio
async def test_sixteen_logins_can_be_in_flight_from_one_ip(monkeypatch):
    monkeypatch.setattr(main, "_login_attempts", defaultdict(deque))
    monkeypatch.setattr(main, "_attempt_lock", asyncio.Lock())
    app = FastAPI()
    app.add_middleware(main.LoginRateLimitMiddleware)
    ready = asyncio.Event()
    arrived = 0

    @app.post("/api/auth/token")
    async def login():
        nonlocal arrived
        arrived += 1
        if arrived == 16:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=3)
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(*(client.post("/api/auth/token") for _ in range(16)))
    assert [response.status_code for response in responses] == [200] * 16


@pytest.mark.asyncio
async def test_failed_burst_still_throttles_and_returns_retry_after(monkeypatch):
    monkeypatch.setattr(main, "_login_attempts", defaultdict(deque))
    monkeypatch.setattr(main, "_attempt_lock", asyncio.Lock())
    app = FastAPI()
    app.add_middleware(main.LoginRateLimitMiddleware)

    @app.post("/api/auth/token")
    async def login():
        return JSONResponse({"detail": "invalid credentials"}, status_code=401)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(main.RATE_LIMIT_MAX_ATTEMPTS):
            assert (await client.post("/api/auth/token")).status_code == 401
        response = await client.post("/api/auth/token")
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
