from __future__ import annotations

import json
import inspect
import os
from pathlib import Path
from pathlib import PurePath

import pytest

from tools import gitnexus_runtime as runtime


def test_pid_probe_handles_windows_processes_without_system_error(monkeypatch):
    if os.name == "nt":
        def forbidden_os_kill(*_args):
            raise AssertionError("os.kill(pid, 0) is unreliable for unrelated Windows processes")

        monkeypatch.setattr(runtime.os, "kill", forbidden_os_kill)
    assert runtime._pid_is_running(os.getpid()) is True
    assert runtime._pid_is_running(2_147_483_647) is False


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_sync_jarvis_mirror_copies_sources_and_rejects_sensitive_paths(tmp_path):
    source = tmp_path / "jarvis"
    mirror = tmp_path / "mirror"
    _write_tree(source, {
        "main2.py": "print('ok')",
        "frontend/app.js": "export const ok = true",
        ".env": "SECRET=x",
        "credentials_LISEZ_MOI.txt": "secret",
        "jarvis_conversations.json": "[]",
        "jarvis_memoire.json": "{}",
        "knowledge/private.md": "private",
        "main2.py.bak-cutover": "old",
        "voice.mp3": "audio",
        "venv/x.py": "third party",
    })

    report = runtime.sync_jarvis_mirror(source, mirror)

    assert (mirror / "main2.py").exists()
    assert (mirror / "frontend/app.js").exists()
    for forbidden in (
        ".env", "credentials_LISEZ_MOI.txt", "jarvis_conversations.json",
        "jarvis_memoire.json", "knowledge/private.md",
        "main2.py.bak-cutover", "voice.mp3", "venv/x.py",
    ):
        assert not (mirror / forbidden).exists()
    assert report.rejected == 8
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_root"] == str(source.resolve())
    assert sorted(item["path"] for item in manifest["included"]) == [
        "frontend/app.js", "main2.py",
    ]


def test_sync_removes_stale_mirrored_source(tmp_path):
    source = tmp_path / "src"
    mirror = tmp_path / "mirror"
    _write_tree(source, {"old.py": "x=1"})
    runtime.sync_jarvis_mirror(source, mirror)

    (source / "old.py").unlink()
    report = runtime.sync_jarvis_mirror(source, mirror)

    assert not (mirror / "old.py").exists()
    assert report.removed == 1


@pytest.mark.parametrize("path", [
    "data/paper_state.json",
    "data/swing_paper_state.json",
    "data/opportunities.json",
    "signal_history.json",
    "titanium_v12.log",
])
def test_runtime_data_does_not_trigger_index(path):
    assert not runtime.is_index_relevant(PurePath(path))


@pytest.mark.parametrize("path", [
    "core/swing_engine.py",
    "execution/paper_trading.py",
    "api/services_routes.py",
    "tests/test_guards.py",
    "docs/STRATEGY_CONTRACT.md",
])
def test_sources_trigger_index(path):
    assert runtime.is_index_relevant(PurePath(path))


def test_debouncer_runs_after_quiet_period_or_max_delay():
    debouncer = runtime.ChangeDebouncer(debounce_seconds=5.0, max_delay_seconds=15.0)
    debouncer.note_change(0.0)
    assert not debouncer.ready(4.9)
    assert debouncer.ready(5.0)

    debouncer.reset()
    debouncer.note_change(20.0)
    debouncer.note_change(30.0)
    assert not debouncer.ready(34.9)
    assert debouncer.ready(35.0)


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.status = 202

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


def test_gitnexus_health_rejects_http_ok_when_query_probe_times_out(monkeypatch):
    seen_urls = []

    def fake_urlopen(target, *_args, **_kwargs):
        url = target.full_url if isinstance(target, runtime.request.Request) else str(target)
        seen_urls.append(url)
        if url.endswith("/api/health"):
            return _Response(b'{"status": "ok"}')
        if url.endswith("/api/repos"):
            return _Response(b'[{"name": "titanium-v12"}]')
        if url.endswith("/api/query"):
            raise TimeoutError("LadybugDB query lock")
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(runtime.request, "urlopen", fake_urlopen)

    assert runtime.gitnexus_server_healthy("http://127.0.0.1:4747") is False
    assert seen_urls[-1].endswith("/api/query")


def test_gitnexus_repositories_accepts_rc_value_envelope(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "_http_json",
        lambda _url: {"value": [{"name": "titanium-v12"}]},
    )

    assert runtime.gitnexus_repositories() == [{"name": "titanium-v12"}]


