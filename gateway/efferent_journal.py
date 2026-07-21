"""gateway/efferent_journal.py — journal efférent SQLite/WAL, vérité autoritaire locale (C1).

Tables normatives (section 4.4) : proposals / decisions / authorizations / outcomes. En C1 :
JOURNALISER AVANT DE RÉPONDRE, idempotence par (principal_sid, idempotency_key), et les tables
`authorizations` et `outcomes` RESTENT VIDES par invariant (vérifié au démarrage, en test et en
santé). Aucune méthode d'insertion d'autorisation/outcome n'existe dans ce lot.

Réglages : journal_mode=WAL, synchronous=FULL, foreign_keys=ON, busy_timeout borné.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from gateway.contracts import AttestedProposal, PolicyDecision

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _ROOT / "data" / "control_gateway" / "command-gateway-v1.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY,
  principal_sid TEXT NOT NULL,
  principal_kind TEXT NOT NULL,
  capability_id TEXT NOT NULL,
  capability_version INTEGER NOT NULL,
  requested_mode TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  proposal_sha256 TEXT NOT NULL,
  proposal_json TEXT NOT NULL CHECK (json_valid(proposal_json)),
  received_at TEXT NOT NULL,
  UNIQUE (principal_sid, idempotency_key)
);
CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL UNIQUE,
  policy_version TEXT NOT NULL,
  registry_digest TEXT NOT NULL,
  state_digest TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('ALLOW','DENY','NO_DECISION')),
  shadow INTEGER NOT NULL CHECK (shadow IN (0,1)),
  reason_codes_json TEXT NOT NULL CHECK (json_valid(reason_codes_json)),
  decided_at TEXT NOT NULL,
  FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id)
);
CREATE TABLE IF NOT EXISTS authorizations (
  authorization_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL UNIQUE,
  authorization_digest TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  consumer_handler_id TEXT,
  FOREIGN KEY (decision_id) REFERENCES decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS outcomes (
  outcome_id TEXT PRIMARY KEY,
  authorization_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED','REJECTED','FAILED','UNKNOWN')),
  reason_codes_json TEXT NOT NULL CHECK (json_valid(reason_codes_json)),
  broker_ref TEXT,
  recorded_at TEXT NOT NULL,
  FOREIGN KEY (authorization_id) REFERENCES authorizations(authorization_id)
);
"""


class IdempotencyConflict(ValueError):
    """Même (principal_sid, idempotency_key) avec un contenu de proposition différent."""


