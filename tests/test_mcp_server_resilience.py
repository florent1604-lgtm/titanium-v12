"""Résilience HTTP du serveur MCP Titanium."""
from __future__ import annotations

import httpx
import pytest

import mcp_server


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {"version": "v12"}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, *, get_effects=None, post_effects=None):
        self.get_effects = list(get_effects or [_Response()])
        self.post_effects = list(post_effects or [_Response()])
        self.get_calls = 0
        self.post_calls = 0
        self.is_closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        self.get_calls += 1
        effect = self.get_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    async def post(self, url, json, headers):
        self.post_calls += 1
        effect = self.post_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    async def aclose(self):
        self.is_closed = True


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    monkeypatch.setattr(mcp_server, "_http_client", None, raising=False)


@pytest.mark.asyncio
async def test_http_client_is_reused_between_gets(monkeypatch):
    created = []

    def factory(*args, **kwargs):
        client = _FakeClient(
            get_effects=[_Response(payload={"n": 1}), _Response(payload={"n": 2})]
        )
        created.append(client)
        return client

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", factory)

    first = await mcp_server._get("/health")
    second = await mcp_server._get("/health")

    assert first == {"n": 1}
    assert second == {"n": 2}
    assert len(created) == 1
    assert created[0].get_calls == 2


@pytest.mark.asyncio
async def test_get_retries_timeout_and_classifies_final_failure(monkeypatch):
    request = httpx.Request("GET", "http://localhost:8090/health")
    fake = _FakeClient(get_effects=[
        httpx.ReadTimeout("slow", request=request),
        httpx.ReadTimeout("slow", request=request),
    ])
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(mcp_server.asyncio, "sleep", lambda *_: _done())

    result = await mcp_server._get("/health")

    assert result["status"] == "timeout"
    assert fake.get_calls == 2


@pytest.mark.asyncio
async def test_post_is_not_retried_after_ambiguous_timeout(monkeypatch):
    request = httpx.Request("POST", "http://localhost:8090/api/optim/run")
    fake = _FakeClient(post_effects=[
        httpx.ReadTimeout("slow", request=request),
        _Response(payload={"duplicated": True}),
    ])
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", lambda *a, **k: fake)

    result = await mcp_server._post("/api/optim/run")

    assert result["status"] == "timeout"
    assert fake.post_calls == 1


@pytest.mark.asyncio
async def test_health_check_distinguishes_backend_failure(monkeypatch):
    async def timeout(_path):
        return {"status": "timeout", "reason": "slow"}

    monkeypatch.setattr(mcp_server, "_get", timeout)

    result = await mcp_server._health_check()

    assert result["healthy"] is False
    assert result["status"] == "timeout"


@pytest.mark.asyncio
async def test_close_client_releases_persistent_connection(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(mcp_server, "_http_client", fake, raising=False)

    await mcp_server._close_client()

    assert fake.is_closed is True
    assert mcp_server._http_client is None


async def _done():
    return None
