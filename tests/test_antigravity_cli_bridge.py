"""tests/test_antigravity_cli_bridge.py — Tests for the Antigravity CLI bridge.

Run:  cd C:\\Users\\flore\\Desktop\\v12 && venv\\Scripts\\pytest tests/test_antigravity_cli_bridge.py -v
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# The bridge lives in JARVIS, but we test it standalone via sys.path
JARVIS_PATH = Path(r"C:\Program Files\JARVIS")
sys.path.insert(0, str(JARVIS_PATH))

from bridges.antigravity_cli_bridge import (
    find_antigravity_cmd,
    open_file,
    open_workspace,
    open_and_focus,
    _run,
)


# ── find_antigravity_cmd ──────────────────────────────────────────────────────

def test_find_cmd_in_localappdata(tmp_path, monkeypatch):
    """Finds antigravity.cmd when it exists in %LOCALAPPDATA%\\Programs\\Antigravity\\bin\\."""
    fake_cmd = tmp_path / "antigravity.cmd"
    fake_cmd.write_text("@echo off")

    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", None)

    # Patch the search paths to point at our fake file
    monkeypatch.setattr(
        bridge, "_SEARCH_PATHS",
        [fake_cmd, Path("C:/nonexistent/antigravity.cmd")]
    )
    result = bridge.find_antigravity_cmd()
    assert result == str(fake_cmd)


def test_find_cmd_not_found(monkeypatch):
    """Returns None gracefully when antigravity.cmd is nowhere."""
    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", None)
    monkeypatch.setattr(bridge, "_SEARCH_PATHS", [Path("C:/nonexistent/a.cmd")])

    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setenv("JARVIS_ANTIGRAVITY_CMD_PATH", "")

    result = bridge.find_antigravity_cmd()
    assert result is None


def test_find_cmd_uses_env_override(tmp_path, monkeypatch):
    """Respects JARVIS_ANTIGRAVITY_CMD_PATH env variable."""
    fake_cmd = tmp_path / "antigravity.cmd"
    fake_cmd.write_text("@echo off")

    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", None)
    monkeypatch.setattr(bridge, "_SEARCH_PATHS", [])
    monkeypatch.setenv("JARVIS_ANTIGRAVITY_CMD_PATH", str(fake_cmd))

    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)

    result = bridge.find_antigravity_cmd()
    assert result == str(fake_cmd)


# ── open_file ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_file_correct_args(monkeypatch):
    """open_file passes --reuse-window --goto filepath:line to subprocess."""
    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", r"C:\fake\antigravity.cmd")

    captured = {}

    async def mock_run(args, timeout=5.0):
        captured["args"] = args
        return True

    monkeypatch.setattr(bridge, "_run", mock_run)
    result = await bridge.open_file(r"C:\project\main.py", line=42)
    assert result is True
    assert captured["args"] == ["--reuse-window", "--goto", r"C:\project\main.py:42"]


@pytest.mark.asyncio
async def test_open_file_returns_false_when_cmd_missing(monkeypatch):
    """open_file returns False silently when antigravity.cmd not found."""
    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "find_antigravity_cmd", lambda: None)
    monkeypatch.setattr(bridge, "_cached_cmd", None)

    result = await bridge.open_file(r"C:\project\main.py")
    assert result is False


# ── open_workspace ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_workspace_correct_args(monkeypatch):
    """open_workspace passes --reuse-window workspace_path."""
    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", r"C:\fake\antigravity.cmd")

    captured = {}

    async def mock_run(args, timeout=5.0):
        captured["args"] = args
        return True

    monkeypatch.setattr(bridge, "_run", mock_run)
    result = await bridge.open_workspace(r"C:\Users\flore\Desktop\v12")
    assert result is True
    assert captured["args"] == ["--reuse-window", r"C:\Users\flore\Desktop\v12"]


# ── Timeout handling ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_timeout_returns_false(monkeypatch):
    """_run returns False and does not raise when subprocess times out."""
    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", r"C:\fake\antigravity.cmd")

    async def _slow_proc(*args, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        proc.kill = MagicMock()
        async def _hang():
            await asyncio.sleep(999)
            return b"", b""
        proc.communicate = _hang
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=_slow_proc):
        result = await bridge._run(["--version"], timeout=0.01)
    assert result is False


@pytest.mark.asyncio
async def test_run_exception_returns_false(monkeypatch):
    """_run returns False without raising when subprocess raises."""
    import bridges.antigravity_cli_bridge as bridge
    monkeypatch.setattr(bridge, "_cached_cmd", r"C:\fake\antigravity.cmd")

    with patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
        result = await bridge._run(["--version"])
    assert result is False
