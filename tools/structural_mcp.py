"""Fournisseur MCP structurel local, sans memoire, confine a Titanium v12."""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_SUFFIXES = {
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".scss", ".md", ".mdx", ".mq5", ".mqh",
}
DENIED_DIRS = {
    ".git", ".gitnexus", ".pyembed", ".pytest_cache", "__pycache__",
    "node_modules", "venv", ".venv", "data", "logs", "backups",
}
DENIED_NAMES = {
    ".env", "auth.json", "secrets.json", "credentials.json",
    "jarvis_conversations.json", "jarvis_memoire.json",
}
SENSITIVE_NAME_PARTS = {"credential", "secret", "token", "password", "apikey", "api_key"}
MAX_FILE_BYTES = 2_000_000


class ScopeViolation(ValueError):
    """Le chemin demande sort du perimetre structurel autorise."""


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in DENIED_NAMES or any(part in lowered for part in SENSITIVE_NAME_PARTS)


def resolve_scoped_path(root: Path, requested: str | os.PathLike[str]) -> Path:
    """Resout un chemin en refusant toute sortie, symlink inclus, et tout secret."""
    root = Path(root).resolve()
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ScopeViolation("path outside Titanium structural scope") from exc
    for part in relative.parts:
        if part.lower() in DENIED_DIRS or _is_sensitive_name(part):
            raise ScopeViolation(f"path denied by structural policy: {part}")
    return candidate


def _read_code_file(root: Path, requested: str) -> tuple[Path, str]:
    file_path = resolve_scoped_path(root, requested)
    if not file_path.is_file():
        raise FileNotFoundError(requested)
    if file_path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ScopeViolation(f"unsupported structural file type: {file_path.suffix}")
    if file_path.stat().st_size > MAX_FILE_BYTES:
        raise ScopeViolation("file exceeds structural read limit")
    return file_path, file_path.read_text(encoding="utf-8", errors="replace")


def _python_signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        result = f"{prefix} {node.name}({ast.unparse(node.args)})"
        if node.returns is not None:
            result += f" -> {ast.unparse(node.returns)}"
        return result
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(base) for base in node.bases)
        return f"class {node.name}" + (f"({bases})" if bases else "")
    return type(node).__name__


def _python_outline(content: str) -> list[str]:
    tree = ast.parse(content)
    lines: list[str] = []

    def visit(nodes: Iterable[ast.stmt], depth: int = 0) -> None:
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.append(f"{'  ' * depth}- L{node.lineno}: {_python_signature(node)}")
                if isinstance(node, ast.ClassDef):
                    visit(node.body, depth + 1)

    visit(tree.body)
    return lines


def _markdown_outline(content: str) -> list[str]:
    return [
        f"- L{number}: {line.strip()}"
        for number, line in enumerate(content.splitlines(), 1)
        if re.match(r"^#{1,6}\s+", line)
    ]


GENERIC_SYMBOL = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:class|interface|function|def)\s+"
    r"[A-Za-z_$][\w$]*.*$"
)


def _generic_outline(content: str) -> list[str]:
    return [
        f"- L{number}: {line.strip()}"
        for number, line in enumerate(content.splitlines(), 1)
        if GENERIC_SYMBOL.match(line)
    ]


def smart_outline(root: Path, file_path: str) -> str:
    path, content = _read_code_file(root, file_path)
    suffix = path.suffix.lower()
    if suffix in {".py", ".pyw"}:
        symbols = _python_outline(content)
    elif suffix in {".md", ".mdx"}:
        symbols = _markdown_outline(content)
    else:
        symbols = _generic_outline(content)
    relative = path.relative_to(Path(root).resolve()).as_posix()
    body = "\n".join(symbols) if symbols else "(no structural symbol found)"
    return f"# Outline: {relative}\n{body}"


def _find_python_symbol(tree: ast.AST, qualified_name: str) -> ast.AST | None:
    wanted = qualified_name.split(".")

    def descend(nodes: Iterable[ast.stmt], parts: list[str]) -> ast.AST | None:
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == parts[0]:
                    if len(parts) == 1:
                        return node
                    if hasattr(node, "body"):
                        return descend(node.body, parts[1:])
        return None

    return descend(getattr(tree, "body", []), wanted)


