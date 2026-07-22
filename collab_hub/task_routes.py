"""HTTP routes for CollabHub's durable, manually driven task workflow."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import hmac
import json

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .secret_gate import scan_text
from .session import SessionAuthority, SessionError
from .store import CollabStore
from .task_contracts import TASK_STATES, TaskDraft


class TaskInput(BaseModel):
    title: str
    owner: str
    priority: str


class TransitionInput(BaseModel):
    status: str


def _status_filter(request: Request) -> tuple[str, ...]:
    raw_values = request.query_params.getlist("status")
    if not raw_values:
        return TASK_STATES
    return tuple(
        status.strip()
        for raw in raw_values
        for status in raw.split(",")
        if status.strip()
    )


async def _authorized(
    request: Request,
    session_authority: SessionAuthority,
    expected_windows_sid: str,
) -> bool:
    token = request.headers.get("X-Collab-Session", "")
    try:
        session = await asyncio.to_thread(session_authority.verify, token)
    except SessionError:
        return False
    return hmac.compare_digest(session.windows_sid, expected_windows_sid)


def _session_required() -> JSONResponse:
    return JSONResponse(
        {"reason_code": "FLORENT_SESSION_REQUIRED"}, status_code=401
    )


def _task_error(exc: Exception, *, conflict: bool = False) -> JSONResponse:
    if isinstance(exc, KeyError):
        return JSONResponse({"reason_code": "TASK_NOT_FOUND"}, status_code=404)
    return JSONResponse(
        {"reason_code": "TASK_CONFLICT" if conflict else "TASK_REJECTED"},
        status_code=409 if conflict else 400,
    )


def create_task_routes(
    store: CollabStore,
    session_authority: SessionAuthority,
    expected_windows_sid: str,
) -> list[Route]:
    """Build task routes without adding any automatic execution mechanism."""

    async def list_tasks(request: Request) -> JSONResponse:
        if not await _authorized(request, session_authority, expected_windows_sid):
            return _session_required()
        try:
            rows = await asyncio.to_thread(
                store.tasks.list_tasks, statuses=_status_filter(request)
            )
        except ValueError as exc:
            return _task_error(exc)
        return JSONResponse({"tasks": [asdict(row) for row in rows]})

    async def create_task(request: Request) -> JSONResponse:
        if not await _authorized(request, session_authority, expected_windows_sid):
            return _session_required()
        try:
            body = TaskInput.model_validate(await request.json())
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError):
            return JSONResponse({"reason_code": "PAYLOAD_INVALID"}, status_code=422)
        if scan_text(body.title):
            return JSONResponse({"reason_code": "SECRET_REJECTED"}, status_code=400)
        try:
            row = await asyncio.to_thread(
                store.tasks.create_task,
                TaskDraft(title=body.title, owner=body.owner, priority=body.priority),
            )
        except (TypeError, ValueError) as exc:
            return _task_error(exc)
        return JSONResponse(asdict(row), status_code=201)

    async def transition(request: Request) -> JSONResponse:
        if not await _authorized(request, session_authority, expected_windows_sid):
            return _session_required()
        try:
            body = TransitionInput.model_validate(await request.json())
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError):
            return JSONResponse({"reason_code": "PAYLOAD_INVALID"}, status_code=422)
        try:
            row = await asyncio.to_thread(
                store.tasks.transition, request.path_params["task_id"], body.status
            )
        except (KeyError, ValueError) as exc:
            return _task_error(exc, conflict=isinstance(exc, ValueError))
        return JSONResponse(asdict(row))

    async def retry(request: Request) -> JSONResponse:
        if not await _authorized(request, session_authority, expected_windows_sid):
            return _session_required()
        try:
            row = await asyncio.to_thread(
                store.tasks.request_retry,
                request.path_params["task_id"],
                requested_by="florent",
            )
        except (KeyError, ValueError) as exc:
            return _task_error(exc, conflict=isinstance(exc, ValueError))
        return JSONResponse(asdict(row), status_code=201)

    async def list_failures(request: Request) -> JSONResponse:
        if not await _authorized(request, session_authority, expected_windows_sid):
            return _session_required()
        try:
            rows = await asyncio.to_thread(
                store.tasks.list_failed, statuses=_status_filter(request)
            )
        except ValueError as exc:
            return _task_error(exc)
        return JSONResponse({"failures": [asdict(row) for row in rows]})

    return [
        Route("/v1/tasks", list_tasks, methods=["GET"]),
        Route("/v1/tasks", create_task, methods=["POST"]),
        Route("/v1/tasks/{task_id:str}/transition", transition, methods=["POST"]),
        Route("/v1/tasks/{task_id:str}/retry", retry, methods=["POST"]),
        Route("/v1/failures", list_failures, methods=["GET"]),
    ]
