"""Runtime local GitNexus pour Titanium.

Le module ne copie vers le miroir JARVIS que des sources explicitement autorisées.
Il ne lit ni ne journalise le contenu des fichiers rejetés.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePath
from shutil import copy2
from typing import Any, Sequence
from urllib import error, request


ALLOWED_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue",
    ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml",
    ".md", ".ps1", ".bat", ".cmd",
}
ALLOWED_EXACT_FILES = {"requirements.txt"}
DENIED_DIRS = {
    "venv", ".venv", "__pycache__", "node_modules", "knowledge", "data",
    "cache", "audio_cache", "logs", "backups",
}
DENIED_NAMES = {
    ".env", "jarvis_conversations.json", "jarvis_memoire.json",
    "auth.json", "secrets.json",
}
DENIED_SUFFIXES = {".mp3", ".wav", ".ogg", ".flac", ".key"}
SENSITIVE_NAME_PARTS = {"credential", "secret", "token"}
MANIFEST_NAME = "mirror_manifest.json"
OPPORTUNITY_STATUS_URL = "http://127.0.0.1:8090/opportunities/status"
GITNEXUS_HOST = "127.0.0.1"
GITNEXUS_PORT = 4747
GITNEXUS_BASE_URL = f"http://{GITNEXUS_HOST}:{GITNEXUS_PORT}"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BELOW_NORMAL_PRIORITY_CLASS = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
INDEX_SUFFIXES = ALLOWED_SUFFIXES | {".mq5"}
INDEX_IGNORED_ROOTS = {
    ".git", ".gitnexus", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", ".venv", "node_modules", "__pycache__",
}
INDEX_IGNORED_FILES = {
    "signal_history.json", "scoring_weights.json", "titanium_v12.log",
}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GITNEXUS_GLOBAL_CLI = (
    Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    / "npm" / "node_modules" / "gitnexus" / "dist" / "cli" / "index.js"
)
GITNEXUS_PROJECT_CLI = (
    PROJECT_ROOT / "gitnexus" / "runtime" / "node_modules"
    / "gitnexus" / "dist" / "cli" / "index.js"
)
GITNEXUS_OPENSSL_BIN = Path(
    os.environ.get("GITNEXUS_OPENSSL_BIN", r"C:\Program Files\Git\mingw64\bin")
)
JARVIS_SOURCE = Path(r"C:\Program Files\JARVIS")
RUNTIME_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Titanium" / "gitnexus"
JARVIS_MIRROR = RUNTIME_ROOT / "jarvis-runtime"
WATCHER_PID_PATH = RUNTIME_ROOT / "watcher.pid"
SERVER_PID_PATH = RUNTIME_ROOT / "server-4747.pid"
SHUTDOWN_TOKEN_PATH = RUNTIME_ROOT / "server-4747.shutdown-token"
PROJECT_SNAPSHOT_PATH = RUNTIME_ROOT / "titanium-v12.snapshot.json"
JARVIS_SNAPSHOT_PATH = RUNTIME_ROOT / "jarvis-runtime.snapshot.json"


@dataclass(frozen=True)
class MirrorReport:
    copied: int
    unchanged: int
    removed: int
    rejected: int
    manifest_path: Path


@dataclass
class ChangeDebouncer:
    debounce_seconds: float = 5.0
    max_delay_seconds: float = 15.0
    first_change: float | None = None
    last_change: float | None = None

    def note_change(self, now: float) -> None:
        if self.first_change is None:
            self.first_change = now
        self.last_change = now

    def ready(self, now: float) -> bool:
        if self.first_change is None or self.last_change is None:
            return False
        return (
            now - self.last_change >= self.debounce_seconds
            or now - self.first_change >= self.max_delay_seconds
        )

    def reset(self) -> None:
        self.first_change = None
        self.last_change = None


def is_index_relevant(relative_path: PurePath) -> bool:
    """Filtre les changements qui justifient une nouvelle analyse du code."""
    parts = tuple(part.lower() for part in relative_path.parts)
    name = relative_path.name.lower()
    if not parts or any(part in INDEX_IGNORED_ROOTS for part in parts[:-1]):
        return False
    if name in INDEX_IGNORED_FILES or relative_path.suffix.lower() == ".log":
        return False
    if parts[0] == "data" and relative_path.suffix.lower() == ".json":
        return False
    return relative_path.suffix.lower() in INDEX_SUFFIXES or name in ALLOWED_EXACT_FILES


def opportunity_scan_running(
    url: str = OPPORTUNITY_STATUS_URL,
    timeout: float = 5.0,
) -> bool:
    """True si le scan lourd tourne ou si son état ne peut être vérifié."""
    try:
        with request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("running") is not False
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return True


def spawn_low_priority(
    argv: Sequence[str],
    cwd: Path,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.Popen:
    """Lance un processus GitNexus sans fenêtre et en priorité basse sous Windows."""
    env = os.environ.copy()
    if os.name == "nt" and GITNEXUS_OPENSSL_BIN.is_dir():
        openssl_bin = str(GITNEXUS_OPENSSL_BIN)
        path_entries = env.get("PATH", "").split(os.pathsep)
        if os.path.normcase(openssl_bin) not in {
            os.path.normcase(entry) for entry in path_entries if entry
        }:
            env["PATH"] = os.pathsep.join([openssl_bin, *path_entries])
    if env_overrides:
        env.update(env_overrides)
    return subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS,
    )


def _normalized_path(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def plan_session_actions(
    *,
    server_healthy: bool,
    registered_paths: set[str],
    project_root: Path,
    mirror_root: Path,
    project_stale: bool,
    mirror_changed: bool,
    no_watch: bool,
) -> tuple[str, ...]:
    """Calcule les actions minimales d'une session sans effet de bord."""
    registered = {_normalized_path(path) for path in registered_paths}
    actions: list[str] = []
    if project_stale or _normalized_path(project_root) not in registered:
        actions.append("analyze_project")
    if mirror_changed or _normalized_path(mirror_root) not in registered:
        actions.append("analyze_mirror")
    if not server_healthy:
        actions.append("serve")
    if not no_watch:
        actions.append("watch")
    return tuple(actions)