def smart_unfold(root: Path, file_path: str, symbol_name: str) -> str:
    path, content = _read_code_file(root, file_path)
    if path.suffix.lower() not in {".py", ".pyw"}:
        raise ScopeViolation("safe unfold currently supports Python symbols only")
    tree = ast.parse(content)
    node = _find_python_symbol(tree, symbol_name)
    if node is None or not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        raise LookupError(f"symbol not found: {symbol_name}")
    start = min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])])
    lines = content.splitlines()
    snippet = "\n".join(lines[start - 1 : node.end_lineno])
    relative = path.relative_to(Path(root).resolve()).as_posix()
    return f"# {relative}:{start} — {symbol_name}\n{snippet}"


def _iter_safe_files(scope: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(scope):
        dirs[:] = [
            name for name in dirs
            if name.lower() not in DENIED_DIRS and not _is_sensitive_name(name)
        ]
        for name in files:
            path = Path(current) / name
            if (
                path.suffix.lower() in ALLOWED_SUFFIXES
                and not _is_sensitive_name(name)
                and path.stat().st_size <= MAX_FILE_BYTES
            ):
                yield path


def smart_search(
    root: Path,
    query: str,
    *,
    path: str = ".",
    max_results: int = 20,
    file_pattern: str | None = None,
) -> str:
    scope = resolve_scoped_path(root, path)
    if not scope.is_dir():
        raise NotADirectoryError(path)
    needle = query.casefold().strip()
    if not needle:
        raise ValueError("query is required")
    limit = max(1, min(int(max_results), 50))
    root = Path(root).resolve()
    matches: list[str] = []
    for file_path in _iter_safe_files(scope):
        try:
            safe_file = resolve_scoped_path(root, file_path)
        except ScopeViolation:
            continue
        relative = safe_file.relative_to(root).as_posix()
        if file_pattern and file_pattern.casefold() not in relative.casefold():
            continue
        content = safe_file.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(content.splitlines(), 1):
            if needle in line.casefold():
                matches.append(f"- {relative}:{number} — {line.strip()[:240]}")
                if len(matches) >= limit:
                    return f"# Smart search: {query}\n" + "\n".join(matches)
    body = "\n".join(matches) if matches else "(no match)"
    return f"# Smart search: {query}\n{body}"


TOOLS = [
    {
        "name": "smart_search",
        "description": "Search code structure inside Titanium v12 only; secrets and internal indexes are excluded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 20},
                "file_pattern": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "smart_outline",
        "description": "Return a structural outline for one safe project code file.",
        "inputSchema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "smart_unfold",
        "description": "Return one Python symbol body from a safe Titanium v12 file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "symbol_name": {"type": "string"},
            },
            "required": ["file_path", "symbol_name"],
            "additionalProperties": False,
        },
    },
]


def _tool_call(root: Path, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "smart_search":
            text = smart_search(root, **arguments)
        elif name == "smart_outline":
            text = smart_outline(root, **arguments)
        elif name == "smart_unfold":
            text = smart_unfold(root, **arguments)
        else:
            raise LookupError(f"unknown tool: {name}")
        return {"content": [{"type": "text", "text": text}]}
    except Exception as exc:
        return {
            "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
            "isError": True,
        }


def handle_request(root: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    if "id" not in request:
        return None
    request_id = request["id"]
    method = request.get("method")
    if method == "initialize":
        protocol = request.get("params", {}).get("protocolVersion", "2024-11-05")
        result = {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "titanium-structural", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params", {})
        result = _tool_call(root, params.get("name", ""), params.get("arguments", {}))
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    root = resolve_scoped_path(
        PROJECT_ROOT,
        os.environ.get("TITANIUM_STRUCTURE_ROOT", str(PROJECT_ROOT)),
    )
    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
            response = handle_request(root, request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stderr.write(f"titanium-structural: {type(exc).__name__}: {exc}\n")
            sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
