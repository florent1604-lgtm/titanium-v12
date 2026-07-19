from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_gitnexus_gate import GitNexusClient


def test_claude_project_scope_has_no_conflicting_gitnexus_transport():
    cfg = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "gitnexus" not in cfg
    assert cfg["gitnexus_write_gate"] == {
        "command": str(Path.cwd() / "gitnexus/gate-venv/Scripts/python.exe"),
        "args": [str(Path.cwd() / "mcp_gitnexus_gate.py")],
    }


def test_configurator_uses_claude_http_user_scope_without_credentials():
    script = Path("tools/configure_gitnexus_mcp.ps1").read_text(encoding="utf-8")
    endpoint = "http://127.0.0.1:4747/api/mcp"
    assert "$Claude" in script
    assert endpoint in script
    assert "mcp add --transport http --scope user gitnexus $ClaudeGitNexusEndpoint" in script
    assert "mcp remove gitnexus --scope user" in script
    assert "--mcp-verified" in script
    assert "ANTHROPIC_API_KEY" not in script
    assert "--header" not in script
    assert "--client-secret" not in script


def test_configurator_keeps_codex_direct_and_gates_hermes():
    script = Path("tools/configure_gitnexus_mcp.ps1").read_text(encoding="utf-8")
    assert "codex mcp add gitnexus -- node $GitNexusRuntime mcp" in script
    assert '"Y" | & $Hermes mcp add gitnexus --command $ProjectPython --args $GitNexusGate' in script
    assert "$HermesTest" in script
    assert 'notmatch "Connected"' in script


def test_gitnexus_mcp_bootstrap_preloads_native_binding_before_cli():
    bootstrap = Path("tools/gitnexus_mcp_bootstrap.mjs").read_text(encoding="utf-8")
    assert "process.env.APPDATA" in bootstrap
    assert '"npm", "node_modules", "gitnexus"' in bootstrap
    native = "node_modules/@ladybugdb/core/index.js"
    sentinel = "installGlobalStdoutSentinel();"
    backend = "dist/mcp/local/local-backend.js"
    assert bootstrap.index(native) < bootstrap.index(sentinel) < bootstrap.index(backend)


def test_detect_changes_runner_returns_structured_result_and_disposes_backend():
    runner = Path("tools/gitnexus_detect_changes.mjs").read_text(encoding="utf-8")
    assert "new LocalBackend()" in runner
    assert 'callTool("detect_changes"' in runner
    assert "JSON.stringify(result)" in runner
    assert "await backend.dispose()" in runner


def test_gate_uses_bootstrap_with_fixed_safe_directory():
    parameters = GitNexusClient()._parameters()
    assert parameters.command == "node"
    assert parameters.args == [
        str(Path.cwd() / "tools/gitnexus_mcp_bootstrap.mjs"),
        "mcp",
    ]
    assert parameters.cwd == str(Path.cwd())
    assert parameters.env == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(Path.cwd()),
    }


@pytest.mark.asyncio
async def test_detect_changes_uses_stable_cli_path_not_mcp(monkeypatch):
    recorded = {}

    class Process:
        returncode = 0

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_exec(*args, **kwargs):
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        kwargs["stdout"].write(b'{"summary":{"changed_count":138}}')
        kwargs["stderr"].write(b"git warning")
        return Process()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await GitNexusClient().detect_changes()

    assert result == {"summary": {"changed_count": 138}}
    assert recorded["args"] == (
        "node",
        str(Path.cwd() / "tools/gitnexus_detect_changes.mjs"),
    )
    assert recorded["kwargs"]["cwd"] == str(Path.cwd())
    assert recorded["kwargs"]["env"]["GIT_CONFIG_VALUE_0"] == str(Path.cwd())
    assert recorded["kwargs"]["stdout"] != -1
    assert recorded["kwargs"]["stderr"] != -1


@pytest.mark.asyncio
async def test_detect_changes_cli_failure_is_fail_closed(monkeypatch):
    class Process:
        returncode = -1073741819

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_exec(*args, **kwargs):
        return Process()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="DETECT_CHANGES_CLI_FAILED"):
        await GitNexusClient().detect_changes()


def test_gate_environment_requirements_are_exactly_pinned():
    requirements = Path("requirements-gitnexus-gate.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert requirements == [
        "mcp==1.28.1",
        "cryptography==49.0.0",
        "pytest==9.1.1",
        "pytest-asyncio==1.4.0",
    ]
