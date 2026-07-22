from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from collab_hub.app import create_app
from collab_hub.store import CollabStore


def _payload(key: str) -> dict:
    return {
        "principal": "codex",
        "target": "claude",
        "kind": "handoff",
        "content": "résultat vérifiable",
        "idempotency_key": key,
        "task_id": "COLLAB_HUB",
        "evidence_refs": ["gitnexus://repo/titanium-v12/context"],
    }


def _client(tmp_path: Path) -> tuple[TestClient, CollabStore]:
    store = CollabStore(tmp_path / "collab.sqlite3")
    return TestClient(create_app(store)), store


def test_publish_health_read_and_ack(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    published = client.post("/v1/messages", json=_payload("api-1"))
    assert published.status_code == 201
    assert published.json()["global_offset"] == 1

    replay = client.get("/v1/messages", params={"after_offset": 0, "limit": 10})
    assert replay.status_code == 200
    assert replay.json()["messages"][0]["content"] == "résultat vérifiable"

    ack = client.post("/v1/consumers/hermes/ack", json={"global_offset": 1})
    assert ack.status_code == 200
    assert ack.json() == {"consumer_id": "hermes", "global_offset": 1}

    health = client.get("/health").json()
    assert health["ok"] is True
    assert health["head_offset"] == 1
    assert health["ws_clients"] == 0
    store.close()


def test_invalid_payload_is_rejected_without_commit(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    payload = _payload("api-invalid")
    payload["principal"] = "intrus"

    response = client.post("/v1/messages", json=payload)

    assert response.status_code == 400
    assert store.health()["head_offset"] == 0
    store.close()


def test_sse_replay_uses_global_offset_as_event_id(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    client.post("/v1/messages", json=_payload("sse-1"))

    response = client.get("/v1/stream", params={"after_offset": 0, "follow": "false"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 1\n" in response.text
    assert "event: message\n" in response.text
    assert '"idempotency_key":"sse-1"' in response.text
    store.close()


def test_websocket_receives_committed_message_and_cleans_up(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    with client.websocket_connect("/v1/ws?after_offset=0") as websocket:
        assert client.get("/health").json()["ws_clients"] == 1
        response = client.post("/v1/messages", json=_payload("ws-1"))
        assert response.status_code == 201
        message = websocket.receive_json()
        assert message["global_offset"] == 1
        assert message["idempotency_key"] == "ws-1"

    assert client.get("/health").json()["ws_clients"] == 0
    store.close()