class CriticalInvariantViolation(RuntimeError):
    """Invariant C1 rompu (ex. `authorizations`/`outcomes` non vides). Arrêt fail-closed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def _proposal_digest(p) -> str:
    """Empreinte du CONTENU d'une proposition (définit l'idempotence). request_id, principal
    JSON et justification en sont EXCLUS : ils ne changent pas la nature de la commande."""
    material = {
        "capability_id": p.capability_id, "capability_version": p.capability_version,
        "requested_mode": p.requested_mode, "params": dict(p.params),
        "created_at": p.created_at, "expires_at": p.expires_at,
        "m2_proof": p.m2_proof, "approval": p.approval,
    }
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


class EfferentJournal:
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cx = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.execute("PRAGMA synchronous=FULL")
        self._cx.execute("PRAGMA foreign_keys=ON")
        self._cx.execute("PRAGMA busy_timeout=4000")
        self._cx.executescript(_SCHEMA)
        self._cx.commit()
        self.assert_c1_invariants()

    # -- proposals -----------------------------------------------------------------------
    def persist_proposal(self, attested: AttestedProposal) -> Tuple[str, bool]:
        """Persiste (idempotent). Retourne (proposal_id, duplicate). Un rejeu EXACT rend le
        même proposal_id ; une clé d'idempotence réutilisée avec un digest différent lève
        IdempotencyConflict."""
        p = attested.proposal
        digest = _proposal_digest(p)
        with self._lock:
            cx = self._cx
            cx.execute("BEGIN IMMEDIATE")
            try:
                row = cx.execute(
                    "SELECT proposal_id, proposal_sha256 FROM proposals "
                    "WHERE principal_sid=? AND idempotency_key=?",
                    (attested.principal.sid, p.idempotency_key)).fetchone()
                if row:
                    cx.execute("ROLLBACK")
                    if row[1] == digest:
                        return row[0], True                     # rejeu exact
                    raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
                proposal_id = uuid.uuid4().hex
                cx.execute(
                    "INSERT INTO proposals (proposal_id, principal_sid, principal_kind, "
                    "capability_id, capability_version, requested_mode, created_at, expires_at, "
                    "idempotency_key, proposal_sha256, proposal_json, received_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (proposal_id, attested.principal.sid, attested.principal.kind,
                     p.capability_id, p.capability_version, p.requested_mode, p.created_at,
                     p.expires_at, p.idempotency_key, digest,
                     _canonical({
                         "capability_id": p.capability_id,
                         "capability_version": p.capability_version,
                         "requested_mode": p.requested_mode, "params": dict(p.params),
                         "created_at": p.created_at, "expires_at": p.expires_at,
                     }), attested.received_at))
                cx.execute("COMMIT")
                return proposal_id, False
            except IdempotencyConflict:
                raise
            except Exception:
                try:
                    cx.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    # -- decisions -----------------------------------------------------------------------
    def record_decision(self, proposal_id: str, decision: PolicyDecision, *,
                        registry_digest: str, state_digest: str) -> str:
        with self._lock:
            cx = self._cx
            cx.execute("BEGIN IMMEDIATE")
            try:
                row = cx.execute("SELECT decision_id FROM decisions WHERE proposal_id=?",
                                 (proposal_id,)).fetchone()
                if row:
                    cx.execute("ROLLBACK")
                    return row[0]
                decision_id = uuid.uuid4().hex
                cx.execute(
                    "INSERT INTO decisions (decision_id, proposal_id, policy_version, "
                    "registry_digest, state_digest, verdict, shadow, reason_codes_json, "
                    "decided_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (decision_id, proposal_id, decision.policy_version, registry_digest,
                     state_digest, decision.verdict, 1 if decision.shadow else 0,
                     _canonical(list(decision.reason_codes)), _now()))
                cx.execute("COMMIT")
                return decision_id
            except Exception:
                try:
                    cx.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def load_decision(self, proposal_id: str) -> Optional[dict]:
        row = self._cx.execute(
            "SELECT decision_id, verdict, shadow, reason_codes_json, policy_version, "
            "registry_digest FROM decisions WHERE proposal_id=?", (proposal_id,)).fetchone()
        if not row:
            return None
        return {"decision_id": row[0], "verdict": row[1], "shadow": bool(row[2]),
                "reason_codes": tuple(json.loads(row[3])), "policy_version": row[4],
                "registry_digest": row[5]}

    # -- invariants + santé --------------------------------------------------------------
    def assert_c1_invariants(self) -> None:
        na = self._cx.execute("SELECT COUNT(*) FROM authorizations").fetchone()[0]
        no = self._cx.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        if na != 0:
            raise CriticalInvariantViolation(f"C1_AUTHORIZATIONS_NOT_EMPTY:{na}")
        if no != 0:
            raise CriticalInvariantViolation(f"C1_OUTCOMES_NOT_EMPTY:{no}")

    def health(self) -> dict:
        cx = self._cx
        verdicts = {v: c for v, c in cx.execute(
            "SELECT verdict, COUNT(*) FROM decisions GROUP BY verdict")}
        return {
            "palier": "C1_SHADOW",
            "n_proposals": cx.execute("SELECT COUNT(*) FROM proposals").fetchone()[0],
            "n_decisions": cx.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
            "verdicts": verdicts,
            "authorization_count": cx.execute("SELECT COUNT(*) FROM authorizations").fetchone()[0],
            "outcome_count": cx.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0],
        }
