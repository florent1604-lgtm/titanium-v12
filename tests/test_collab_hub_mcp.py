from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from collab_hub.app import RealtimeBroker, create_app
from collab_hub.mcp import create_collab_mcp
from collab_hub.store import CollabStore


EXPECTED_TOOLS = {
    "collab_publish",
    "collab_read",
    "collab_ack",
    "collab_presence",
    "collab_health",
}


def _publish_arguments(key: str, content: str) -> dict:
    return {
        "principal": "codex",
        "target": "claude",
        "kind": "handoff",
        "content": content,
        "idempotency_key": key,
    }


def test_mcp_exposes_only_the_five_c1_tools(tmp_path: Path) -> None:
    store = CollabStore(tmp_path / "collab.sqlite3")
    mcp = create_collab_mcp(store, RealtimeBroker())

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert names == EXPECTED_TOOLS
    assert not names & {
        "permissions_respond",
        "shell",
        "write_file",
        "git_commit",
        "execute_trade",
        "dispatch_command",
    }
    store.close()


@pytest.mark.parametrize(
    "content",
    (
        "token=not-a-real-session-token-42",
        "password=not-a-real-credential-42",
        "-----BEGIN PRIVATE KEY-----",
    ),
)
def test_mcp_publish_rejects_secrets_before_persistence(
    tmp_path: Path, content: str
) -> None:
    store = CollabStore(tmp_path / "collab.sqlite3")
    mcp = create_collab_mcp(store, RealtimeBroker())

    with pytest.raises(ToolError) as rejected:
        asyncio.run(
            mcp.call_tool(
                "collab_publish", _publish_arguments("mcp-secret", content)
            )
        )

    assert str(rejected.value) == (
        "Error executing tool collab_publish: SECRET_REJECTED"
    )
    assert content not in str(rejected.value)
    assert store.health()["head_offset"] == 0
    store.close()


def test_mcp_publish_still_accepts_non_secret_agent_message(tmp_path: Path) -> None:
    store = CollabStore(tmp_path / "collab.sqlite3")
    mcp = create_collab_mcp(store, RealtimeBroker())

    asyncio.run(
        mcp.call_tool(
            "collab_publish",
            _publish_arguments("mcp-clean", "Compte rendu de revue sans secret"),
        )
    )

    assert store.health()["head_offset"] == 1
    store.close()


def test_mcp_is_mounted_on_exact_loopback_client_path(tmp_path: Path) -> None:
    store = CollabStore(tmp_path / "collab.sqlite3")
    client = TestClient(create_app(store), base_url="http://127.0.0.1:8770")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "collab-test", "version": "1.0"},
        },
    }

    with client:
        response = client.post("/mcp", headers=headers, json=initialize, follow_redirects=False)
        assert response.status_code == 200
        payload = response.json()
        assert payload["result"]["serverInfo"]["name"] == "titanium-collab-hub"

        tools = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            follow_redirects=False,
        )
        assert tools.status_code == 200
        assert {item["name"] for item in tools.json()["result"]["tools"]} == EXPECTED_TOOLS
    store.close()