def source_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Empreinte légère des seules sources qui doivent rafraîchir l'index."""
    root = root.resolve()
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = PurePath(path.relative_to(root).as_posix())
        if not is_index_relevant(relative):
            continue
        stat = path.stat()
        snapshot[relative.as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def jarvis_source_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Empreinte JARVIS limitée à la même whitelist que le miroir assaini."""
    root = root.resolve()
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = PurePath(path.relative_to(root).as_posix())
        if not is_jarvis_source_allowed(relative):
            continue
        stat = path.stat()
        snapshot[relative.as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _http_json(url: str, timeout: float = 3.0) -> Any:
    with request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict[str, Any], timeout: float = 3.0) -> Any:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    http_request = request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(http_request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def gitnexus_server_healthy(base_url: str = GITNEXUS_BASE_URL) -> bool:
    try:
        payload = _http_json(f"{base_url}/api/health")
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return False
        repositories = _http_json(f"{base_url}/api/repos")
        if isinstance(repositories, dict):
            repositories = repositories.get(
                "repos", repositories.get("repositories", repositories.get("value", []))
            )
        if not isinstance(repositories, list) or not repositories:
            return True
        names = [
            item.get("name") for item in repositories
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        if not names:
            return True
        repo_name = "titanium-v12" if "titanium-v12" in names else names[0]
        probe = _http_post_json(
            f"{base_url}/api/query",
            {
                "cypher": "MATCH (n:File) RETURN COUNT(n) AS count",
                "repo": repo_name,
            },
        )
        return isinstance(probe, dict) and isinstance(probe.get("result"), list)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def gitnexus_repositories(base_url: str = GITNEXUS_BASE_URL) -> list[dict]:
    try:
        payload = _http_json(f"{base_url}/api/repos")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            repos = payload.get(
                "repos", payload.get("repositories", payload.get("value", []))
            )
            if isinstance(repos, list):
                return [item for item in repos if isinstance(item, dict)]
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []


def _run_quiet(argv: Sequence[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=check,
        creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS,
    )


def ensure_mirror_git_repository(mirror: Path) -> bool:
    """Initialise/snapshotte le dépôt technique local. Retourne True si commit créé."""
    mirror.mkdir(parents=True, exist_ok=True)
    if not (mirror / ".git").exists():
        _run_quiet(["git", "init"], mirror)
    _run_quiet(["git", "add", "-A"], mirror)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(mirror),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS,
    ).returncode != 0
    if not changed:
        return False
    _run_quiet([
        "git", "-c", "user.name=Titanium GitNexus",
        "-c", "user.email=gitnexus@localhost", "commit", "-m",
        "chore: refresh sanitized JARVIS analysis mirror",
    ], mirror)
    return True


def _snapshot_digest(snapshot: dict[str, tuple[int, int]]) -> str:
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _saved_snapshot_digest(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("digest")
        return value if isinstance(value, str) else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def gitnexus_index_stale(repo: Path) -> bool:
    """Fail closed when GitNexus metadata does not match the repository HEAD."""
    try:
        metadata = json.loads((repo / ".gitnexus" / "meta.json").read_text(encoding="utf-8"))
        indexed_commit = metadata.get("lastCommit")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    return result.returncode != 0 or not isinstance(indexed_commit, str) or (
        result.stdout.strip() != indexed_commit
    )


def _save_snapshot(path: Path, snapshot: dict[str, tuple[int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "digest": _snapshot_digest(snapshot),
        "files": len(snapshot),
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def gitnexus_command(*args: str) -> list[str]:
    """Commande épinglée au CLI global, avec repli sur le lanceur du dépôt."""
    if GITNEXUS_GLOBAL_CLI.is_file():
        return ["node", str(GITNEXUS_GLOBAL_CLI), *args]
    if GITNEXUS_PROJECT_CLI.is_file():
        return ["node", str(GITNEXUS_PROJECT_CLI), *args]
    runner = PROJECT_ROOT / ".gitnexus" / "run.cjs"
    if not runner.exists():
        raise FileNotFoundError(f"Lanceur GitNexus absent: {runner}")
    return ["node", str(runner), *args]


def gitnexus_serve_command() -> list[str]:
    """Serveur local explicite : IPv4 loopback uniquement, port stable 4747."""
    return gitnexus_command(
        "serve", "--port", str(GITNEXUS_PORT), "--host", GITNEXUS_HOST,
    )


def gitnexus_version() -> str:
    """Version du premier CLI GitNexus disponible, sans lancer de processus."""
    for cli in (GITNEXUS_GLOBAL_CLI, GITNEXUS_PROJECT_CLI):
        package_json = cli.parents[2] / "package.json"
        try:
            value = json.loads(package_json.read_text(encoding="utf-8")).get("version")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, str):
            return value
    return "unknown"


def gitnexus_fts_server_safe(version: str | None = None) -> bool:
    """Autorise FTS serveur seulement sur la première version Windows validée."""
    candidate = version or gitnexus_version()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?", candidate)
    if not match:
        return False
    core = tuple(int(part) for part in match.group(1, 2, 3))
    if core != (1, 6, 10):
        return core > (1, 6, 10)
    rc = match.group(4)
    return rc is None or int(rc) >= 50


def gitnexus_shutdown_token() -> str:
    """Return the local per-install token used only for graceful loopback shutdown."""
    try:
        current = SHUTDOWN_TOKEN_PATH.read_text(encoding="ascii").strip()
        if len(current) == 64 and all(char in "0123456789abcdef" for char in current):
            return current
    except OSError:
        pass
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    SHUTDOWN_TOKEN_PATH.write_text(token, encoding="ascii")
    return token


def _analyze_command(repo: Path, *, force: bool = False) -> list[str]:
    args = ["analyze", "--pdg"]
    if force:
        args.extend(("--force", "--index-only"))
    return gitnexus_command(*args)


def analyze_repository(repo: Path) -> int:
    if opportunity_scan_running():
        return 75  # EX_TEMPFAIL : le watcher réessaiera sans concurrencer MT5.
    server_was_running = managed_gitnexus_server_running() or gitnexus_server_healthy()
    if server_was_running and not stop_gitnexus_server():
        return 69  # EX_UNAVAILABLE: never replace a database still held open.
    started = time.monotonic()
    code = 70
    try:
        process = spawn_low_priority(_analyze_command(repo), repo)
        code = process.wait()
        if code != 0:
            recovery = spawn_low_priority(_analyze_command(repo, force=True), repo)
            code = recovery.wait()
    finally:
        if server_was_running:
            start_gitnexus_server()
            if not _wait_for_server():
                code = 69
    print(json.dumps({
        "event": "gitnexus_analyze",
        "repo": str(repo),
        "return_code": code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "priority": "below_normal",
    }), flush=True)
    return code


def start_gitnexus_server() -> subprocess.Popen | None:
    if gitnexus_server_healthy():
        return None
    # LadybugDB FTS 0.18.1 crashes the Windows server process on the first
    # BM25 request even though index construction succeeds. Keep structural
    # graph/Cypher serving fail-safe; analyze_repository still loads FTS so
    # the index remains portable once the native upstream defect is fixed.
    env_overrides = {
        "GITNEXUS_MCP_READ_ONLY": "1",
        "GITNEXUS_SHUTDOWN_TOKEN": gitnexus_shutdown_token(),
    }
    if not gitnexus_fts_server_safe():
        env_overrides["GITNEXUS_LBUG_EXTENSION_INSTALL"] = "never"
        process = spawn_low_priority(
            gitnexus_serve_command(),
            PROJECT_ROOT,
            env_overrides=env_overrides,
        )
    else:
        process = spawn_low_priority(
            gitnexus_serve_command(), PROJECT_ROOT, env_overrides=env_overrides,
        )
    pid = getattr(process, "pid", None)
    if isinstance(pid, int) and pid > 0:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        SERVER_PID_PATH.write_text(str(pid), encoding="ascii")
    return process


def _wait_for_server(timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gitnexus_server_healthy():
            return True
        time.sleep(0.5)
    return False


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        handle = open_process(process_query_limited_information, False, pid)
        if not handle:
            return False
        close_handle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def managed_gitnexus_server_running() -> bool:
    try:
        pid = int(SERVER_PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    return _pid_is_running(pid)


def _is_managed_gitnexus_serve_command(command_line: str) -> bool:
    """Accept only the exact GitNexus CLI/port/host launched by this runtime."""
    tokens = [quoted or bare for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', command_line)]
    if len(tokens) < 3 or Path(tokens[0]).name.lower() not in {"node", "node.exe"}:
        return False
    candidate = os.path.normcase(os.path.normpath(tokens[1]))
    allowed_clis = {
        os.path.normcase(os.path.normpath(str(GITNEXUS_GLOBAL_CLI))),
        os.path.normcase(os.path.normpath(str(GITNEXUS_PROJECT_CLI))),
    }
    if candidate not in allowed_clis or tokens[2].lower() != "serve":
        return False
    lowered = [token.lower() for token in tokens[3:]]
    return (
        any(lowered[index:index + 2] == ["--port", str(GITNEXUS_PORT)] for index in range(len(lowered) - 1))
        and any(lowered[index:index + 2] == ["--host", GITNEXUS_HOST] for index in range(len(lowered) - 1))
    )


def _managed_process_command_line(pid: int) -> str | None:
    if os.name == "nt":
        script = (
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; "
            "if($p){[Console]::Out.Write($p.CommandLine)}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    try:
        return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _terminate_managed_gitnexus_server(pid: int) -> bool:
    command_line = _managed_process_command_line(pid)
    if not command_line or not _is_managed_gitnexus_serve_command(command_line):
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def quarantine_empty_orphan_wal(repo: Path) -> bool:
    """Preserve and detach only LadybugDB's known 42-byte closed WAL state."""
    database_dir = repo / ".gitnexus"
    wal = database_dir / "lbug.wal"
    shadow = database_dir / "lbug.shadow"
    if not wal.exists():
        return True
    try:
        if wal.stat().st_size != 42:
            return False
        suffix = time.time_ns()
        if shadow.exists():
            shadow.replace(database_dir / f"lbug.shadow.closed.{suffix}")
        quarantine = database_dir / f"lbug.wal.missing-shadow.{suffix}"
        wal.replace(quarantine)
        return True
    except OSError:
        return False


def stop_gitnexus_server(timeout: float = 30.0) -> bool:
    """Stop only the port-4747 process previously recorded by this runtime."""
    try:
        pid = int(SERVER_PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    if not _pid_is_running(pid):
        SERVER_PID_PATH.unlink(missing_ok=True)
        return True
    shutdown_request = request.Request(
        f"{GITNEXUS_BASE_URL}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-GitNexus-Shutdown-Token": gitnexus_shutdown_token(),
        },
    )
    route_missing = False
    try:
        with request.urlopen(shutdown_request, timeout=3.0) as response:
            if response.status not in (200, 202):
                return False
    except error.HTTPError as exc:
        route_missing = exc.code in (404, 405)
        if not route_missing:
            return False
    except OSError:
        # The Node process can close the loopback connection immediately after
        # accepting shutdown. Treat that transport race as provisional only:
        # success still requires the exact recorded PID to disappear below.
        pass
    if route_missing and not _terminate_managed_gitnexus_server(pid):
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _pid_is_running(pid):
        time.sleep(0.1)
    if _pid_is_running(pid):
        return False
    SERVER_PID_PATH.unlink(missing_ok=True)
    return all(quarantine_empty_orphan_wal(repo) for repo in (PROJECT_ROOT, JARVIS_MIRROR))


def _watcher_running() -> bool:
    try:
        return _pid_is_running(int(WATCHER_PID_PATH.read_text(encoding="ascii").strip()))
    except (OSError, ValueError):
        return False


def start_watcher() -> subprocess.Popen | None:
    if _watcher_running():
        return None
    return spawn_low_priority([
        sys.executable, str(Path(__file__).resolve()), "watch",
    ], PROJECT_ROOT)


def _sync_and_snapshot_jarvis() -> tuple[MirrorReport, dict[str, tuple[int, int]]]:
    report = sync_jarvis_mirror(JARVIS_SOURCE, JARVIS_MIRROR)
    ensure_mirror_git_repository(JARVIS_MIRROR)
    return report, jarvis_source_snapshot(JARVIS_SOURCE)


def run_session(*, open_browser: bool, no_watch: bool) -> dict:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    report, jarvis_snapshot = _sync_and_snapshot_jarvis()
    project_snapshot = source_snapshot(PROJECT_ROOT)

    healthy = gitnexus_server_healthy()
    if not healthy:
        start_gitnexus_server()
        healthy = _wait_for_server()
    repositories = gitnexus_repositories() if healthy else []
    registered = {
        str(item.get("path")) for item in repositories
        if isinstance(item, dict) and item.get("path")
    }
    project_stale = (
        _saved_snapshot_digest(PROJECT_SNAPSHOT_PATH) != _snapshot_digest(project_snapshot)
        or gitnexus_index_stale(PROJECT_ROOT)
    )
    mirror_changed = (
        report.copied > 0 or report.removed > 0
        or _saved_snapshot_digest(JARVIS_SNAPSHOT_PATH) != _snapshot_digest(jarvis_snapshot)
        or gitnexus_index_stale(JARVIS_MIRROR)
    )
    actions = plan_session_actions(
        server_healthy=healthy,
        registered_paths=registered,
        project_root=PROJECT_ROOT,
        mirror_root=JARVIS_MIRROR,
        project_stale=project_stale,
        mirror_changed=mirror_changed,
        no_watch=no_watch,
    )
    completed: list[str] = []
    deferred: list[str] = []
    if "analyze_project" in actions:
        code = analyze_repository(PROJECT_ROOT)
        (completed if code == 0 else deferred).append("analyze_project")
        if code == 0:
            _save_snapshot(PROJECT_SNAPSHOT_PATH, project_snapshot)
    if "analyze_mirror" in actions:
        code = analyze_repository(JARVIS_MIRROR)
        (completed if code == 0 else deferred).append("analyze_mirror")
        if code == 0:
            _save_snapshot(JARVIS_SNAPSHOT_PATH, jarvis_snapshot)
    if "watch" in actions:
        start_watcher()
        completed.append("watch")
    if open_browser:
        webbrowser.open(f"{GITNEXUS_BASE_URL}/")
        completed.append("browser")
    return {
        "healthy": gitnexus_server_healthy(),
        "actions": list(actions),
        "completed": completed,
        "deferred": deferred,
        "mirror": {
            "copied": report.copied,
            "unchanged": report.unchanged,
            "removed": report.removed,
            "rejected": report.rejected,
        },
    }


def run_watcher(poll_seconds: float = 2.0) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    if _watcher_running():
        return
    WATCHER_PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    project_before = source_snapshot(PROJECT_ROOT)
    jarvis_before = jarvis_source_snapshot(JARVIS_SOURCE)
    project_debounce = ChangeDebouncer()
    jarvis_debounce = ChangeDebouncer()
    try:
        while True:
            now = time.monotonic()
            project_after = source_snapshot(PROJECT_ROOT)
            jarvis_after = jarvis_source_snapshot(JARVIS_SOURCE)
            if project_after != project_before:
                project_debounce.note_change(now)
                project_before = project_after
            if jarvis_after != jarvis_before:
                jarvis_debounce.note_change(now)
                jarvis_before = jarvis_after
            if not opportunity_scan_running():
                if project_debounce.ready(now):
                    if analyze_repository(PROJECT_ROOT) == 0:
                        _save_snapshot(PROJECT_SNAPSHOT_PATH, project_before)
                        project_debounce.reset()
                if jarvis_debounce.ready(now):
                    sync_jarvis_mirror(JARVIS_SOURCE, JARVIS_MIRROR)
                    ensure_mirror_git_repository(JARVIS_MIRROR)
                    if analyze_repository(JARVIS_MIRROR) == 0:
                        _save_snapshot(JARVIS_SNAPSHOT_PATH, jarvis_before)
                        jarvis_debounce.reset()
            time.sleep(poll_seconds)
    finally:
        try:
            if WATCHER_PID_PATH.read_text(encoding="ascii").strip() == str(os.getpid()):
                WATCHER_PID_PATH.unlink()
        except OSError:
            pass


def status_payload() -> dict:
    repositories = gitnexus_repositories()
    return {
        "healthy": gitnexus_server_healthy(),
        "url": GITNEXUS_BASE_URL,
        "repositories": repositories,
        "watcher_running": _watcher_running(),
        "opportunity_scan_running": opportunity_scan_running(),
        "project_snapshot_saved": PROJECT_SNAPSHOT_PATH.exists(),
        "jarvis_snapshot_saved": JARVIS_SNAPSHOT_PATH.exists(),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runtime commun GitNexus Titanium")
    sub = parser.add_subparsers(dest="command", required=True)
    session = sub.add_parser("session")
    session.add_argument("--open-browser", action="store_true")
    session.add_argument("--no-watch", action="store_true")
    sub.add_parser("watch")
    sub.add_parser("sync-jarvis")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "session":
        print(json.dumps(run_session(open_browser=args.open_browser, no_watch=args.no_watch), ensure_ascii=False))
        return 0
    if args.command == "watch":
        run_watcher()
        return 0
    if args.command == "sync-jarvis":
        report, _ = _sync_and_snapshot_jarvis()
        print(json.dumps(report.__dict__, default=str, ensure_ascii=False))
        return 0
    payload = status_payload()
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0


def _rejection_reason(relative_path: PurePath) -> str | None:
    parts = tuple(part.lower() for part in relative_path.parts)
    name = relative_path.name.lower()
    suffix = relative_path.suffix.lower()
    if any(part in DENIED_DIRS for part in parts[:-1]):
        return "denied_directory"
    if name in DENIED_NAMES:
        return "denied_name"
    if any(marker in name for marker in (".bak-", ".bak.")):
        return "backup"
    if suffix in DENIED_SUFFIXES:
        return "denied_suffix"
    if any(marker in name for marker in SENSITIVE_NAME_PARTS):
        return "sensitive_name"
    if name not in ALLOWED_EXACT_FILES and suffix not in ALLOWED_SUFFIXES:
        return "extension_not_allowed"
    return None


def is_jarvis_source_allowed(relative_path: PurePath) -> bool:
    """Retourne True uniquement pour une source JARVIS explicitement indexable."""
    return _rejection_reason(relative_path) is None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _destination_under(root: Path, relative_path: PurePath) -> Path:
    resolved_root = root.resolve()
    destination = (resolved_root / Path(*relative_path.parts)).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Chemin miroir hors racine: {relative_path}") from exc
    return destination


def _read_previous_manifest(path: Path) -> dict:
    if not path.exists():
        return {"included": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"included": []}
    except (OSError, json.JSONDecodeError):
        return {"included": []}


def sync_jarvis_mirror(source: Path, destination: Path) -> MirrorReport:
    """Synchronise une vue d'analyse JARVIS assainie et produit un manifeste.

    Les liens symboliques sont rejetés. Les suppressions sont limitées aux chemins
    précédemment déclarés dans le manifeste du miroir.
    """
    source_root = source.resolve(strict=True)
    destination_root = destination.resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    manifest_path = destination_root / MANIFEST_NAME
    previous = _read_previous_manifest(manifest_path)

    included: list[dict] = []
    rejected: list[dict] = []
    copied = 0
    unchanged = 0

    for path in sorted(source_root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        relative = PurePath(path.relative_to(source_root).as_posix())
        if path.is_symlink():
            rejected.append({"path": relative.as_posix(), "reason": "symlink"})
            continue
        reason = _rejection_reason(relative)
        if reason:
            rejected.append({"path": relative.as_posix(), "reason": reason})
            continue

        source_hash = _sha256(path)
        target = _destination_under(destination_root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _sha256(target) == source_hash:
            unchanged += 1
        else:
            copy2(path, target)
            copied += 1
        included.append({
            "path": relative.as_posix(),
            "sha256": source_hash,
            "size": path.stat().st_size,
        })

    current_paths = {item["path"] for item in included}
    previous_paths = {
        item.get("path") for item in previous.get("included", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    removed = 0
    for stale in sorted(previous_paths - current_paths):
        target = _destination_under(destination_root, PurePath(stale))
        if target.is_file():
            target.unlink()
            removed += 1

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "mirror_root": str(destination_root),
        "included": included,
        "rejected": rejected,
    }
    stable_keys = ("schema_version", "source_root", "mirror_root", "included", "rejected")
    manifest_changed = any(previous.get(key) != manifest.get(key) for key in stable_keys)
    if manifest_changed or not manifest_path.exists():
        temp_path = manifest_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(manifest_path)
    return MirrorReport(
        copied=copied,
        unchanged=unchanged,
        removed=removed,
        rejected=len(rejected),
        manifest_path=manifest_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
