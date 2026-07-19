from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tools.claude_gitnexus_identity import (
    build_public_attestation,
    read_attestation,
    write_attestation,
)


SAFE_AUTH = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "subscriptionType": "pro",
    "email": "must-not-persist@example.invalid",
    "orgId": "must-not-persist",
    "orgName": "must-not-persist",
}


def test_subscription_auth_is_safe_and_filters_identity_data():
    when = datetime(2026, 7, 19, 17, 0, tzinfo=timezone.utc)
    result = build_public_attestation(
        SAFE_AUTH, {}, mcp_verified=True, verified_at=when
    )
    assert result == {
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
    serialized = json.dumps(result)
    assert "must-not-persist" not in serialized
    assert "email" not in serialized
    assert "org" not in serialized.lower()


def test_api_key_forces_ollama_fallback():
    result = build_public_attestation(
        SAFE_AUTH,
        {"ANTHROPIC_API_KEY": "present-but-never-copied"},
        mcp_verified=True,
        verified_at=datetime.now(timezone.utc),
    )
    assert result["billing_guard"] == "API_BILLING_RISK"
    assert result["selected_provider"] == "ollama"
    assert "present-but-never-copied" not in json.dumps(result)


def test_console_or_third_party_auth_forces_ollama():
    for auth in (
        {**SAFE_AUTH, "authMethod": "console"},
        {**SAFE_AUTH, "apiProvider": "bedrock"},
    ):
        result = build_public_attestation(
            auth,
            {},
            mcp_verified=True,
            verified_at=datetime.now(timezone.utc),
        )
        assert result["billing_guard"] == "API_BILLING_RISK"
        assert result["selected_provider"] == "ollama"


def test_unverified_or_disconnected_auth_forces_ollama():
    result = build_public_attestation(
        {},
        {},
        mcp_verified=False,
        verified_at=datetime.now(timezone.utc),
    )
    assert result["configured"] is False
    assert result["billing_guard"] == "UNVERIFIED"
    assert result["selected_provider"] == "ollama"


def test_read_attestation_fails_closed_when_stale(tmp_path):
    path = tmp_path / "claude-status.json"
    when = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    payload = build_public_attestation(
        SAFE_AUTH, {}, mcp_verified=True, verified_at=when
    )
    write_attestation(payload, path)

    result = read_attestation(path, now=when + timedelta(seconds=86_401))
    assert result["verification_fresh"] is False
    assert result["billing_guard"] == "UNVERIFIED"
    assert result["selected_provider"] == "ollama"


def test_write_attestation_is_atomic_and_public(tmp_path):
    path = tmp_path / "claude-status.json"
    payload = build_public_attestation(
        SAFE_AUTH,
        {},
        mcp_verified=True,
        verified_at=datetime.now(timezone.utc),
    )
    write_attestation(payload, path)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert not path.with_suffix(".tmp").exists()
