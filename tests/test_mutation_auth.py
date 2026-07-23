"""Static regression guard for the fail-closed mutation route inventory.

The test deliberately uses only the Python AST: importing the full FastAPI app
would start configuration/data providers and is unnecessary for this security
property.
"""
from __future__ import annotations

import ast
from pathlib import Path


EXPECTED = {
    "api/forex_routes.py": {"/scan", "/reset"},
    "api/swing_routes.py": {"/scan", "/reset"},
    "api/latency_routes.py": {"/run"},
    "api/opportunity_routes.py": {"/run", "/ack"},
    "api/fundamentals_routes.py": {"/reload", "/enable", "/disable"},
    "api/context_routes.py": {"/regen"},
    "api/cockpit_routes.py": {"/journal/{trade_hash}/approve"},
    "api/titan_routes.py": {"/titan/speak", "/titan/command", "/titan/clear-history"},
    "api/api_server.py": {"/api/optim/run"},
    "api/services_routes.py": {
        "/titan/start", "/titan/stop",
        "/ollama/start", "/ollama/stop",
        "/gitnexus/start", "/gitnexus/stop",
        "/github/push",
    },
}


def _protected_post_paths(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute) or decorator.func.attr != "post":
                continue
            if not any(keyword.arg == "dependencies" for keyword in decorator.keywords):
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                paths.add(str(decorator.args[0].value))
    return paths


def test_sensitive_post_routes_have_explicit_auth_dependency():
    for path, expected in EXPECTED.items():
        assert expected <= _protected_post_paths(path), path
