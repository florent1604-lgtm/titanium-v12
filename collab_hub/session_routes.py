"""HTTP routes for the local Windows-attested Florent session."""

from __future__ import annotations

import asyncio
import hmac
import json

from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .session import SessionAuthority, SessionCapacityExceeded
from .windows_attestation import AttestationError, WindowsAttestation


_ATTESTATION_REJECTED = "WINDOWS_ATTESTATION_REJECTED"
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class WindowsProofInput(BaseModel):
    sid: str = Field(min_length=1, max_length=256)
    nonce: str = Field(min_length=1, max_length=256)
    proof: str = Field(min_length=1, max_length=256)


def create_session_routes(
    attestation: WindowsAttestation,
    session_authority: SessionAuthority,
    expected_windows_sid: str,
) -> list[Route]:
    """Build session routes around process-local, injectable authorities."""

    async def challenge(_request: Request) -> JSONResponse:
        try:
            issued = await asyncio.to_thread(attestation.challenge_details)
        except AttestationError:
            return JSONResponse(
                {"reason_code": "WINDOWS_ATTESTATION_UNAVAILABLE"},
                status_code=503,
                headers=_NO_STORE_HEADERS,
            )
        return JSONResponse(
            {"nonce": issued.nonce, "expires_at": issued.expires_at},
            status_code=201,
            headers=_NO_STORE_HEADERS,
        )

    async def windows_session(request: Request) -> JSONResponse:
        try:
            body = WindowsProofInput.model_validate(await request.json())
            await asyncio.to_thread(
                attestation.verify, body.sid, body.nonce, body.proof
            )
            if not hmac.compare_digest(body.sid, expected_windows_sid):
                raise ValueError("unexpected Windows SID")
        except (
            AttestationError,
            json.JSONDecodeError,
            TypeError,
            ValidationError,
            ValueError,
        ):
            return JSONResponse(
                {"reason_code": _ATTESTATION_REJECTED},
                status_code=401,
                headers=_NO_STORE_HEADERS,
            )

        try:
            session = await asyncio.to_thread(session_authority.issue, body.sid)
        except SessionCapacityExceeded:
            return JSONResponse(
                {"reason_code": "SESSION_CAPACITY_EXCEEDED"},
                status_code=503,
                headers=_NO_STORE_HEADERS,
            )
        return JSONResponse(
            {
                "token": session.token,
                "session_id": session.session_id,
                "expires_at": session.expires_at.isoformat(),
            },
            status_code=201,
            headers=_NO_STORE_HEADERS,
        )

    return [
        Route("/v1/session/challenge", challenge, methods=["POST"]),
        Route("/v1/session/windows", windows_session, methods=["POST"]),
    ]
