"""Bounded local sessions for the native CollabHub host."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


class SessionError(Exception):
    """Base error for local session verification."""


class InvalidSession(SessionError):
    """Raised when a token does not identify an issued session."""


class SessionExpired(SessionError):
    """Raised when a token identifies an expired session."""


class SessionCapacityExceeded(SessionError):
    """Raised when all bounded session slots contain live sessions."""


@dataclass(frozen=True)
class LocalSession:
    session_id: str
    windows_sid: str
    expires_at: datetime
    token: str = field(repr=False)


@dataclass(frozen=True)
class _SessionRecord:
    session_id: str
    windows_sid: str
    expires_at: datetime
    token_digest: bytes


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class SessionAuthority:
    """Issue and verify short-lived sessions without retaining bearer tokens."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        ttl_seconds: int = 900,
        max_sessions: int = 1024,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        if not isinstance(max_sessions, int) or max_sessions <= 0:
            raise ValueError("max_sessions must be a positive integer")
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[bytes, _SessionRecord] = {}
        self._lock = threading.RLock()

    def _purge_expired(
        self, now: datetime, *, preserve_digest: bytes | None = None
    ) -> None:
        expired = [
            digest
            for digest, record in self._sessions.items()
            if digest != preserve_digest and now >= record.expires_at
        ]
        for digest in expired:
            del self._sessions[digest]

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def issue(self, windows_sid: str) -> LocalSession:
        if not isinstance(windows_sid, str) or not windows_sid.strip():
            raise ValueError("windows_sid must be non-empty")
        now = self._now()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        with self._lock:
            self._purge_expired(now)
            if len(self._sessions) >= self._max_sessions:
                raise SessionCapacityExceeded("SESSION_CAPACITY_EXCEEDED")
            while True:
                token = secrets.token_urlsafe(32)
                digest = _token_digest(token)
                if digest not in self._sessions:
                    break
            record = _SessionRecord(
                str(uuid.uuid4()), windows_sid, expires_at, digest
            )
            self._sessions[digest] = record
        return LocalSession(record.session_id, record.windows_sid, record.expires_at, token)

    def verify(self, token: str) -> LocalSession:
        now = self._now()
        presented = _token_digest(token) if isinstance(token, str) and token else None
        with self._lock:
            self._purge_expired(now, preserve_digest=presented)
            if presented is None:
                raise InvalidSession("SESSION_INVALID")
            record = self._sessions.get(presented)
            candidate = record.token_digest if record is not None else bytes(len(presented))
            if record is None or not hmac.compare_digest(presented, candidate):
                raise InvalidSession("SESSION_INVALID")
            if now >= record.expires_at:
                del self._sessions[presented]
                raise SessionExpired("SESSION_EXPIRED")
        return LocalSession(record.session_id, record.windows_sid, record.expires_at, token)

    @staticmethod
    def audit_view(session: LocalSession) -> dict[str, str]:
        """Return an explicit token-free representation suitable for audit logs."""

        return {
            "session_id": session.session_id,
            "windows_sid": session.windows_sid,
            "expires_at": session.expires_at.isoformat(),
        }
