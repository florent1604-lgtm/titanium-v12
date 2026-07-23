from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_base44_runtime_modules_are_removed():
    for relative in (
        "mcp_base44.py",
        "api/base44_routes.py",
        "core/base44_client.py",
        "core/base44_push.py",
    ):
        assert not (ROOT / relative).exists(), relative


def test_base44_is_absent_from_active_configs_and_surfaces():
    mcp_config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert "base44" not in mcp_config["mcpServers"]

    for relative in (
        ".codex/config.toml",
        "api/api_server.py",
        "utils/config.py",
        "titanium_v12_dashboard.html",
        "titanium_unified.html",
        "titanium_v14_console.html",
    ):
        content = (ROOT / relative).read_text(encoding="utf-8").casefold()
        assert "base44" not in content, relative
