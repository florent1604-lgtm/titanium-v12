"""Starlette, SSE and WebSocket transports for the local CollabHub."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
import json
from typing import AsyncIterator

from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .contracts import MessageDraft, StoredMessage
from .mcp import create_collab_mcp
from .secret_gate import scan_text
from .session import SessionAuthority, SessionError
from .session_routes import create_session_routes
from .store import CollabStore, IdempotencyConflict
from .task_routes import create_task_routes
from .windows_attestation import (
    KeyProtectionError,
    WindowsAttestation,
    current_user_sid,
)


class MessageInput(BaseModel):
    principal: str
    target: str
    kind: str
    content: str
    idempotency_key: str
    task_id: str | None = None
    correlation_id: str | None = None
    in_reply_to: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    classification: str = "INTERNAL"


class AckInput(BaseModel):
    global_offset: int = Field(ge=0)


class PresenceInput(BaseModel):
    principal: str
    state: str
    detail: str = ""


def _message_dict(message: StoredMessage) -> dict:
    value = asdict(message)
    value["evidence_refs"] = list(message.evidence_refs)
    return value


def _query_int(request: Request, name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{name} invalide") from exc
    if not low <= value <= high:
        raise HTTPException(status_code=400, detail=f"{name} hors limites")
    return value


def _query_bool(request: Request, name: str, default: bool) -> bool:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise HTTPException(status_code=400, detail=f"{name} invalide")


async def _json_body(request: Request, model):
    try:
        return model.model_validate(await request.json())
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="payload invalide") from exc


async def require_florent_session(
    request: Request,
    principal: str,
    session_authority: SessionAuthority,
    expected_windows_sid: str,
) -> JSONResponse | None:
    if principal != "florent":
        return None
    token = request.headers.get("X-Collab-Session", "")
    try:
        session = await asyncio.to_thread(session_authority.verify, token)
    except SessionError:
        return JSONResponse(
            {"reason_code": "FLORENT_SESSION_REQUIRED"}, status_code=401
        )
    if not hmac.compare_digest(session.windows_sid, expected_windows_sid):
        return JSONResponse(
            {"reason_code": "FLORENT_SESSION_REQUIRED"}, status_code=401
        )
    return None


class RealtimeBroker:
    """Process-local fanout; SQLite remains the replayable source of truth."""

    def __init__(self, *, max_clients: int = 32, queue_size: int = 128):
        self.max_clients = max_clients
        self.queue_size = queue_size
        self._queues: set[asyncio.Queue] = set()

    @property
    def active_count(self) -> int:
        return len(self._queues)

    async def subscribe(self) -> asyncio.Queue:
        if len(self._queues) >= self.max_clients:
            raise RuntimeError("REALTIME_CAPACITY_REACHED")
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    async def publish(self, message: dict) -> None:
        for queue in tuple(self._queues):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self._queues.discard(queue)
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass


def create_app(
    store: CollabStore,
    *,
    attestation: WindowsAttestation | None = None,
    session_authority: SessionAuthority | None = None,
    expected_windows_sid: str | None = None,
) -> Starlette:
    broker = RealtimeBroker()
    collab_mcp = create_collab_mcp(store, broker)
    mcp_app = collab_mcp.streamable_http_app()
    active_attestation = attestation or WindowsAttestation()
    active_sessions = session_authority or SessionAuthority()
    active_windows_sid = (
        current_user_sid() if expected_windows_sid is None else expected_windows_sid
    )
    if not isinstance(active_windows_sid, str) or not active_windows_sid.strip():
        raise KeyProtectionError("CURRENT_USER_SID_UNAVAILABLE")

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with collab_mcp.session_manager.run():
            yield

    async def health(_request: Request) -> JSONResponse:
        result = await asyncio.to_thread(store.health)
        result["ws_clients"] = broker.active_count
        result["transport"] = "LOOPBACK_C1_SHADOW"
        return JSONResponse(result)

    async def publish_message(request: Request) -> JSONResponse:
        body = await _json_body(request, MessageInput)
        session_rejection = await require_florent_session(
            request, body.principal, active_sessions, active_windows_sid
        )
        if session_rejection is not None:
            return session_rejection
        if scan_text(body.content):
            return JSONResponse({"reason_code": "SECRET_REJECTED"}, status_code=400)
        draft = MessageDraft(
            principal=body.principal,
            target=body.target,
            kind=body.kind,
            content=body.content,
            idempotency_key=body.idempotency_key,
            task_id=body.task_id,
            correlation_id=body.correlation_id,
            in_reply_to=body.in_reply_to,
            evidence_refs=tuple(body.evidence_refs),
            classification=body.classification,
        )
        try:
            receipt = await asyncio.to_thread(store.publish, draft)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not receipt.duplicate:
            rows = await asyncio.to_thread(
                store.read, after_offset=receipt.global_offset - 1, limit=1
            )
            if rows:
                await broker.publish(_message_dict(rows[0]))
        return JSONResponse(asdict(receipt), status_code=201)

    async def read_messages(request: Request) -> JSONResponse:
        has_after = "after_offset" in request.query_params
        has_before = "before_offset" in request.query_params
        if has_after and has_before:
            raise HTTPException(
                status_code=400,
                detail="before_offset et after_offset sont mutuellement exclusifs",
            )
        limit = _query_int(request, "limit", 100, 1, 1000)
        if has_before:
            before_offset = _query_int(
                request, "before_offset", 0, 0, 2**63 - 1
            )
            rows = await asyncio.to_thread(
                store.read_before, before_offset=before_offset, limit=limit
            )
        else:
            after_offset = _query_int(request, "after_offset", 0, 0, 2**63 - 1)
            rows = await asyncio.to_thread(
                store.read, after_offset=after_offset, limit=limit
            )
        return JSONResponse({"messages": [_message_dict(row) for row in rows]})

    async def acknowledge(request: Request) -> JSONResponse:
        consumer_id = request.path_params["consumer_id"]
        body = await _json_body(request, AckInput)
        try:
            await asyncio.to_thread(
                store.ack, consumer_id=consumer_id, global_offset=body.global_offset
            )
            offset = await asyncio.to_thread(store.consumer_offset, consumer_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"consumer_id": consumer_id, "global_offset": offset})

    async def set_presence(request: Request) -> JSONResponse:
        body = await _json_body(request, PresenceInput)
        try:
            await asyncio.to_thread(
                store.set_presence,
                principal=body.principal,
                state=body.state,
                detail=body.detail,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"principal": body.principal, "state": body.state})

    async def list_presence(_request: Request) -> JSONResponse:
        rows = await asyncio.to_thread(store.list_presence)
        return JSONResponse({"presence": list(rows)})

    async def stream_messages(request: Request) -> StreamingResponse:
        after_offset = _query_int(request, "after_offset", 0, 0, 2**63 - 1)
        follow = _query_bool(request, "follow", True)

        async def generate() -> AsyncIterator[str]:
            queue: asyncio.Queue | None = None
            last_offset = after_offset
            try:
                if follow:
                    queue = await broker.subscribe()
                rows = await asyncio.to_thread(
                    store.read, after_offset=after_offset, limit=1000
                )
                for row in rows:
                    last_offset = row.global_offset
                    payload = json.dumps(
                        _message_dict(row), ensure_ascii=False, separators=(",", ":")
                    )
                    yield f"id: {row.global_offset}\nevent: message\ndata: {payload}\n\n"
                if not follow:
                    return
                while queue is not None:
                    item = await queue.get()
                    if item is None:
                        return
                    if int(item["global_offset"]) <= last_offset:
                        continue
                    last_offset = int(item["global_offset"])
                    payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {last_offset}\nevent: message\ndata: {payload}\n\n"
            finally:
                if queue is not None:
                    broker.unsubscribe(queue)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def websocket_messages(websocket: WebSocket) -> None:
        try:
            after_offset = int(websocket.query_params.get("after_offset", "0"))
        except ValueError:
            await websocket.close(code=1008, reason="after_offset invalide")
            return
        try:
            queue = await broker.subscribe()
        except RuntimeError:
            await websocket.close(code=1013, reason="realtime capacity reached")
            return
        await websocket.accept()
        last_offset = max(0, after_offset)
        try:
            rows = await asyncio.to_thread(store.read, after_offset=last_offset, limit=1000)
            for row in rows:
                last_offset = row.global_offset
                await websocket.send_json(_message_dict(row))
            while True:
                queue_task = asyncio.create_task(queue.get())
                receive_task = asyncio.create_task(websocket.receive())
                done, pending = await asyncio.wait(
                    {queue_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if receive_task in done:
                    event = receive_task.result()
                    if event.get("type") == "websocket.disconnect":
                        break
                if queue_task in done:
                    item = queue_task.result()
                    if item is None:
                        await websocket.close(code=1013, reason="client too slow")
                        break
                    if int(item["global_offset"]) > last_offset:
                        last_offset = int(item["global_offset"])
                        await websocket.send_json(item)
        except WebSocketDisconnect:
            pass
        finally:
            broker.unsubscribe(queue)

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/v1/messages", publish_message, methods=["POST"]),
        Route("/v1/messages", read_messages, methods=["GET"]),
        Route("/v1/consumers/{consumer_id:str}/ack", acknowledge, methods=["POST"]),
        Route("/v1/presence", set_presence, methods=["POST"]),
        Route("/v1/presence", list_presence, methods=["GET"]),
        Route("/v1/stream", stream_messages, methods=["GET"]),
        WebSocketRoute("/v1/ws", websocket_messages),
    ]
    routes.extend(
        create_session_routes(active_attestation, active_sessions, active_windows_sid)
    )
    routes.extend(create_task_routes(store, active_sessions, active_windows_sid))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.collab_store = store
    app.state.collab_broker = broker
    app.state.collab_mcp = collab_mcp
    app.state.collab_attestation = active_attestation
    app.state.collab_sessions = active_sessions
    app.state.collab_windows_sid = active_windows_sid
    app.router.routes.extend(mcp_app.routes)
    return app
