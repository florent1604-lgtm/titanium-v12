from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_mcp_clients_use_singleton_http_endpoints():
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        codex = tomllib.load(handle)["mcp_servers"]

    assert claude["titanium"] == {
        "type": "http", "url": "http://127.0.0.1:8091/mcp"
    }
    assert codex["titanium"] == {"url": "http://127.0.0.1:8091/mcp"}
    assert claude["gitnexus_write_gate"] == {
        "type": "http", "url": "http://127.0.0.1:4750/mcp"
    }
    assert "titanium_structural" not in claude
    assert "titanium_structural" not in codex


def test_titanium_http_catalog_is_strictly_read_only():
    from tools.titanium_mcp_http import mcp

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {
        "get_signal_history",
        "get_pnl_summary",
        "get_active_alerts",
        "get_backtest_results",
        "read_recent_logs",
    }
    assert not names & {
        "modify_scoring_weight", "trigger_recalibration",
        "modify_risk_params", "close_position",
    }


def test_titanium_http_direct_launcher_resolves_the_project_root():
    source = (ROOT / "tools" / "titanium_mcp_http.py").read_text(encoding="utf-8")

    assert "PROJECT_ROOT" in source
    assert "sys.path.insert(0, str(PROJECT_ROOT))" in source
