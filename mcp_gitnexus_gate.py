"""Supervised MCP proxy for GitNexus native writes used by Hermes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Sequence
from uuid import uuid4

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send
import uvicorn

from tools.gitnexus_write_policy import (
    ALLOWED_REPO,
    ROOT,
    TTL_SECONDS,
    ExecutionLedger,
    GateRefused,
    WriteRequest,
    args_sha256,
    find_valid_approvals,
    fingerprint_files,
    load_trusted_public_keys,
    normalize_args,
    validate_repo_path,
)


GITNEXUS_MCP_BOOTSTRAP = ROOT / "tools" / "gitnexus_mcp_bootstrap.mjs"
GITNEXUS_DETECT_CHANGES_RUNNER = ROOT / "tools" / "gitnexus_detect_changes.mjs"
STREAM_PATH = ROOT / "collab" / "messages" / "stream.ndjson"
ACK_PATH = ROOT / "collab" / "messages" / "acks.ndjson"
LEDGER_PATH = ROOT / "collab" / "messages" / "gitnexus_write_executions.ndjson"
LOCK_PATH = ROOT / "collab" / "messages" / "gitnexus_write_gate.lock"
APPROVAL_KEYS_PATH = ROOT / "collab" / "governance" / "gitnexus_approver_keys.json"
CONTROLLED_TOOLS = frozenset({"rename", "group_sync"})
GATE_HOST = "127.0.0.1"
GATE_PORT = 4750
GATE_PATH = "/mcp"


def _json_from_text(text: str) -> dict[str, Any]:
    payload = text.split("\n--- Next:", 1)[0].lstrip()
    try:
        decoded, _ = json.JSONDecoder().raw_decode(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("DOWNSTREAM_INVALID_JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("DOWNSTREAM_INVALID_RESULT")
    return decoded


class GitNexusClient:
    """Bounded stdio client for the pinned local GitNexus runtime."""

    def __init__(
        self,
        cli_path: Path = GITNEXUS_MCP_BOOTSTRAP,
        root: Path = ROOT,
    ) -> None:
        self.cli_path = Path(cli_path)
        self.root = Path(root)

    def _parameters(self) -> StdioServerParameters:
        if not self.cli_path.is_file():
            raise RuntimeError("GITNEXUS_RUNTIME_MISSING")
        return StdioServerParameters(
            command="node",
            args=[str(self.cli_path), "mcp"],
            cwd=str(self.root),
            env={
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": str(self.root),
            },
        )

    async def list_tools(self) -> list[types.Tool]:
        with anyio.fail_after(30):
            async with stdio_client(self._parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return list((await session.list_tools()).tools)

    async def detect_changes(self) -> dict[str, Any]:
        """Run the read-only scan with file-backed native output handles."""
        if not GITNEXUS_DETECT_CHANGES_RUNNER.is_file():
            raise RuntimeError("GITNEXUS_RUNTIME_MISSING")
        env = os.environ.copy()
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": str(self.root),
            }
        )
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = await asyncio.create_subprocess_exec(
                "node",
                str(GITNEXUS_DETECT_CHANGES_RUNNER),
                cwd=str(self.root),
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=30)
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise RuntimeError("DETECT_CHANGES_CLI_TIMEOUT") from exc
            if process.returncode != 0:
                raise RuntimeError("DETECT_CHANGES_CLI_FAILED")
            stdout_file.seek(0)
            stdout = stdout_file.read()
        try:
            return _json_from_text(stdout.decode("utf-8"))
        except (RuntimeError, UnicodeDecodeError) as exc:
            raise RuntimeError("DETECT_CHANGES_CLI_INVALID_JSON") from exc

    async def call(
        self,
        name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        approved_write = name == "group_sync" or (
            name == "rename" and args.get("dry_run") is False
        )
        timeout = 120 if approved_write else 30
        with anyio.fail_after(timeout):
            async with stdio_client(self._parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        name,
                        arguments=args,
                        read_timeout_seconds=timedelta(seconds=timeout),
                    )
        if result.isError:
            raise RuntimeError("DOWNSTREAM_TOOL_ERROR")
        if isinstance(result.structuredContent, dict):
            return dict(result.structuredContent)
        text = "".join(
            block.text for block in result.content if isinstance(block, types.TextContent)
        )
        return _json_from_text(text)


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateRefused("BUS_CORRUPT") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_ndjson(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _request_message(request: WriteRequest, preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": request.request_id,
        "type": "gitnexus_write_request",
        "from": "hermes",
        "to": "claude_or_codex",
        "task": "GITNEXUS_WRITE",
        "ts_utc": request.created_ts.isoformat(),
        "expires_ts": request.expires_ts.isoformat(),
        "tool": request.tool,
        "args": request.args,
        "args_sha256": request.args_sha256,
        "impact_risk": request.impact_risk,
        "files": list(request.files),
        "file_fingerprint": request.file_fingerprint,
        "preview": preview,
        "content": "PENDING_APPROVAL",
        "body": "PENDING_APPROVAL",
    }


def _request_from_message(message: dict[str, Any]) -> WriteRequest:
    try:
        created = datetime.fromisoformat(str(message["ts_utc"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(message["expires_ts"]).replace("Z", "+00:00"))
        return WriteRequest(
            request_id=str(message["id"]),
            tool=message["tool"],
            args=dict(message["args"]),
            args_sha256=str(message["args_sha256"]),
            created_ts=created,
            expires_ts=expires,
            impact_risk=str(message["impact_risk"]),
            files=tuple(str(item) for item in message["files"]),
            file_fingerprint=str(message["file_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GateRefused("REQUEST_CORRUPT") from exc


class GitNexusGate:
    def __init__(
        self,
        downstream: Any,
        root: Path,
        stream_path: Path,
        ack_path: Path,
        ledger_path: Path,
        lock_path: Path,
        approval_keys_path: Path = APPROVAL_KEYS_PATH,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.downstream = downstream
        self.root = Path(root).resolve()
        self.stream_path = Path(stream_path)
        self.ack_path = Path(ack_path)
        self.approval_keys_path = Path(approval_keys_path)
        self.ledger = ExecutionLedger(Path(ledger_path), Path(lock_path))
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def list_tools(self) -> list[types.Tool]:
        exposed: list[types.Tool] = []
        for tool in await self.downstream.list_tools():
            if tool.name in CONTROLLED_TOOLS:
                schema = deepcopy(tool.inputSchema)
                properties = schema.setdefault("properties", {})
                properties["approval_id"] = {
                    "type": "string",
                    "description": (
                        "Single-use request id with Ed25519 signatures from a supervisor "
                        "and Florent"
                    ),
                }
                exposed.append(
                    tool.model_copy(
                        update={
                            "description": f"SUPERVISED WRITE — {tool.description or tool.name}",
                            "inputSchema": schema,
                            "annotations": types.ToolAnnotations(
                                readOnlyHint=False,
                                destructiveHint=True,
                                idempotentHint=False,
                                openWorldHint=False,
                            ),
                        }
                    )
                )
            elif tool.annotations is not None and tool.annotations.readOnlyHint is True:
                exposed.append(tool)
        return exposed

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "rename":
            return await self.rename(arguments)
        if name == "group_sync":
            return await self.group_sync(arguments)
        allowed = {
            tool.name
            for tool in await self.list_tools()
            if tool.annotations is not None and tool.annotations.readOnlyHint is True
        }
        if name not in allowed:
            return {"status": "REFUSED", "reason": "TOOL_NOT_ALLOWED"}
        try:
            return await self.downstream.call(name, arguments)
        except Exception:
            return {"status": "REFUSED", "reason": "DOWNSTREAM_ERROR"}

    def _new_request(
        self,
        tool: str,
        args: dict[str, Any],
        risk: str,
        files: Sequence[str],
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        created = self.now().astimezone(timezone.utc)
        request = WriteRequest(
            request_id=str(uuid4()),
            tool=tool,
            args=args,
            args_sha256=args_sha256(args),
            created_ts=created,
            expires_ts=created + timedelta(seconds=TTL_SECONDS),
            impact_risk=risk,
            files=tuple(files),
            file_fingerprint=fingerprint_files(files, root=self.root),
        )
        _append_ndjson(self.stream_path, _request_message(request, preview))
        return {
            "status": "PENDING_APPROVAL",
            "request_id": request.request_id,
            "expires_ts": request.expires_ts.isoformat(),
            "args_sha256": request.args_sha256,
            "impact_risk": request.impact_risk,
            "files": list(request.files),
            "file_fingerprint": request.file_fingerprint,
            "args": request.args,
            "preview": preview,
        }

    def _load_request(self, request_id: str, tool: str) -> WriteRequest:
        matches = [
            item
            for item in _load_ndjson(self.stream_path)
            if item.get("type") == "gitnexus_write_request" and item.get("id") == request_id
        ]
        if len(matches) != 1:
            raise GateRefused("REQUEST_NOT_FOUND")
        request = _request_from_message(matches[0])
        if request.tool != tool:
            raise GateRefused("APPROVAL_MISMATCH")
        return request

    def _validate_execution(
        self,
        request: WriteRequest,
        supplied_args: dict[str, Any],
    ) -> None:
        if args_sha256(supplied_args) != request.args_sha256:
            raise GateRefused("APPROVAL_MISMATCH")
        current_fingerprint = fingerprint_files(request.files, root=self.root)
        if current_fingerprint != request.file_fingerprint:
            raise GateRefused("TARGET_CHANGED")
        approvals = _load_ndjson(self.ack_path)
        trusted_public_keys = load_trusted_public_keys(self.approval_keys_path)
        find_valid_approvals(
            request,
            approvals,
            trusted_public_keys=trusted_public_keys,
            require_florent_all=True,
            now=self.now(),
        )

    async def _detect_changes(self) -> dict[str, Any]:
        detector = getattr(self.downstream, "detect_changes", None)
        if callable(detector):
            result = await detector()
        else:
            result = await self.downstream.call(
                "detect_changes",
                {"scope": "all", "repo": ALLOWED_REPO},
            )
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError("DETECT_CHANGES_FAILED")
        return result

    async def rename(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            supplied = dict(arguments)
            approval_id = supplied.pop("approval_id", None)
            supplied["dry_run"] = True
            normalized = normalize_args("rename", supplied)

            if approval_id is not None:
                request = self._load_request(str(approval_id), "rename")
                self._validate_execution(request, normalized)
                preflight = await self._detect_changes()
                self.ledger.consume_once(request.request_id)
                apply_args = dict(request.args)
                apply_args["dry_run"] = False
                result = await self.downstream.call(
                    "rename",
                    apply_args,
                )
                if result.get("status") != "success" or result.get("applied") is not True:
                    return {"status": "VERIFICATION_FAILED", "reason": "WRITE_NOT_APPLIED"}
                changes = await self._detect_changes()
                return {
                    "status": "APPLIED",
                    "request_id": request.request_id,
                    "result": result,
                    "preflight_detect_changes": preflight,
                    "detect_changes": changes,
                }

            preview = await self.downstream.call("rename", normalized)
            if (
                preview.get("status") != "success"
                or preview.get("applied") is not False
                or not isinstance(preview.get("changes"), list)
                or not preview["changes"]
            ):
                raise GateRefused("PREVIEW_INVALID")
            files: list[str] = []
            for change in preview["changes"]:
                if not isinstance(change, dict) or not isinstance(change.get("file_path"), str):
                    raise GateRefused("PREVIEW_INVALID")
                resolved = validate_repo_path(change["file_path"], root=self.root)
                files.append(resolved.relative_to(self.root).as_posix())
            target = normalized.get("symbol_name") or normalized.get("symbol_uid")
            impact_args: dict[str, Any] = {
                "target": target,
                "direction": "upstream",
                "repo": ALLOWED_REPO,
            }
            if normalized.get("symbol_uid"):
                impact_args["uid"] = normalized["symbol_uid"]
            impact = await self.downstream.call("impact", impact_args)
            risk = str(impact.get("risk", "UNKNOWN")).upper()
            if risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise GateRefused("IMPACT_INVALID")
            return self._new_request("rename", normalized, risk, files, preview)
        except GateRefused as exc:
            return {"status": "REFUSED", "reason": str(exc)}
        except Exception:
            return {"status": "VERIFICATION_FAILED", "reason": "DOWNSTREAM_ERROR"}

    async def _validated_group(self, name: str) -> dict[str, Any]:
        result = await self.downstream.call("group_list", {})
        groups = result.get("groups")
        if not isinstance(groups, list):
            raise GateRefused("GROUP_NOT_ALLOWED")
        matches = [item for item in groups if isinstance(item, dict) and item.get("name") == name]
        if len(matches) != 1:
            raise GateRefused("GROUP_NOT_ALLOWED")
        members = matches[0].get("members") or matches[0].get("repos")
        if not isinstance(members, list) or not members:
            raise GateRefused("GROUP_NOT_ALLOWED")
        for member in members:
            if not isinstance(member, dict) or not isinstance(member.get("path"), str):
                raise GateRefused("GROUP_NOT_ALLOWED")
            if Path(member["path"]).resolve() != self.root:
                raise GateRefused("GROUP_NOT_ALLOWED")
        return matches[0]

    async def group_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            supplied = dict(arguments)
            approval_id = supplied.pop("approval_id", None)
            normalized = normalize_args("group_sync", supplied)
            group = await self._validated_group(normalized["name"])
            fingerprint_target = self.root / ".gitnexus" / "meta.json"
            if not fingerprint_target.is_file():
                raise GateRefused("GROUP_NOT_ALLOWED")
            files = [fingerprint_target.relative_to(self.root).as_posix()]

            if approval_id is not None:
                request = self._load_request(str(approval_id), "group_sync")
                self._validate_execution(request, normalized)
                preflight = await self._detect_changes()
                self.ledger.consume_once(request.request_id)
                result = await self.downstream.call(
                    "group_sync",
                    dict(request.args),
                )
                changes = await self._detect_changes()
                return {
                    "status": "APPLIED",
                    "request_id": request.request_id,
                    "result": result,
                    "preflight_detect_changes": preflight,
                    "detect_changes": changes,
                }

            preview = {"group": group, "operation": "group_sync", "applied": False}
            return self._new_request("group_sync", normalized, "MEDIUM", files, preview)
        except GateRefused as exc:
            return {"status": "REFUSED", "reason": str(exc)}
        except Exception:
            return {"status": "VERIFICATION_FAILED", "reason": "DOWNSTREAM_ERROR"}


gate = GitNexusGate(
    downstream=GitNexusClient(),
    root=ROOT,
    stream_path=STREAM_PATH,
    ack_path=ACK_PATH,
    ledger_path=LEDGER_PATH,
    lock_path=LOCK_PATH,
    approval_keys_path=APPROVAL_KEYS_PATH,
)
server = Server("titanium-gitnexus-write-gate")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return await gate.list_tools()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    result = await gate.call_tool(name, arguments)
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def _serve() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


class _StreamableHTTPApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


def _serve_http() -> None:
    """Serve one supervised gate for every local client session."""
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
    )
    application = Starlette(
        routes=[Route(GATE_PATH, endpoint=_StreamableHTTPApp(manager))],
        lifespan=lambda _app: manager.run(),
    )
    uvicorn.run(application, host=GATE_HOST, port=GATE_PORT, log_level="warning")


if __name__ == "__main__":
    try:
        if "--stdio" in sys.argv:
            asyncio.run(_serve())
        else:
            _serve_http()
    except KeyboardInterrupt:
        sys.exit(0)