def test_opportunity_scan_pause_is_fail_safe(monkeypatch):
    calls = []

    def available(*_args, **kwargs):
        calls.append(kwargs)
        return _Response(b'{"running": false}')

    monkeypatch.setattr(
        runtime.request, "urlopen",
        available,
    )
    assert not runtime.opportunity_scan_running()
    assert calls == [{"timeout": 5.0}]

    monkeypatch.setattr(
        runtime.request, "urlopen",
        lambda *_args, **_kwargs: _Response(b'{"running": true}'),
    )
    assert runtime.opportunity_scan_running()

    def unavailable(*_args, **_kwargs):
        raise OSError("api unavailable")

    monkeypatch.setattr(runtime.request, "urlopen", unavailable)
    assert runtime.opportunity_scan_running()


def test_spawn_low_priority_sets_windows_flags(monkeypatch, tmp_path):
    captured = {}
    sentinel = object()

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)
    result = runtime.spawn_low_priority(["node", "run.cjs", "analyze"], tmp_path)

    assert result is sentinel
    assert captured["cwd"] == str(tmp_path)
    assert captured["creationflags"] & runtime.BELOW_NORMAL_PRIORITY_CLASS
    assert captured["creationflags"] & runtime.CREATE_NO_WINDOW


def test_spawn_low_priority_exposes_git_openssl_dlls(monkeypatch, tmp_path):
    captured = {}
    openssl_bin = tmp_path / "git" / "mingw64" / "bin"
    openssl_bin.mkdir(parents=True)

    def fake_popen(_argv, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime, "GITNEXUS_OPENSSL_BIN", openssl_bin)
    monkeypatch.setenv("PATH", str(tmp_path / "existing"))

    runtime.spawn_low_priority(["node", "gitnexus.js", "serve"], tmp_path)

    assert captured["env"]["PATH"].split(runtime.os.pathsep)[0] == str(openssl_bin)


def test_gitnexus_fts_server_safe_is_version_gated():
    assert not runtime.gitnexus_fts_server_safe("1.6.9")
    assert not runtime.gitnexus_fts_server_safe("1.6.10-rc.49")
    assert runtime.gitnexus_fts_server_safe("1.6.10-rc.50")
    assert runtime.gitnexus_fts_server_safe("1.6.10")
    assert runtime.gitnexus_fts_server_safe("1.7.0")
    assert not runtime.gitnexus_fts_server_safe("unknown")


def test_start_gitnexus_server_disables_crashing_native_fts(monkeypatch):
    captured = {}

    def fake_spawn(argv, cwd, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime, "gitnexus_server_healthy", lambda: False)
    monkeypatch.setattr(runtime, "gitnexus_fts_server_safe", lambda: False)
    monkeypatch.setattr(runtime, "gitnexus_shutdown_token", lambda: "test-token")
    monkeypatch.setattr(runtime, "spawn_low_priority", fake_spawn)

    runtime.start_gitnexus_server()

    assert captured["env_overrides"] == {
        "GITNEXUS_LBUG_EXTENSION_INSTALL": "never",
        "GITNEXUS_MCP_READ_ONLY": "1",
        "GITNEXUS_SHUTDOWN_TOKEN": "test-token",
    }


def test_start_gitnexus_server_enables_fts_on_validated_version(monkeypatch):
    captured = {}

    def fake_spawn(argv, cwd, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime, "gitnexus_server_healthy", lambda: False)
    monkeypatch.setattr(runtime, "gitnexus_fts_server_safe", lambda: True)
    monkeypatch.setattr(runtime, "gitnexus_shutdown_token", lambda: "test-token")
    monkeypatch.setattr(runtime, "spawn_low_priority", fake_spawn)

    runtime.start_gitnexus_server()

    assert captured["env_overrides"] == {
        "GITNEXUS_MCP_READ_ONLY": "1",
        "GITNEXUS_SHUTDOWN_TOKEN": "test-token",
    }


