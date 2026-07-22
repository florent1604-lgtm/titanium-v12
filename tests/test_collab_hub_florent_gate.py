from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from collab_hub.app import create_app
from collab_hub.session import SessionAuthority
from collab_hub.store import CollabStore


EXPECTED_SID = "S-1-5-21-florent"


def _payload(key: str, *, principal: str = "florent") -> dict:
    return {
        "principal": principal,
        "target": "codex",
        "kind": "decision",
        "content": "Validation manuelle de Florent",
        "idempotency_key": key,
    }


def _client(tmp_path: Path) -> tuple[TestClient, CollabStore]:
    store = CollabStore(tmp_path / "collab.sqlite3")
    app = create_app(store, expected_windows_sid=EXPECTED_SID)
    return TestClient(app), store


def test_http_cannot_impersonate_florent(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    response = client.post("/v1/messages", json=_payload("florent-impersonation"))

    assert response.status_code == 401
    assert response.json() == {"reason_code": "FLORENT_SESSION_REQUIRED"}
    assert store.health()["head_offset"] == 0
    store.close()


def test_http_florent_session_must_match_expected_windows_sid(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    sessions = client.app.state.collab_sessions
    other = sessions.issue("S-1-5-21-other-user")
    expected = sessions.issue(EXPECTED_SID)

    denied = client.post(
        "/v1/messages",
        json=_payload("florent-wrong-sid"),
        headers={"X-Collab-Session": other.token},
    )
    accepted = client.post(
        "/v1/messages",
        json=_payload("florent-expected-sid"),
        headers={"X-Collab-Session": expected.token},
    )

    assert denied.status_code == 401
    assert accepted.status_code == 201
    assert store.health()["head_offset"] == 1
    store.close()


def test_http_auth_precedes_secret_rejection_and_persistence(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    secret = "password=not-a-real-credential-42"
    payload = _payload("florent-secret")
    payload["content"] = secret

    unauthenticated = client.post("/v1/messages", json=payload)
    session = client.app.state.collab_sessions.issue(EXPECTED_SID)
    authenticated = client.post(
        "/v1/messages",
        json=payload,
        headers={"X-Collab-Session": session.token},
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 400
    assert authenticated.json() == {"reason_code": "SECRET_REJECTED"}
    assert secret not in unauthenticated.text
    assert secret not in authenticated.text
    assert store.health()["head_offset"] == 0
    store.close()


def test_http_rejects_expired_florent_session_without_persistence(
    tmp_path: Path,
) -> None:
    current = [datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)]
    sessions = SessionAuthority(clock=lambda: current[0], ttl_seconds=1)
    store = CollabStore(tmp_path / "collab.sqlite3")
    app = create_app(
        store,
        session_authority=sessions,
        expected_windows_sid=EXPECTED_SID,
    )
    client = TestClient(app)
    session = sessions.issue(EXPECTED_SID)
    current[0] += timedelta(seconds=2)

    response = client.post(
        "/v1/messages",
        json=_payload("florent-expired-session"),
        headers={"X-Collab-Session": session.token},
    )

    assert response.status_code == 401
    assert response.json() == {"reason_code": "FLORENT_SESSION_REQUIRED"}
    assert store.health()["head_offset"] == 0
    store.close()
