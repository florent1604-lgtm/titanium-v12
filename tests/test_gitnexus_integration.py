from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gitnexusignore_excludes_runtime_without_hiding_sources() -> None:
    content = (ROOT / ".gitnexusignore").read_text(encoding="utf-8")
    assert "data/*.json" in content
    assert "data/**/*.json" in content
    assert "*.log" in content
    assert ".env" in content
    assert ".env.*" in content
    assert "core/**" not in content
    assert "api/**" not in content
    assert "tests/**" not in content


def test_topology_manifest_is_local_paper_only_and_contains_all_participants() -> None:
    manifest = json.loads(
        (ROOT / "architecture/gitnexus/services.json").read_text(encoding="utf-8")
    )
    assert manifest["paper_only"] is True
    assert manifest["gitnexus"]["bind"] == "127.0.0.1"
    assert manifest["gitnexus"]["port"] == 4747
    names = {service["id"] for service in manifest["services"]}
    assert {"titanium", "titan", "jarvis", "hermes", "claude", "codex", "mt5"} <= names
    claude = manifest["gitnexus"]["clients"]["claude"]
    assert claude == {
        "identity": "claude",
        "transport": "http",
        "endpoint": "http://127.0.0.1:4747/api/mcp",
        "access": "advisory-read-only",
        "billing_guard": "subscription-only",
        "fallback": "ollama:qwen2.5:7b",
    }
    assert {
        "from": "gitnexus",
        "to": "claude",
        "data": "code-map",
        "mode": "advisory-read-only",
    } in manifest["boundaries"]
    assert "rename" not in json.dumps(claude).lower()
    assert "group_sync" not in json.dumps(claude).lower()


def test_session_script_enforces_low_priority_pause_and_opt_in_browser() -> None:
    script = (ROOT / "tools/gitnexus_session.ps1").read_text(encoding="utf-8")
    runtime = (ROOT / "tools/gitnexus_runtime.py").read_text(encoding="utf-8")
    assert "BELOW_NORMAL_PRIORITY_CLASS" in runtime
    assert "/opportunities/status" in runtime
    assert "OpenBrowser" in script
    assert "uv python find 3.11" in script
    assert "Python 3.11+ introuvable" in script
    assert '"serve"' in runtime
    assert "/api/health" in runtime
    assert "/api/repos" in runtime
    assert "--open-browser" not in (
        ROOT / ".vscode/tasks.json"
    ).read_text(encoding="utf-8")


def test_api_keeps_orbe_and_adds_read_only_nexus_route() -> None:
    path = ROOT / "api/api_server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    get_paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "get"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                get_paths.add(str(decorator.args[0].value))
    assert "/orbe" in get_paths
    assert "/nexus" in get_paths


def test_services_routes_use_current_gitnexus_contract_and_admin_mutations() -> None:
    content = (ROOT / "api/services_routes.py").read_text(encoding="utf-8")
    api_server = (ROOT / "api/api_server.py").read_text(encoding="utf-8")
    assert "4747" in content
    assert "from tools.gitnexus_runtime import (" in content
    assert "GITNEXUS_BASE_URL," in content
    assert "start_gitnexus_server," in content
    assert "stop_gitnexus_server," in content
    assert 'GITNEXUS_HOST = "127.0.0.1"' in (
        ROOT / "tools/gitnexus_runtime.py"
    ).read_text(encoding="utf-8")
    assert 'target = "http://localhost:4747/"' in api_server
    assert "/api/health" in content
    assert "/api/repos" in content
    assert '"serve"' in content
    assert "/api/graph/stats" not in content
    assert "dependencies=_ADMIN" in content
