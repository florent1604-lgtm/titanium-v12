from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from collab_hub.app import create_app
from collab_hub.contracts import MessageDraft
from collab_hub.session import SessionAuthority
from collab_hub.store import CollabStore
from collab_hub.task_contracts import TaskDraft
from collab_hub.windows_attestation import WindowsAttestation


EXPECTED_SID = "S-1-5-21-florent"


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class RecordingProtector:
    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        return value.removeprefix(b"protected:")[::-1]


def _session_dependencies(
    tmp_path: Path, clock: FakeClock
) -> tuple[WindowsAttestation, SessionAuthority]:
    return (
        WindowsAttestation(
            clock=clock,
            key_path=tmp_path / "session.key.dpapi",
            protector=RecordingProtector(),
            acl_hardener=lambda _path: None,
        ),
        SessionAuthority(clock=clock, ttl_seconds=900),
    )


def _client(
    tmp_path: Path, clock: FakeClock | None = None
) -> tuple[TestClient, CollabStore, WindowsAttestation, SessionAuthority]:
    effective_clock = clock or FakeClock()
    attestation, sessions = _session_dependencies(tmp_path, effective_clock)
    store = CollabStore(tmp_path / "collab.sqlite3", task_clock=effective_clock)
    app = create_app(
        store,
        attestation=attestation,
        session_authority=sessions,
        expected_windows_sid=EXPECTED_SID,
    )
    return TestClient(app), store, attestation, sessions


def _session_token(
    client: TestClient,
    attestation: WindowsAttestation,
    sid: str = EXPECTED_SID,
) -> str:
    nonce = client.post("/v1/session/challenge").json()["nonce"]
    proof = attestation.test_proof(sid, nonce)
    response = client.post(
        "/v1/session/windows",
        json={"sid": sid, "nonce": nonce, "proof": proof},
    )
    assert response.status_code == 201
    return response.json()["token"]


def _message(key: str) -> MessageDraft:
    return MessageDraft(
        principal="codex",
        target="claude",
        kind="status",
        content=key,
        idempotency_key=key,
    )


def test_session_challenge_is_exposed_over_http(tmp_path: Path) -> None:
    client, store, _attestation, _sessions = _client(tmp_path)

    response = client.post("/v1/session/challenge")

    assert response.status_code == 201
    assert isinstance(response.json()["nonce"], str)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    store.close()


