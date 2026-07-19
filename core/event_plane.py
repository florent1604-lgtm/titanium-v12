"""core/event_plane.py — EventPlane control-grade B0 (fusion Hermes, plan afférent).

Substrat durable des SYNAPSES : les moteurs publient des FAITS typés (jamais des
commandes), append-only, ordonnés, hashés en chaîne. Le Cortex et Hermes PROJETTENT
ces faits (lecture seule). Implémente fidèlement le contrat de Codex
(`collab/CONTRAT_FUSION_HERMES_EVENTPLANE_COMMANDGATEWAY_2026-07-19.md`).

INVARIANTS appliqués ici : persistance avant acquittement (I-11), au-moins-une-fois +
idempotence (I-12), ordering défini + gaps visibles (I-13), enveloppe immuable et
hash-chaînée (I-15/I-16), aucune commande ne transite (I-10 : un event est un FAIT).
Store autoritaire = SQLite/WAL, une transaction `BEGIN IMMEDIATE` par publish.

⚠️ Ce module NE déclenche RIEN : pas de handler, pas d'ordre, aucun effet trading.
Le CommandGateway efférent est un canal SÉPARÉ (non fourni ici).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from core.event_registry import (
    EXPECTED_REGISTRY_SHA256,
    RegistryViolation,
    load_registry,
    validate_payload,
)

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _ROOT / "data" / "control_event_plane" / "events-v1.sqlite3"
SCHEMA_VERSION = 1
_EVENT_TYPE_RE = __import__("re").compile(r"^[a-z][a-z0-9_.-]{2,127}\.v[1-9][0-9]*$")


class EventPlaneError(Exception): ...
class SchemaViolation(EventPlaneError): ...
class IdempotencyConflict(EventPlaneError): ...


@dataclass(frozen=True)
class EventSource:
    component: str
    instance_id: str
    producer_version: str


@dataclass(frozen=True)
class EventScope:
    operating_mode: str                  # "OBSERVE" | "PAPER" | "DEMO"
    account_ref: Optional[str] = None
    instrument_id: Optional[str] = None
    venue: Optional[str] = None


@dataclass(frozen=True)
class EventDraft:
    event_type: str
    occurred_at: datetime
    source: EventSource
    idempotency_key: str
    partition_key: str
    scope: EventScope
    payload: Mapping[str, Any]
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    classification: str = "INTERNAL"


@dataclass(frozen=True)
class PublishReceipt:
    event_id: str
    global_offset: int
    stream_id: str
    stream_seq: int
    duplicate: bool
    event_hash: str


@dataclass(frozen=True)
class StoredEvent:
    global_offset: int
    event_id: str
    event_type: str
    occurred_at: str
    recorded_at: str
    stream_id: str
    stream_seq: int
    source_component: str
    idempotency_key: str
    partition_key: str
    correlation_id: Optional[str]
    causation_id: Optional[str]
    scope: dict
    classification: str
    payload: dict
    payload_sha256: str
    prev_event_hash: Optional[str]
    event_hash: str


def _canonical(obj: Any) -> str:
    """JSON canonique B0 : clés triées, compact, ensure_ascii=False, NaN/Inf refusés."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise SchemaViolation("occurred_at doit être timezone-aware (UTC)")
    return dt.astimezone(timezone.utc).isoformat()


_DDL = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS streams (
  stream_id TEXT PRIMARY KEY, last_seq INTEGER NOT NULL CHECK (last_seq >= 0),
  last_event_hash TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  global_offset INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  schema_version INTEGER NOT NULL CHECK (schema_version = 1),
  event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
  stream_id TEXT NOT NULL, stream_seq INTEGER NOT NULL CHECK (stream_seq > 0),
  source_component TEXT NOT NULL, source_instance_id TEXT NOT NULL,
  producer_version TEXT NOT NULL, idempotency_key TEXT NOT NULL, partition_key TEXT NOT NULL,
  correlation_id TEXT, causation_id TEXT,
  scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
  classification TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  payload_sha256 TEXT NOT NULL, prev_event_hash TEXT, event_hash TEXT NOT NULL,
  UNIQUE (stream_id, stream_seq), UNIQUE (source_component, idempotency_key));
