"""Contract tests for the repo-local Claude/Codex -> Hermes MCP bridge."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_URL = "http://127.0.0.1:8766/mcp"


def test_claude_project_mcp_config_exposes_hermes_bridge() -> None:
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["hermes"]

    assert server == {"type": "http", "url": EXPECTED_URL}


def test_codex_project_mcp_config_exposes_same_hermes_bridge() -> None:
    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    server = config["mcp_servers"]["hermes"]

    assert server == {"url": EXPECTED_URL}


def test_bridge_runbook_is_present() -> None:
    runbook = ROOT / "collab" / "HERMES_BRIDGE.md"
    assert runbook.is_file()
    text = runbook.read_text(encoding="utf-8")
    assert EXPECTED_URL in text
    assert "PAPER ONLY" in text
    assert "permissions_respond" in text