def test_windows_proof_issues_memory_only_session_token(tmp_path: Path) -> None:
    client, store, attestation, sessions = _client(tmp_path)
    nonce = client.post("/v1/session/challenge").json()["nonce"]
    proof = attestation.test_proof("S-1-5-21-florent", nonce)

    response = client.post(
        "/v1/session/windows",
        json={"sid": "S-1-5-21-florent", "nonce": nonce, "proof": proof},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    token = response.json()["token"]
    assert sessions.verify(token).windows_sid == "S-1-5-21-florent"
    assert token not in repr(vars(sessions))
    store.close()


def test_blank_sid_is_rejected_even_with_matching_proof(tmp_path: Path) -> None:
    client, store, attestation, _sessions = _client(tmp_path)
    nonce = client.post("/v1/session/challenge").json()["nonce"]
    proof = attestation.test_proof("", nonce)

    response = client.post(
        "/v1/session/windows",
        json={"sid": "", "nonce": nonce, "proof": proof},
    )

    assert response.status_code == 401
    assert response.json() == {"reason_code": "WINDOWS_ATTESTATION_REJECTED"}
    store.close()


def test_valid_proof_for_another_sid_cannot_issue_a_session(tmp_path: Path) -> None:
    client, store, attestation, sessions = _client(tmp_path)
    other_sid = "S-1-5-21-other-user"
    nonce = client.post("/v1/session/challenge").json()["nonce"]
    proof = attestation.test_proof(other_sid, nonce)

    response = client.post(
        "/v1/session/windows",
        json={"sid": other_sid, "nonce": nonce, "proof": proof},
    )

    assert response.status_code == 401
    assert response.json() == {"reason_code": "WINDOWS_ATTESTATION_REJECTED"}
    assert sessions._sessions == {}
    store.close()


def test_task_authorization_rejects_session_for_another_sid(tmp_path: Path) -> None:
    client, store, _attestation, sessions = _client(tmp_path)
    other_session = sessions.issue("S-1-5-21-other-user")

    response = client.get(
        "/v1/tasks", headers={"X-Collab-Session": other_session.token}
    )

    assert response.status_code == 401
    assert response.json() == {"reason_code": "FLORENT_SESSION_REQUIRED"}
    store.close()


def test_windows_attestation_failures_share_one_public_reason_code(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    client, store, attestation, _sessions = _client(tmp_path, clock)

    missing_proof_nonce = client.post("/v1/session/challenge").json()["nonce"]
    missing_proof = client.post(
        "/v1/session/windows",
        json={"sid": "S-1-5-21-florent", "nonce": missing_proof_nonce},
    )
    expired_nonce = client.post("/v1/session/challenge").json()["nonce"]
    expired_proof = attestation.test_proof("S-1-5-21-florent", expired_nonce)
    clock.advance(30)
    expired = client.post(
        "/v1/session/windows",
        json={"sid": "S-1-5-21-florent", "nonce": expired_nonce, "proof": expired_proof},
    )
    replay_nonce = client.post("/v1/session/challenge").json()["nonce"]
    replay_proof = attestation.test_proof("S-1-5-21-florent", replay_nonce)
    accepted = client.post(
        "/v1/session/windows",
        json={"sid": "S-1-5-21-florent", "nonce": replay_nonce, "proof": replay_proof},
    )
    assert accepted.status_code == 201
    replayed = client.post(
        "/v1/session/windows",
        json={"sid": "S-1-5-21-florent", "nonce": replay_nonce, "proof": replay_proof},
    )
    altered_nonce = client.post("/v1/session/challenge").json()["nonce"]
    altered_proof = attestation.test_proof("S-1-5-21-florent", altered_nonce)
    altered_proof = ("0" if altered_proof[0] != "0" else "1") + altered_proof[1:]
    altered = client.post(
        "/v1/session/windows",
        json={"sid": "S-1-5-21-florent", "nonce": altered_nonce, "proof": altered_proof},
    )

    responses = (missing_proof, expired, replayed, altered)

    assert [(response.status_code, response.json()) for response in responses] == [
        (401, {"reason_code": "WINDOWS_ATTESTATION_REJECTED"}),
        (401, {"reason_code": "WINDOWS_ATTESTATION_REJECTED"}),
        (401, {"reason_code": "WINDOWS_ATTESTATION_REJECTED"}),
        (401, {"reason_code": "WINDOWS_ATTESTATION_REJECTED"}),
    ]
    assert all(
        response.headers["cache-control"] == "no-store"
        and response.headers["pragma"] == "no-cache"
        for response in responses
    )
    store.close()


def test_task_create_and_transition_require_a_florent_session(tmp_path: Path) -> None:
    client, store, attestation, _sessions = _client(tmp_path)
    payload = {"title": "Revoir le correctif", "owner": "codex", "priority": "P1"}

    denied = client.post("/v1/tasks", json=payload)
    token = _session_token(client, attestation)
    created = client.post(
        "/v1/tasks", json=payload, headers={"X-Collab-Session": token}
    )
    transitioned = client.post(
        f"/v1/tasks/{created.json()['task_id']}/transition",
        json={"status": "A_ANALYSER"},
        headers={"X-Collab-Session": token},
    )

    assert denied.status_code == 401
    assert denied.json() == {"reason_code": "FLORENT_SESSION_REQUIRED"}
    assert created.status_code == 201
    assert transitioned.status_code == 200
    assert transitioned.json()["status"] == "A_ANALYSER"
    listed = client.get("/v1/tasks", headers={"X-Collab-Session": token})
    assert [task["task_id"] for task in listed.json()["tasks"]] == [
        created.json()["task_id"]
    ]
    store.close()


@pytest.mark.parametrize("endpoint", ("/v1/tasks", "/v1/failures"))
def test_task_reads_require_a_live_florent_session(
    tmp_path: Path, endpoint: str
) -> None:
    clock = FakeClock()
    client, store, attestation, _sessions = _client(tmp_path, clock)

    missing = client.get(endpoint)
    invalid = client.get(endpoint, headers={"X-Collab-Session": "invalid-token"})
    expired_token = _session_token(client, attestation)
    clock.advance(901)
    expired = client.get(
        endpoint, headers={"X-Collab-Session": expired_token}
    )
    live_token = _session_token(client, attestation)
    accepted = client.get(endpoint, headers={"X-Collab-Session": live_token})

    assert [missing.status_code, invalid.status_code, expired.status_code] == [
        401,
        401,
        401,
    ]
    assert accepted.status_code == 200
    store.close()


def test_task_secret_gate_runs_before_persistence(tmp_path: Path) -> None:
    client, store, attestation, _sessions = _client(tmp_path)
    token = _session_token(client, attestation)

    response = client.post(
        "/v1/tasks",
        json={
            "title": "password=not-a-real-credential-42",
            "owner": "codex",
            "priority": "P1",
        },
        headers={"X-Collab-Session": token},
    )

    assert response.status_code == 400
    assert response.json() == {"reason_code": "SECRET_REJECTED"}
    assert store.tasks.list_tasks() == ()
    store.close()


def test_retry_requires_florent_session_and_is_manual(tmp_path: Path) -> None:
    client, store, attestation, _sessions = _client(tmp_path)
    task = store.tasks.create_task(
        TaskDraft(title="Revalider", owner="codex", priority="P1")
    )
    store.tasks.record_failure(task.task_id, "TEST_FAILED", "pytest:1")

    denied = client.post(f"/v1/tasks/{task.task_id}/retry")
    assert denied.status_code == 401
    assert store.tasks.attempt_count(task.task_id) == 1

    token = _session_token(client, attestation)
    accepted = client.post(
        f"/v1/tasks/{task.task_id}/retry",
        headers={"X-Collab-Session": token},
    )

    assert accepted.status_code == 201
    assert accepted.json()["requested_by"] == "florent"
    assert store.tasks.attempt_count(task.task_id) == 2
    store.close()


def test_failures_are_readable_without_mutating_attempts(tmp_path: Path) -> None:
    client, store, attestation, _sessions = _client(tmp_path)
    task = store.tasks.create_task(
        TaskDraft(title="Diagnostiquer", owner="claude", priority="P2")
    )
    failure = store.tasks.record_failure(
        task.task_id, "SERVICE_UNAVAILABLE", "health:degraded"
    )

    token = _session_token(client, attestation)
    response = client.get(
        "/v1/failures", headers={"X-Collab-Session": token}
    )

    assert response.status_code == 200
    assert response.json()["failures"][0]["attempt_id"] == failure.attempt_id
    assert store.tasks.attempt_count(task.task_id) == 1
    store.close()


def test_failed_attempt_is_not_retried_after_twenty_four_hours(tmp_path: Path) -> None:
    clock = FakeClock()
    client, store, attestation, _sessions = _client(tmp_path, clock)
    initial_timestamp = clock.current.isoformat()
    task = store.tasks.create_task(
        TaskDraft(title="Attendre Florent", owner="hermes", priority="P3")
    )
    failure = store.tasks.record_failure(task.task_id, "TIMEOUT", "worker:timeout")

    assert task.created_at == initial_timestamp
    assert failure.created_at == initial_timestamp

    clock.advance(24 * 60 * 60)
    advanced_timestamp = clock.current.isoformat()
    later_task = store.tasks.create_task(
        TaskDraft(title="Horloge témoin", owner="codex", priority="P3")
    )
    assert later_task.created_at == advanced_timestamp

    token = _session_token(client, attestation)
    response = client.get(
        "/v1/failures", headers={"X-Collab-Session": token}
    )

    assert response.status_code == 200
    assert len(response.json()["failures"]) == 1
    assert store.tasks.attempt_count(task.task_id) == 1
    assert store.tasks.get_task(task.task_id).updated_at == initial_timestamp
    store.close()


def test_message_offsets_cannot_mix_forward_and_backward_pagination(
    tmp_path: Path,
) -> None:
    client, store, _attestation, _sessions = _client(tmp_path)

    response = client.get(
        "/v1/messages", params={"after_offset": 1, "before_offset": 4}
    )

    assert response.status_code == 400
    store.close()


def test_two_backward_pages_rebuild_global_order_without_gaps_or_duplicates(
    tmp_path: Path,
) -> None:
    client, store, _attestation, _sessions = _client(tmp_path)
    for index in range(1, 7):
        store.publish(_message(f"message-{index}"))

    newest = client.get(
        "/v1/messages", params={"before_offset": 7, "limit": 3}
    ).json()["messages"]
    older = client.get(
        "/v1/messages",
        params={"before_offset": newest[0]["global_offset"], "limit": 3},
    ).json()["messages"]

    rebuilt = older + newest
    assert [message["global_offset"] for message in rebuilt] == list(range(1, 7))
    assert len({message["message_id"] for message in rebuilt}) == 6
    store.close()