CREATE INDEX IF NOT EXISTS events_type_offset ON events(event_type, global_offset);
CREATE INDEX IF NOT EXISTS events_stream_seq ON events(stream_id, stream_seq);
CREATE TABLE IF NOT EXISTS consumer_offsets (
  consumer_id TEXT PRIMARY KEY, global_offset INTEGER NOT NULL CHECK (global_offset >= 0),
  updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS consumer_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT, consumer_id TEXT NOT NULL,
  event_id TEXT NOT NULL, attempt INTEGER NOT NULL CHECK (attempt > 0),
  reason_code TEXT NOT NULL, detail TEXT NOT NULL, failed_at TEXT NOT NULL);
"""


class EventPlane:
    """Store d'événements append-only, hash-chaîné, idempotent. Thread-safe (verrou)."""

    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cx = sqlite3.connect(str(self.db_path), check_same_thread=False,
                                   isolation_level=None)  # autocommit; on gère les BEGIN
        self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.execute("PRAGMA synchronous=FULL")
        self._cx.execute("PRAGMA foreign_keys=ON")
        self._cx.execute("PRAGMA busy_timeout=5000")
        self._cx.executescript(_DDL)

    # ── Publication (I-11/I-12/I-13/I-15) ────────────────────────────────
    def publish(self, draft: EventDraft) -> PublishReceipt:
        self._validate(draft)
        payload_canon = _canonical(dict(draft.payload))
        payload_sha = _sha256(payload_canon)
        scope = {"operating_mode": draft.scope.operating_mode,
                 "account_ref": draft.scope.account_ref,
                 "instrument_id": draft.scope.instrument_id, "venue": draft.scope.venue}
        stream_id = f"{draft.source.component}|{draft.partition_key}"[:192]
        occurred = _iso(draft.occurred_at)

        with self._lock:
            cx = self._cx
            cx.execute("BEGIN IMMEDIATE")
            try:
                # Idempotence (I-12) : même (component, idempotency_key)
                dup = cx.execute(
                    "SELECT event_id, global_offset, stream_id, stream_seq, event_hash, "
                    "payload_sha256, event_type, occurred_at, scope_json FROM events "
                    "WHERE source_component=? AND idempotency_key=?",
                    (draft.source.component, draft.idempotency_key)).fetchone()
                if dup:
                    same = (dup[5] == payload_sha and dup[6] == draft.event_type
                            and dup[7] == occurred and dup[8] == _canonical(scope))
                    if same:
                        cx.execute("ROLLBACK")
                        return PublishReceipt(dup[0], dup[1], dup[2], dup[3], True, dup[4])
                    cx.execute("ROLLBACK")
                    raise IdempotencyConflict(
                        f"idempotency_key réutilisée avec un contenu différent: {draft.idempotency_key}")

                row = cx.execute("SELECT last_seq, last_event_hash FROM streams WHERE stream_id=?",
                                 (stream_id,)).fetchone()
                last_seq = row[0] if row else 0
                prev_hash = row[1] if row else None
                stream_seq = last_seq + 1
                event_id = str(uuid.uuid4())
                recorded = datetime.now(timezone.utc).isoformat()

                immutable = {
                    "schema_version": SCHEMA_VERSION, "event_id": event_id,
                    "event_type": draft.event_type, "occurred_at": occurred,
                    "recorded_at": recorded, "stream_id": stream_id, "stream_seq": stream_seq,
                    "source": {"component": draft.source.component,
                               "instance_id": draft.source.instance_id,
                               "producer_version": draft.source.producer_version},
                    "idempotency_key": draft.idempotency_key, "partition_key": draft.partition_key,
                    "correlation_id": draft.correlation_id, "causation_id": draft.causation_id,
                    "scope": scope, "classification": draft.classification,
                    "payload_sha256": payload_sha, "prev_event_hash": prev_hash,
                }
                event_hash = _sha256(_canonical(immutable))

                cx.execute(
                    "INSERT INTO events (event_id, schema_version, event_type, occurred_at, "
                    "recorded_at, stream_id, stream_seq, source_component, source_instance_id, "
                    "producer_version, idempotency_key, partition_key, correlation_id, "
                    "causation_id, scope_json, classification, payload_json, payload_sha256, "
                    "prev_event_hash, event_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, SCHEMA_VERSION, draft.event_type, occurred, recorded, stream_id,
                     stream_seq, draft.source.component, draft.source.instance_id,
                     draft.source.producer_version, draft.idempotency_key, draft.partition_key,
                     draft.correlation_id, draft.causation_id, _canonical(scope),
                     draft.classification, payload_canon, payload_sha, prev_hash, event_hash))
                global_offset = cx.execute(
                    "SELECT global_offset FROM events WHERE event_id=?", (event_id,)).fetchone()[0]
                cx.execute(
                    "INSERT INTO streams (stream_id, last_seq, last_event_hash, updated_at) "
                    "VALUES (?,?,?,?) ON CONFLICT(stream_id) DO UPDATE SET "
                    "last_seq=excluded.last_seq, last_event_hash=excluded.last_event_hash, "
                    "updated_at=excluded.updated_at",
                    (stream_id, stream_seq, event_hash, recorded))
                cx.execute("COMMIT")
                return PublishReceipt(event_id, global_offset, stream_id, stream_seq, False, event_hash)
            except Exception:
                try:
                    cx.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def _validate(self, d: EventDraft) -> None:
        if not _EVENT_TYPE_RE.match(d.event_type or ""):
            raise SchemaViolation(f"event_type invalide: {d.event_type!r}")
        if not (1 <= len(d.idempotency_key or "") <= 192):
            raise SchemaViolation("idempotency_key 1..192 caractères requis")
        if not (1 <= len(d.partition_key or "") <= 160):
            raise SchemaViolation("partition_key requis")
        if d.classification not in ("PUBLIC", "INTERNAL", "SENSITIVE_METADATA"):
            raise SchemaViolation(f"classification interdite: {d.classification!r}")
        if d.scope.operating_mode not in ("OBSERVE", "PAPER", "DEMO"):
            raise SchemaViolation(f"operating_mode invalide: {d.scope.operating_mode!r}")
        try:
            _canonical(dict(d.payload))          # rejette NaN/Inf/non-sérialisable
        except (ValueError, TypeError) as exc:
            raise SchemaViolation(f"payload non canonicalisable: {exc}") from exc
        try:
            validate_payload(d.event_type, d.payload)
        except RegistryViolation as exc:
            raise SchemaViolation(str(exc)) from None

    # ── Lecture / consommation (I-13/I-14) ───────────────────────────────
    def read(self, *, after_offset: int = 0, limit: int = 100,
             event_types: Tuple[str, ...] = ()) -> Tuple[StoredEvent, ...]:
        q = ("SELECT global_offset,event_id,event_type,occurred_at,recorded_at,stream_id,"
             "stream_seq,source_component,idempotency_key,partition_key,correlation_id,"
             "causation_id,scope_json,classification,payload_json,payload_sha256,"
             "prev_event_hash,event_hash FROM events WHERE global_offset>?")
        args: list = [int(after_offset)]
        if event_types:
            q += " AND event_type IN (%s)" % ",".join("?" * len(event_types))
            args += list(event_types)
        q += " ORDER BY global_offset ASC LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))
        with self._lock:
            rows = self._cx.execute(q, args).fetchall()
        return tuple(StoredEvent(
            r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11],
            json.loads(r[12]), r[13], json.loads(r[14]), r[15], r[16], r[17]) for r in rows)

    def ack(self, *, consumer_id: str, global_offset: int) -> None:
        with self._lock:
            self._cx.execute(
                "INSERT INTO consumer_offsets (consumer_id, global_offset, updated_at) "
                "VALUES (?,?,?) ON CONFLICT(consumer_id) DO UPDATE SET "
                "global_offset=max(consumer_offsets.global_offset, excluded.global_offset), "
                "updated_at=excluded.updated_at",
                (consumer_id, int(global_offset), datetime.now(timezone.utc).isoformat()))

    def consumer_offset(self, consumer_id: str) -> int:
        with self._lock:
            r = self._cx.execute("SELECT global_offset FROM consumer_offsets WHERE consumer_id=?",
                                 (consumer_id,)).fetchone()
        return int(r[0]) if r else 0

    def record_failure(self, *, consumer_id: str, event_id: str, reason_code: str,
                       detail: str) -> None:
        with self._lock:
            n = self._cx.execute(
                "SELECT count(*) FROM consumer_failures WHERE consumer_id=? AND event_id=?",
                (consumer_id, event_id)).fetchone()[0]
            self._cx.execute(
                "INSERT INTO consumer_failures (consumer_id,event_id,attempt,reason_code,"
                "detail,failed_at) VALUES (?,?,?,?,?,?)",
                (consumer_id, event_id, int(n) + 1, reason_code, detail[:2000],
                 datetime.now(timezone.utc).isoformat()))

    # ── Intégrité / santé (I-13/I-16) ────────────────────────────────────
    def verify_integrity(self) -> dict:
        """Recalcule la chaîne de hash par stream ; signale toute rupture (aucun rattrapage)."""
        broken = []
        with self._lock:
            streams = [r[0] for r in self._cx.execute("SELECT stream_id FROM streams").fetchall()]
            for sid in streams:
                prev = None
                rows = self._cx.execute(
                    "SELECT stream_seq,event_hash,payload_sha256,event_id,event_type,occurred_at,"
                    "recorded_at,source_component,source_instance_id,producer_version,"
                    "idempotency_key,partition_key,correlation_id,causation_id,scope_json,"
                    "classification,stream_id FROM events WHERE stream_id=? ORDER BY stream_seq ASC",
                    (sid,)).fetchall()
                expected_seq = 0
                for r in rows:
                    expected_seq += 1
                    if r[0] != expected_seq:
                        broken.append({"stream_id": sid, "issue": "SEQ_GAP", "at": r[0]}); break
                    immutable = {
                        "schema_version": SCHEMA_VERSION, "event_id": r[3], "event_type": r[4],
                        "occurred_at": r[5], "recorded_at": r[6], "stream_id": r[16],
                        "stream_seq": r[0], "source": {"component": r[7], "instance_id": r[8],
                        "producer_version": r[9]}, "idempotency_key": r[10], "partition_key": r[11],
                        "correlation_id": r[12], "causation_id": r[13],
                        "scope": json.loads(r[14]), "classification": r[15],
                        "payload_sha256": r[2], "prev_event_hash": prev}
                    if _sha256(_canonical(immutable)) != r[1]:
                        broken.append({"stream_id": sid, "issue": "HASH_MISMATCH", "seq": r[0]}); break
                    prev = r[1]
        return {"ok": not broken, "streams": len(streams), "broken": broken}

    def health(self) -> dict:
        with self._lock:
            n = self._cx.execute("SELECT count(*) FROM events").fetchone()[0]
            last = self._cx.execute("SELECT max(global_offset) FROM events").fetchone()[0] or 0
            fails = self._cx.execute("SELECT count(*) FROM consumer_failures").fetchone()[0]
            journal_mode = self._cx.execute("PRAGMA journal_mode").fetchone()[0]
        registry = load_registry()
        return {
            "registry_version": registry["registry_version"],
            "registry_sha256": EXPECTED_REGISTRY_SHA256,
            "transport_mode": "SQLITE_FALLBACK",
            "journal_mode": str(journal_mode).upper(),
            "n_events": n,
            "last_offset": last,
            "consumer_failures": fails,
        }

    def close(self) -> None:
        """Close the process-local SQLite connection without deleting the journal."""
        with self._lock:
            self._cx.close()


_DEFAULT: Optional[EventPlane] = None
_DEF_LOCK = threading.Lock()


def get_event_plane() -> EventPlane:
    """Singleton process-local de l'EventPlane par défaut."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEF_LOCK:
            if _DEFAULT is None:
                _DEFAULT = EventPlane()
    return _DEFAULT