def test_quarantine_empty_orphan_wal_is_bounded_and_preserves_evidence(tmp_path):
    gitnexus_dir = tmp_path / ".gitnexus"
    gitnexus_dir.mkdir()
    wal = gitnexus_dir / "lbug.wal"
    wal.write_bytes(b"x" * 42)

    assert runtime.quarantine_empty_orphan_wal(tmp_path)
    assert not wal.exists()
    quarantined = list(gitnexus_dir.glob("lbug.wal.missing-shadow.*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"x" * 42


def test_quarantine_empty_orphan_wal_preserves_matching_shadow(tmp_path):
    gitnexus_dir = tmp_path / ".gitnexus"
    gitnexus_dir.mkdir()
    wal = gitnexus_dir / "lbug.wal"
    shadow = gitnexus_dir / "lbug.shadow"
    wal.write_bytes(b"x" * 42)
    shadow.write_bytes(b"rollback-evidence")

    assert runtime.quarantine_empty_orphan_wal(tmp_path)
    assert not wal.exists()
    assert not shadow.exists()
    quarantined_shadow = list(gitnexus_dir.glob("lbug.shadow.closed.*"))
    assert len(quarantined_shadow) == 1
    assert quarantined_shadow[0].read_bytes() == b"rollback-evidence"


def test_quarantine_empty_orphan_wal_fails_closed_on_nonempty_wal(tmp_path):
    gitnexus_dir = tmp_path / ".gitnexus"
    gitnexus_dir.mkdir()
    wal = gitnexus_dir / "lbug.wal"
    wal.write_bytes(b"x" * 43)

    assert runtime.quarantine_empty_orphan_wal(tmp_path) is False
    assert wal.exists()


def test_stop_gitnexus_server_uses_authenticated_graceful_endpoint(monkeypatch, tmp_path):
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("4242", encoding="ascii")
    running = iter((True, False, False))
    captured = {}

    def fake_urlopen(target, *_args, **_kwargs):
        captured["request"] = target
        return _Response(b'{"status":"shutting_down"}')

    monkeypatch.setattr(runtime, "SERVER_PID_PATH", pid_path)
    monkeypatch.setattr(runtime, "_pid_is_running", lambda _pid: next(running))
    monkeypatch.setattr(runtime, "gitnexus_shutdown_token", lambda: "test-token")
    monkeypatch.setattr(runtime, "quarantine_empty_orphan_wal", lambda _repo: True)
    monkeypatch.setattr(runtime.request, "urlopen", fake_urlopen)

    assert runtime.stop_gitnexus_server(timeout=0.1)
    assert captured["request"].full_url.endswith("/api/shutdown")
    assert captured["request"].get_header("X-gitnexus-shutdown-token") == "test-token"
    assert not pid_path.exists()


def test_stop_gitnexus_server_allows_slow_windows_shutdown():
    timeout = inspect.signature(runtime.stop_gitnexus_server).parameters["timeout"]
    assert timeout.default == 30.0


def test_stop_gitnexus_server_accepts_disconnect_only_after_pid_exits(monkeypatch, tmp_path):
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("4242", encoding="ascii")
    running = iter((True, False, False))

    monkeypatch.setattr(runtime, "SERVER_PID_PATH", pid_path)
    monkeypatch.setattr(runtime, "_pid_is_running", lambda _pid: next(running))
    monkeypatch.setattr(runtime, "gitnexus_shutdown_token", lambda: "test-token")
    monkeypatch.setattr(runtime, "quarantine_empty_orphan_wal", lambda _repo: True)
    monkeypatch.setattr(
        runtime.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionResetError()),
    )

    assert runtime.stop_gitnexus_server(timeout=0.1)
    assert not pid_path.exists()


def test_analyze_repository_cycles_healthy_server_around_index(monkeypatch, tmp_path):
    events = []

    class _AnalyzeProcess:
        def wait(self):
            events.append("wait_analyze")
            return 0

    monkeypatch.setattr(runtime, "opportunity_scan_running", lambda: False)
    monkeypatch.setattr(runtime, "gitnexus_server_healthy", lambda: True)
    monkeypatch.setattr(runtime, "managed_gitnexus_server_running", lambda: True)
    monkeypatch.setattr(
        runtime, "stop_gitnexus_server", lambda: events.append("stop_server") or True,
    )
    monkeypatch.setattr(
        runtime, "spawn_low_priority",
        lambda *_args, **_kwargs: events.append("spawn_analyze") or _AnalyzeProcess(),
    )
    monkeypatch.setattr(
        runtime, "start_gitnexus_server",
        lambda: events.append("start_server") or object(),
    )
    monkeypatch.setattr(
        runtime, "_wait_for_server", lambda: events.append("wait_server") or True,
    )

    assert runtime.analyze_repository(tmp_path) == 0
    assert events == [
        "stop_server", "spawn_analyze", "wait_analyze", "start_server", "wait_server",
    ]


def test_analyze_repository_refuses_unmanaged_healthy_server(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "opportunity_scan_running", lambda: False)
    monkeypatch.setattr(runtime, "gitnexus_server_healthy", lambda: True)
    monkeypatch.setattr(runtime, "managed_gitnexus_server_running", lambda: False)
    monkeypatch.setattr(runtime, "stop_gitnexus_server", lambda: False)
    monkeypatch.setattr(
        runtime,
        "spawn_low_priority",
        lambda *_args, **_kwargs: pytest.fail("analysis must not race an unmanaged server"),
    )

    assert runtime.analyze_repository(tmp_path) == 69


def test_analyze_repository_retries_failed_incremental_once_with_force(monkeypatch, tmp_path):
    commands = []
    return_codes = iter((1, 0))

    class _AnalyzeProcess:
        def __init__(self, code):
            self._code = code

        def wait(self):
            return self._code

    monkeypatch.setattr(runtime, "opportunity_scan_running", lambda: False)
    monkeypatch.setattr(runtime, "gitnexus_server_healthy", lambda: False)
    monkeypatch.setattr(runtime, "managed_gitnexus_server_running", lambda: False)

    def fake_spawn(argv, _cwd, **_kwargs):
        commands.append(argv)
        return _AnalyzeProcess(next(return_codes))

    monkeypatch.setattr(runtime, "spawn_low_priority", fake_spawn)

    assert runtime.analyze_repository(tmp_path) == 0
    assert "--force" not in commands[0]
    assert "--force" in commands[1]
    assert "--index-only" in commands[1]
    assert len(commands) == 2


def test_gitnexus_index_stale_compares_indexed_and_current_commit(monkeypatch, tmp_path):
    metadata = tmp_path / ".gitnexus" / "meta.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"lastCommit": "old-head"}), encoding="utf-8")

    class _GitResult:
        returncode = 0
        stdout = "new-head\n"

    monkeypatch.setattr(runtime.subprocess, "run", lambda *_args, **_kwargs: _GitResult())
    assert runtime.gitnexus_index_stale(tmp_path)

    metadata.write_text(json.dumps({"lastCommit": "new-head"}), encoding="utf-8")
    assert not runtime.gitnexus_index_stale(tmp_path)


def test_gitnexus_command_uses_project_pinned_cli_before_npx(monkeypatch, tmp_path):
    global_cli = tmp_path / "missing-global" / "index.js"
    project_cli = tmp_path / "project" / "gitnexus" / "index.js"
    project_cli.parent.mkdir(parents=True)
    project_cli.write_text("// pinned cli", encoding="utf-8")
    monkeypatch.setattr(runtime, "GITNEXUS_GLOBAL_CLI", global_cli)
    monkeypatch.setattr(runtime, "GITNEXUS_PROJECT_CLI", project_cli, raising=False)

    command = runtime.gitnexus_command("status")

    assert command == ["node", str(project_cli), "status"]


def test_gitnexus_serve_command_is_direct_and_ipv4_loopback(monkeypatch, tmp_path):
    cli = tmp_path / "gitnexus" / "dist" / "cli" / "index.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("// cli", encoding="utf-8")
    monkeypatch.setattr(runtime, "GITNEXUS_GLOBAL_CLI", cli)

    command = runtime.gitnexus_serve_command()

    assert command == [
        "node", str(cli), "serve", "--port", "4747", "--host", "127.0.0.1",
    ]


def test_session_plan_is_idempotent_and_repairs_only_missing_parts(tmp_path):
    project = tmp_path / "v12"
    mirror = tmp_path / "jarvis-runtime"
    project.mkdir()
    mirror.mkdir()

    healthy = runtime.plan_session_actions(
        server_healthy=True,
        registered_paths={str(project.resolve()), str(mirror.resolve())},
        project_root=project,
        mirror_root=mirror,
        project_stale=False,
        mirror_changed=False,
        no_watch=False,
    )
    assert healthy == ("watch",)

    repair = runtime.plan_session_actions(
        server_healthy=False,
        registered_paths={str(project.resolve())},
        project_root=project,
        mirror_root=mirror,
        project_stale=True,
        mirror_changed=True,
        no_watch=False,
    )
    assert repair == (
        "analyze_project", "analyze_mirror", "serve", "watch",
    )


def test_source_snapshot_ignores_runtime_json(tmp_path):
    _write_tree(tmp_path, {
        "core/a.py": "x = 1",
        "data/paper_state.json": "{}",
        "docs/design.md": "design",
    })

    snapshot = runtime.source_snapshot(tmp_path)

    assert set(snapshot) == {"core/a.py", "docs/design.md"}


def test_jarvis_snapshot_uses_the_sanitized_mirror_whitelist(tmp_path):
    _write_tree(tmp_path, {
        "main2.py": "x = 1",
        "frontend/app.ts": "export const x = 1",
        "knowledge/private.md": "runtime memory",
        "data/state.json": "{}",
        ".env": "SECRET=x",
    })

    snapshot = runtime.jarvis_source_snapshot(tmp_path)

    assert set(snapshot) == {"main2.py", "frontend/app.ts"}


def test_identical_mirror_sync_does_not_rewrite_manifest(tmp_path):
    source = tmp_path / "source"
    mirror = tmp_path / "mirror"
    _write_tree(source, {"main2.py": "x = 1"})
    first = runtime.sync_jarvis_mirror(source, mirror)
    before = first.manifest_path.read_bytes()

    second = runtime.sync_jarvis_mirror(source, mirror)

    assert second.copied == 0
    assert second.manifest_path.read_bytes() == before
