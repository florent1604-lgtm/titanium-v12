from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_URL = "http://127.0.0.1:8770/mcp"


def test_claude_and_codex_use_the_same_collab_hub_singleton() -> None:
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        codex = tomllib.load(handle)["mcp_servers"]

    assert claude["collab_hub"] == {"type": "http", "url": EXPECTED_URL}
    assert codex["collab_hub"] == {"url": EXPECTED_URL}
    assert "base44" not in claude
    assert "base44" not in codex


def test_singleton_supervisor_manages_collab_hub_without_replacing_existing_services() -> None:
    source = (ROOT / "tools" / "mcp_singletons.ps1").read_text(encoding="utf-8")

    assert 'Name = "collab-hub"; Port = 8770' in source
    assert r'tools\collab_hub_server.py' in source
    for existing in ("gitnexus-write-gate", "titanium-mcp", "hermes-mcp"):
        assert existing in source


def test_launcher_is_strictly_loopback_on_port_8770() -> None:
    source = (ROOT / "tools" / "collab_hub_server.py").read_text(encoding="utf-8")

    assert 'host="127.0.0.1"' in source
    assert "port=8770" in source
    assert "reload=False" in source


def test_launcher_imports_in_the_pinned_mcp_environment() -> None:
    python = ROOT / "gitnexus" / "gate-venv" / "Scripts" / "python.exe"
    result = subprocess.run(
        [str(python), str(ROOT / "tools" / "collab_hub_server.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "COLLAB_IMPORT_OK"
