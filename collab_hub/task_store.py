"""Append-first SQLite task and immutable attempt-failure ledger."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .contracts import PRINCIPALS
from .secret_gate import scan_text
from .task_contracts import (
    FAILURE_REASONS,
    TASK_PRIORITIES,
    TASK_SCHEMA_VERSION,
    TASK_STATES,
    AttemptFailure,
    TaskDraft,
    TaskRecord,
)


_OWNER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ATTEMPT_STATES = frozenset({"ACTIVE", "FAILED"})
_NEXT_STATE = dict(zip(TASK_STATES, TASK_STATES[1:]))

TASK_DDL = """
CREATE TABLE IF NOT EXISTS task_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  event_type TEXT NOT NULL,
  task_id TEXT NOT NULL,
  attempt_id TEXT,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  payload_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS task_events_task_sequence
  ON task_events(task_id, sequence);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  title TEXT NOT NULL,
  owner TEXT NOT NULL,
  priority TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN
    ('NOUVEAU','A_ANALYSER','CORRECTIF_EN_COURS','A_REVALIDER','CLOS')),
  current_attempt_id TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  last_event_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  FOREIGN KEY(last_event_id) REFERENCES task_events(event_id)
);
CREATE INDEX IF NOT EXISTS tasks_status_updated ON tasks(status, updated_at);
CREATE TABLE IF NOT EXISTS task_attempts (
  attempt_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  parent_attempt_id TEXT,
  requested_by TEXT NOT NULL,
  attempt_status TEXT NOT NULL CHECK(attempt_status IN ('ACTIVE','FAILED')),
  reason_code TEXT,
  evidence_ref TEXT,
  event_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  failed_at TEXT,
  payload_sha256 TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(task_id),
  FOREIGN KEY(parent_attempt_id) REFERENCES task_attempts(attempt_id),
  FOREIGN KEY(event_id) REFERENCES task_events(event_id),
  CHECK (
    (attempt_status = 'ACTIVE' AND reason_code IS NULL AND evidence_ref IS NULL
      AND failed_at IS NULL)
    OR
    (attempt_status = 'FAILED' AND reason_code IS NOT NULL AND evidence_ref IS NOT NULL
      AND failed_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS task_attempts_task_created
  ON task_attempts(task_id, created_at);
CREATE INDEX IF NOT EXISTS task_attempts_failed
  ON task_attempts(attempt_status, failed_at);
"""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_text(name: str, value: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} invalide")
    reasons = scan_text(value)
    if reasons:
        raise ValueError(f"{name} contient un secret: {','.join(reasons)}")
    return value.strip()


def _task_payload(
    *,
    task_id: str,
    title: str,
    owner: str,
    priority: str,
    status: str,
    attempt_id: str,
    requested_by: str,
) -> str:
    return _canonical(
        {
            "schema_version": TASK_SCHEMA_VERSION,
            "task_id": task_id,
            "title": title,
            "owner": owner,
            "priority": priority,
            "status": status,
            "attempt_id": attempt_id,
            "requested_by": requested_by,
        }
    )


class TaskStore:
    """Task projection sharing its parent's SQLite connection and lock."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: threading.RLock,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self._cx = connection
        self._lock = lock
        self._clock = clock or _utc_now
        with self._lock:
            self._cx.executescript(TASK_DDL)

    def _timestamp(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("task clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat()

    def _append_event(
        self,
        *,
        event_type: str,
        task_id: str,
        attempt_id: str | None,
        payload: dict[str, Any],
        created_at: str,
    ) -> tuple[str, str]:
        event_id = str(uuid.uuid4())
        payload_json = _canonical(payload)
        payload_sha256 = _sha256(payload_json)
        self._cx.execute(
            "INSERT INTO task_events "
            "(event_id,schema_version,event_type,task_id,attempt_id,created_at,"
            "payload_json,payload_sha256) VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                TASK_SCHEMA_VERSION,
                event_type,
                task_id,
                attempt_id,
                created_at,
                payload_json,
                payload_sha256,
            ),
        )
        return event_id, payload_sha256

    def _begin(self) -> None:
        self._cx.execute("BEGIN IMMEDIATE")

    def _rollback(self) -> None:
        try:
            self._cx.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def create_task(self, draft: TaskDraft) -> TaskRecord:
        if not isinstance(draft, TaskDraft):
            raise TypeError("draft doit être un TaskDraft")
        title = _validate_text("title", draft.title, maximum=200)
        if not isinstance(draft.owner, str) or not _OWNER_RE.fullmatch(draft.owner):
            raise ValueError("owner invalide")
        if draft.priority not in TASK_PRIORITIES:
            raise ValueError("priority invalide")

        task_id = str(uuid.uuid4())
        attempt_id = str(uuid.uuid4())
        created_at = self._timestamp()
        requested_by = draft.owner
        event_payload = {
            "task_id": task_id,
            "title": title,
            "owner": draft.owner,
            "priority": draft.priority,
            "status": TASK_STATES[0],
            "attempt_id": attempt_id,
            "requested_by": requested_by,
        }
        task_payload = _task_payload(
            task_id=task_id,
            title=title,
            owner=draft.owner,
            priority=draft.priority,
            status=TASK_STATES[0],
            attempt_id=attempt_id,
            requested_by=requested_by,
        )
        attempt_payload = _canonical(
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "parent_attempt_id": None,
                "requested_by": requested_by,
                "attempt_status": "ACTIVE",
            }
        )

        with self._lock:
            self._begin()
            try:
                event_id, _ = self._append_event(
                    event_type="task.created.v1",
                    task_id=task_id,
                    attempt_id=attempt_id,
                    payload=event_payload,
                    created_at=created_at,
                )
                self._cx.execute(
                    "INSERT INTO tasks "
                    "(task_id,schema_version,title,owner,priority,status,current_attempt_id,"
                    "requested_by,last_event_id,created_at,updated_at,payload_sha256) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        task_id,
                        TASK_SCHEMA_VERSION,
                        title,
                        draft.owner,
                        draft.priority,
                        TASK_STATES[0],
                        attempt_id,
                        requested_by,
                        event_id,
                        created_at,
                        created_at,
                        _sha256(task_payload),
                    ),
                )
                self._cx.execute(
                    "INSERT INTO task_attempts "
                    "(attempt_id,task_id,parent_attempt_id,requested_by,attempt_status,"
                    "reason_code,evidence_ref,event_id,created_at,failed_at,payload_sha256) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        attempt_id,
                        task_id,
                        None,
                        requested_by,
                        "ACTIVE",
                        None,
                        None,
                        event_id,
                        created_at,
                        None,
                        _sha256(attempt_payload),
                    ),
                )
                self._cx.execute("COMMIT")
            except Exception:
                self._rollback()
                raise
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            row = self._cx.execute(
                "SELECT task_id,title,owner,priority,status,current_attempt_id,"
                "requested_by,last_event_id,created_at,updated_at,payload_sha256 "
                "FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"task inconnue: {task_id}")
        return TaskRecord(
            task_id=row[0],
            title=row[1],
            owner=row[2],
            priority=row[3],
            status=row[4],
            attempt_id=row[5],
            requested_by=row[6],
            event_id=row[7],
            created_at=row[8],
            updated_at=row[9],
            payload_sha256=row[10],
        )

    def list_tasks(self, *, statuses: tuple[str, ...] = TASK_STATES) -> tuple[TaskRecord, ...]:
        selected = tuple(statuses)
        if any(status not in TASK_STATES for status in selected):
            raise ValueError("status invalide")
        if not selected:
            return ()
        placeholders = ",".join("?" for _ in selected)
        with self._lock:
            rows = self._cx.execute(
                "SELECT task_id,title,owner,priority,status,current_attempt_id,"
                "requested_by,last_event_id,created_at,updated_at,payload_sha256 "
                f"FROM tasks WHERE status IN ({placeholders}) ORDER BY created_at,task_id",
                selected,
            ).fetchall()
        return tuple(
            TaskRecord(
                task_id=row[0],
                title=row[1],
                owner=row[2],
                priority=row[3],
                status=row[4],
                attempt_id=row[5],
                requested_by=row[6],
                event_id=row[7],
                created_at=row[8],
                updated_at=row[9],
                payload_sha256=row[10],
            )
            for row in rows
        )

    def transition(self, task_id: str, new_status: str) -> TaskRecord:
        if new_status not in TASK_STATES:
            raise ValueError("transition vers un status inconnu")
        with self._lock:
            self._begin()
            try:
                row = self._cx.execute(
                    "SELECT title,owner,priority,status,current_attempt_id,requested_by "
                    "FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"task inconnue: {task_id}")
                expected = _NEXT_STATE.get(row[3])
                if new_status != expected:
                    raise ValueError(f"transition interdite: {row[3]} -> {new_status}")
                changed_at = self._timestamp()
                event_id, _ = self._append_event(
                    event_type="task.state_changed.v1",
                    task_id=task_id,
                    attempt_id=row[4],
                    payload={
                        "task_id": task_id,
                        "attempt_id": row[4],
                        "previous_status": row[3],
                        "status": new_status,
                    },
                    created_at=changed_at,
                )
                task_payload = _task_payload(
                    task_id=task_id,
                    title=row[0],
                    owner=row[1],
                    priority=row[2],
                    status=new_status,
                    attempt_id=row[4],
                    requested_by=row[5],
                )
                self._cx.execute(
                    "UPDATE tasks SET status=?,last_event_id=?,updated_at=?,payload_sha256=? "
                    "WHERE task_id=?",
                    (new_status, event_id, changed_at, _sha256(task_payload), task_id),
                )
                self._cx.execute("COMMIT")
            except Exception:
                self._rollback()
                raise
        return self.get_task(task_id)

    def record_failure(
        self, task_id: str, reason_code: str, evidence_ref: str
    ) -> AttemptFailure:
        if reason_code not in FAILURE_REASONS:
            raise ValueError("reason_code inconnu")
        evidence = _validate_text("evidence_ref", evidence_ref, maximum=2_000)
        with self._lock:
            self._begin()
            try:
                row = self._cx.execute(
                    "SELECT t.current_attempt_id,t.title,t.owner,t.priority,t.status,"
                    "t.requested_by,a.attempt_status,a.parent_attempt_id,a.created_at "
                    "FROM tasks t JOIN task_attempts a "
                    "ON a.attempt_id=t.current_attempt_id WHERE t.task_id=?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"task inconnue: {task_id}")
                if row[6] != "ACTIVE":
                    raise ValueError("current attempt is already failed")
                failed_at = self._timestamp()
                event_payload = {
                    "task_id": task_id,
                    "attempt_id": row[0],
                    "reason_code": reason_code,
                    "evidence_ref": evidence,
                }
                event_id, event_digest = self._append_event(
                    event_type="task.attempt_failed.v1",
                    task_id=task_id,
                    attempt_id=row[0],
                    payload=event_payload,
                    created_at=failed_at,
                )
                attempt_payload = _canonical(
                    {
                        "task_id": task_id,
                        "attempt_id": row[0],
                        "parent_attempt_id": row[7],
                        "requested_by": row[5],
                        "attempt_status": "FAILED",
                        "reason_code": reason_code,
                        "evidence_ref": evidence,
                        "failed_at": failed_at,
                    }
                )
                self._cx.execute(
                    "UPDATE task_attempts SET attempt_status='FAILED',reason_code=?,"
                    "evidence_ref=?,event_id=?,failed_at=?,payload_sha256=? "
                    "WHERE attempt_id=? AND attempt_status='ACTIVE'",
                    (
                        reason_code,
                        evidence,
                        event_id,
                        failed_at,
                        _sha256(attempt_payload),
                        row[0],
                    ),
                )
                task_payload = _task_payload(
                    task_id=task_id,
                    title=row[1],
                    owner=row[2],
                    priority=row[3],
                    status=row[4],
                    attempt_id=row[0],
                    requested_by=row[5],
                )
                self._cx.execute(
                    "UPDATE tasks SET last_event_id=?,updated_at=?,payload_sha256=? "
                    "WHERE task_id=?",
                    (event_id, failed_at, _sha256(task_payload), task_id),
                )
                self._cx.execute("COMMIT")
            except Exception:
                self._rollback()
                raise
        return AttemptFailure(
            task_id=task_id,
            attempt_id=row[0],
            reason_code=reason_code,
            evidence_ref=evidence,
            status=row[4],
            event_id=event_id,
            created_at=failed_at,
            payload_sha256=event_digest,
        )

    def request_retry(self, task_id: str, *, requested_by: str) -> TaskRecord:
        if requested_by not in PRINCIPALS:
            raise ValueError("requested_by inconnu")
        with self._lock:
            self._begin()
            try:
                row = self._cx.execute(
                    "SELECT t.title,t.owner,t.priority,t.status,t.current_attempt_id,"
                    "a.attempt_status FROM tasks t JOIN task_attempts a "
                    "ON a.attempt_id=t.current_attempt_id WHERE t.task_id=?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"task inconnue: {task_id}")
                if row[5] != "FAILED":
                    raise ValueError("current attempt is not failed")
                attempt_id = str(uuid.uuid4())
                created_at = self._timestamp()
                event_id, _ = self._append_event(
                    event_type="task.retry_requested.v1",
                    task_id=task_id,
                    attempt_id=attempt_id,
                    payload={
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "parent_attempt_id": row[4],
                        "requested_by": requested_by,
                    },
                    created_at=created_at,
                )
                attempt_payload = _canonical(
                    {
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "parent_attempt_id": row[4],
                        "requested_by": requested_by,
                        "attempt_status": "ACTIVE",
                    }
                )
                self._cx.execute(
                    "INSERT INTO task_attempts "
                    "(attempt_id,task_id,parent_attempt_id,requested_by,attempt_status,"
                    "reason_code,evidence_ref,event_id,created_at,failed_at,payload_sha256) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        attempt_id,
                        task_id,
                        row[4],
                        requested_by,
                        "ACTIVE",
                        None,
                        None,
                        event_id,
                        created_at,
                        None,
                        _sha256(attempt_payload),
                    ),
                )
                task_payload = _task_payload(
                    task_id=task_id,
                    title=row[0],
                    owner=row[1],
                    priority=row[2],
                    status=row[3],
                    attempt_id=attempt_id,
                    requested_by=requested_by,
                )
                self._cx.execute(
                    "UPDATE tasks SET current_attempt_id=?,requested_by=?,last_event_id=?,"
                    "updated_at=?,payload_sha256=? WHERE task_id=?",
                    (
                        attempt_id,
                        requested_by,
                        event_id,
                        created_at,
                        _sha256(task_payload),
                        task_id,
                    ),
                )
                self._cx.execute("COMMIT")
            except Exception:
                self._rollback()
                raise
        return self.get_task(task_id)

    def list_failed(
        self, *, statuses: tuple[str, ...] = TASK_STATES
    ) -> tuple[AttemptFailure, ...]:
        selected = tuple(statuses)
        if any(status not in TASK_STATES for status in selected):
            raise ValueError("status invalide")
        if not selected:
            return ()
        placeholders = ",".join("?" for _ in selected)
        with self._lock:
            rows = self._cx.execute(
                "SELECT a.task_id,a.attempt_id,a.reason_code,a.evidence_ref,t.status,"
                "a.event_id,a.failed_at,e.payload_sha256 FROM task_attempts a "
                "JOIN tasks t ON t.task_id=a.task_id "
                "JOIN task_events e ON e.event_id=a.event_id "
                "WHERE a.attempt_status='FAILED' "
                f"AND t.status IN ({placeholders}) ORDER BY a.failed_at DESC,a.attempt_id",
                selected,
            ).fetchall()
        return tuple(
            AttemptFailure(
                task_id=row[0],
                attempt_id=row[1],
                reason_code=row[2],
                evidence_ref=row[3],
                status=row[4],
                event_id=row[5],
                created_at=row[6],
                payload_sha256=row[7],
            )
            for row in rows
        )

    def attempt_count(self, task_id: str) -> int:
        with self._lock:
            exists = self._cx.execute(
                "SELECT 1 FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(f"task inconnue: {task_id}")
            row = self._cx.execute(
                "SELECT count(*) FROM task_attempts WHERE task_id=?", (task_id,)
            ).fetchone()
        return int(row[0])
