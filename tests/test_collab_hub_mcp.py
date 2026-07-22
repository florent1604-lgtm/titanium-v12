from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

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
