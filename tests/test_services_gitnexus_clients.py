from __future__ import annotations

import json

import pytest

from api import services_routes as routes


@pytest.mark.asyncio
async def test_services_status_exposes_public_claude_attestation(monkeypatch):
    async def gitnexus_ok():
        return True, 4747

    async def repositories():
        return [{"name": "titanium-v12", "stats": {"nodes": 24_354}}]

    async def ollama_off():
        return False

    attestation = {
        "identity": "claude",
        "configured": True,
        "verified_at": "2026-07-19T17:00:00+00:00",
        "verification_fresh": True,
        "transport": "http",
        "endpoint_scope": "loopback",
        "access": "advisory-read-only",
        "billing_guard": "SUBSCRIPTION_OK",
        "selected_provider": "claude",
        "fallback": "ollama:qwen2.5:7b",
    }
    monkeypatch.setattr(routes, "_gitnexus_responding", gitnexus_ok)
    monkeypatch.setattr(routes, "_gitnexus_repositories", repositories)
    monkeypatch.setattr(routes, "_ollama_responding", ollama_off)
    monkeypatch.setattr(routes, "read_claude_attestation", lambda: attestation)

    response = await routes.services_status()
    payload = json.loads(response.body)
    assert payload["gitnexus"]["clients"]["claude"] == attestation
    assert "connected" not in payload["gitnexus"]["clients"]["claude"]
    assert payload["gitnexus"]["symbols"] == 24_354


@pytest.mark.asyncio
async def test_gitnexus_repositories_accepts_rc_value(monkeypatch):
    class Response:
        status = 200

        async def json(self):
            return {"value": [{"name": "titanium-v12"}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(routes.aiohttp, "ClientSession", Session)
    assert await routes._gitnexus_repositories() == [{"name": "titanium-v12"}]


@pytest.mark.asyncio
async def test_gitnexus_start_uses_managed_runtime(monkeypatch):
    state = {"healthy": False}

    async def responding():
        return state["healthy"], 4747 if state["healthy"] else 0

    class Process:
        pid = 4242

    def start():
        state["healthy"] = True
        return Process()

    monkeypatch.setattr(routes, "_gitnexus_responding", responding)
    monkeypatch.setattr(routes, "start_gitnexus_server", start)
    response = await routes.gitnexus_start()
    assert json.loads(response.body)["status"] == "started"


@pytest.mark.asyncio
async def test_gitnexus_stop_uses_authenticated_graceful_runtime(monkeypatch):
    monkeypatch.setattr(routes, "stop_gitnexus_server", lambda: True)
    response = await routes.gitnexus_stop()
    assert json.loads(response.body)["status"] == "stopped"
