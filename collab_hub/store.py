"""SQLite/WAL authoritative store for CollabHub messages and cursors."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    CLASSIFICATIONS,
    KINDS,
    PRESENCE_STATES,
    PRINCIPALS,
    MessageDraft,
    PublishReceipt,
    StoredMessage,
)
from .task_store import TaskStore


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "collab_hub" / "collab-v1.sqlite3"
SCHEMA_VERSION = 1
_TOPIC_RE = re.compile(r"^topic:[a-z0-9][a-z0-9._-]{0,63}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


class CollabStoreError(Exception):
    """Base error for durable collaboration storage."""


class IdempotencyConflict(CollabStoreError):
    """Raised when a key is reused for a different immutable message."""


_DDL = """
CREATE TABLE IF NOT EXISTS messages (
  global_offset INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  created_at TEXT NOT NULL,
  principal TEXT NOT NULL,
  target TEXT NOT NULL,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  task_id TEXT,
  correlation_id TEXT,
  in_reply_to TEXT,
  evidence_refs_json TEXT NOT NULL CHECK(json_valid(evidence_refs_json)),
  classification TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  UNIQUE(principal, idempotency_key)
);
CREATE INDEX IF NOT EXISTS messages_target_offset ON messages(target, global_offset);
CREATE INDEX IF NOT EXISTS messages_task_offset ON messages(task_id, global_offset);
CREATE TABLE IF NOT EXISTS consumer_offsets (
  consumer_id TEXT PRIMARY KEY,
  global_offset INTEGER NOT NULL CHECK(global_offset >= 0),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS presence (
  principal TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  detail TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(draft: MessageDraft) -> str:
    immutable = {
        "schema_version": SCHEMA_VERSION,
        "principal": draft.principal,
        "target": draft.target,
        "kind": draft.kind,
        "content": draft.content,
        "idempotency_key": draft.idempotency_key,
        "task_id": draft.task_id,
        "correlation_id": draft.correlation_id,
        "in_reply_to": draft.in_reply_to,
        "evidence_refs": list(draft.evidence_refs),
        "classification": draft.classification,
    }
    return hashlib.sha256(_canonical(immutable).encode("utf-8")).hexdigest()


def _validate_opaque(name: str, value: str | None) -> None:
    if value is not None and not _OPAQUE_RE.fullmatch(value):
        raise ValueError(f"{name} invalide")


def _validate_draft(draft: MessageDraft) -> None:
    if draft.principal not in PRINCIPALS:
        raise ValueError("principal inconnu")
    if draft.target not in PRINCIPALS and not _TOPIC_RE.fullmatch(draft.target):
        raise ValueError("target invalide")
    if draft.kind not in KINDS:
        raise ValueError("kind invalide")
    if draft.classification not in CLASSIFICATIONS:
        raise ValueError("classification invalide")
    if not isinstance(draft.content, str) or not (1 <= len(draft.content.strip()) <= 32_000):
        raise ValueError("content doit contenir 1..32000 caractères")
    _validate_opaque("idempotency_key", draft.idempotency_key)
    _validate_opaque("task_id", draft.task_id)
    _validate_opaque("correlation_id", draft.correlation_id)
    _validate_opaque("in_reply_to", draft.in_reply_to)
    if len(draft.evidence_refs) > 32:
        raise ValueError("evidence_refs limité à 32")
    if any(not isinstance(ref, str) or not (1 <= len(ref) <= 512) for ref in draft.evidence_refs):
        raise ValueError("evidence_ref invalide")
    _canonical(list(draft.evidence_refs))


class CollabStore:
    """Thread-safe durable message store; it has no dispatch or trading dependency."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB,
        *,
        task_clock: Callable[[], datetime] | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cx = sqlite3.connect(
            str(self.db_path), check_same_thread=False, isolation_level=None
        )
        self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.execute("PRAGMA synchronous=FULL")
        self._cx.execute("PRAGMA foreign_keys=ON")
        self._cx.execute("PRAGMA busy_timeout=5000")
        self._cx.executescript(_DDL)
        self.tasks = TaskStore(self._cx, self._lock, clock=task_clock)

    def publish(self, draft: MessageDraft) -> PublishReceipt:
        _validate_draft(draft)
        digest = _digest(draft)
        evidence = _canonical(list(draft.evidence_refs))
        with self._lock:
            cx = self._cx
            cx.execute("BEGIN IMMEDIATE")
            try:
                duplicate = cx.execute(
                    "SELECT message_id,global_offset,content_sha256 FROM messages "
                    "WHERE principal=? AND idempotency_key=?",
                    (draft.principal, draft.idempotency_key),
                ).fetchone()
                if duplicate:
                    cx.execute("ROLLBACK")
                    if duplicate[2] != digest:
                        raise IdempotencyConflict(
                            f"idempotency_key réutilisée avec un contenu différent: "
                            f"{draft.idempotency_key}"
                        )
                    return PublishReceipt(duplicate[0], int(duplicate[1]), True, duplicate[2])

                message_id = str(uuid.uuid4())
                created_at = _utc_now()
                cx.execute(
                    "INSERT INTO messages (message_id,schema_version,created_at,principal,"
                    "target,kind,content,idempotency_key,task_id,correlation_id,in_reply_to,"
                    "evidence_refs_json,classification,content_sha256) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        message_id,
                        SCHEMA_VERSION,
                        created_at,
                        draft.principal,
                        draft.target,
                        draft.kind,
                        draft.content,
                        draft.idempotency_key,
                        draft.task_id,
                        draft.correlation_id,
                        draft.in_reply_to,
                        evidence,
                        draft.classification,
                        digest,
                    ),
                )
                offset = int(
                    cx.execute(
                        "SELECT global_offset FROM messages WHERE message_id=?", (message_id,)
                    ).fetchone()[0]
                )
                cx.execute("COMMIT")
                return PublishReceipt(message_id, offset, False, digest)
            except Exception:
                try:
                    cx.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def read(self, *, after_offset: int = 0, limit: int = 100) -> tuple[StoredMessage, ...]:
        bounded = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._cx.execute(
                "SELECT global_offset,message_id,schema_version,created_at,principal,target,"
                "kind,content,idempotency_key,task_id,correlation_id,in_reply_to,"
                "evidence_refs_json,classification,content_sha256 FROM messages "
                "WHERE global_offset>? ORDER BY global_offset ASC LIMIT ?",
                (max(0, int(after_offset)), bounded),
            ).fetchall()
        return tuple(
            StoredMessage(
                global_offset=int(row[0]),
                message_id=row[1],
                schema_version=int(row[2]),
                created_at=row[3],
                principal=row[4],
                target=row[5],
                kind=row[6],
                content=row[7],
                idempotency_key=row[8],
                task_id=row[9],
                correlation_id=row[10],
                in_reply_to=row[11],
                evidence_refs=tuple(json.loads(row[12])),
                classification=row[13],
                content_sha256=row[14],
            )
            for row in rows
        )

    def read_before(
        self, *, before_offset: int, limit: int = 100
    ) -> tuple[StoredMessage, ...]:
        bounded = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._cx.execute(
                "SELECT global_offset,message_id,schema_version,created_at,principal,target,"
                "kind,content,idempotency_key,task_id,correlation_id,in_reply_to,"
                "evidence_refs_json,classification,content_sha256 FROM messages "
                "WHERE global_offset < ? ORDER BY global_offset DESC LIMIT ?",
                (int(before_offset), bounded),
            ).fetchall()
        rows.reverse()
        return tuple(
            StoredMessage(
                global_offset=int(row[0]),
                message_id=row[1],
                schema_version=int(row[2]),
                created_at=row[3],
                principal=row[4],
                target=row[5],
                kind=row[6],
                content=row[7],
                idempotency_key=row[8],
                task_id=row[9],
                correlation_id=row[10],
                in_reply_to=row[11],
                evidence_refs=tuple(json.loads(row[12])),
                classification=row[13],
                content_sha256=row[14],
            )
            for row in rows
        )

    def ack(self, *, consumer_id: str, global_offset: int) -> None:
        _validate_opaque("consumer_id", consumer_id)
        offset = max(0, int(global_offset))
        with self._lock:
            self._cx.execute(
                "INSERT INTO consumer_offsets (consumer_id,global_offset,updated_at) "
                "VALUES (?,?,?) ON CONFLICT(consumer_id) DO UPDATE SET "
                "global_offset=max(consumer_offsets.global_offset,excluded.global_offset),"
                "updated_at=excluded.updated_at",
                (consumer_id, offset, _utc_now()),
            )

    def consumer_offset(self, consumer_id: str) -> int:
        _validate_opaque("consumer_id", consumer_id)
        with self._lock:
            row = self._cx.execute(
                "SELECT global_offset FROM consumer_offsets WHERE consumer_id=?", (consumer_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def set_presence(self, *, principal: str, state: str, detail: str = "") -> None:
        if principal not in PRINCIPALS:
            raise ValueError("principal inconnu")
        if state not in PRESENCE_STATES:
            raise ValueError("state invalide")
        if not isinstance(detail, str) or len(detail) > 1000:
            raise ValueError("detail invalide")
        with self._lock:
            self._cx.execute(
                "INSERT INTO presence (principal,state,detail,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(principal) DO UPDATE SET state=excluded.state,"
                "detail=excluded.detail,updated_at=excluded.updated_at",
                (principal, state, detail, _utc_now()),
            )

    def list_presence(self) -> tuple[dict[str, str], ...]:
        with self._lock:
            rows = self._cx.execute(
                "SELECT principal,state,detail,updated_at FROM presence ORDER BY principal"
            ).fetchall()
        return tuple(
            {"principal": row[0], "state": row[1], "detail": row[2], "updated_at": row[3]}
            for row in rows
        )

    def health(self) -> dict[str, Any]:
        with self._lock:
            count, head = self._cx.execute(
                "SELECT count(*),coalesce(max(global_offset),0) FROM messages"
            ).fetchone()
            mode = self._cx.execute("PRAGMA journal_mode").fetchone()[0]
            consumers = self._cx.execute("SELECT count(*) FROM consumer_offsets").fetchone()[0]
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "journal_mode": str(mode).upper(),
            "n_messages": int(count),
            "head_offset": int(head),
            "n_consumers": int(consumers),
        }

    def close(self) -> None:
        with self._lock:
            self._cx.close()
