from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import structural_mcp


def test_resolve_scoped_path_rejects_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(structural_mcp.ScopeViolation):
        structural_mcp.resolve_scoped_path(root, "../secret.txt")


def test_resolve_scoped_path_rejects_sensitive_project_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(structural_mcp.ScopeViolation):
        structural_mcp.resolve_scoped_path(root, ".env")


def test_python_outline_and_unfold_return_only_requested_structure(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = root / "sample.py"
    root.mkdir()
    source.write_text(
        "class Engine:\n"
        "    def decide(self, price: float) -> bool:\n"
        "        return price > 1\n\n"
        "def helper(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    outline = structural_mcp.smart_outline(root, "sample.py")
    unfolded = structural_mcp.smart_unfold(root, "sample.py", "Engine.decide")

    assert "class Engine" in outline
    assert "decide(self, price: float) -> bool" in outline
    assert "def helper(value: int) -> int" in outline
    assert "return price > 1" in unfolded
    assert "return value + 1" not in unfolded


def test_smart_search_ignores_denied_directories(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "core").mkdir(parents=True)
    (root / ".gitnexus").mkdir()
    (root / "core" / "engine.py").write_text(
        "def consensus_engine():\n    return 'visible'\n", encoding="utf-8"
    )
    (root / ".gitnexus" / "private.py").write_text(
        "def consensus_secret():\n    return 'hidden'\n", encoding="utf-8"
    )

    result = structural_mcp.smart_search(root, "consensus", path=".")

    assert "core/engine.py" in result
    assert "consensus_engine" in result
    assert "private.py" not in result
    assert "consensus_secret" not in result


def test_smart_search_does_not_follow_file_symlink_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked_secret():\n    return True\n", encoding="utf-8")
    link = root / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = structural_mcp.smart_search(root, "leaked_secret")

    assert "linked.py" not in result
    assert result.endswith("(no match)")


def test_smart_search_rechecks_each_candidate_against_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked_secret():\n    return True\n", encoding="utf-8")
    monkeypatch.setattr(structural_mcp, "_iter_safe_files", lambda _scope: [outside])

    result = structural_mcp.smart_search(root, "leaked_secret")

    assert "outside.py" not in result
    assert result.endswith("(no match)")


def test_mcp_tools_list_exposes_the_three_structural_tools(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    response = structural_mcp.handle_request(
        root,
        {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
    )

    assert response is not None
    payload = json.loads(json.dumps(response))
    assert payload["id"] == 7
    assert {item["name"] for item in payload["result"]["tools"]} == {
        "smart_search",
        "smart_outline",
        "smart_unfold",
    }
