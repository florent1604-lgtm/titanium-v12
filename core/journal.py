"""core/journal.py — LE SYSTÈME CIRCULATOIRE (N0, socle). Réorg Phase 1.2 (27/07/2026).

Journal append-only LOCAL (SQLite, stdlib — zéro dépendance) où CHAQUE niveau écrit ce
qu'il a produit, indexé par `correlation_id`. C'est le patrimoine du système : tout ce qui
a été appris. Sa perte réinitialise l'adaptation à zéro.

CE QUI EST JOURNALISÉ (par `correlation_id`) :
  - `signal`   : l'état complet au moment du signal (snapshot SystemState),
  - `decision` : la décision du RiskGate — ALLOW / REDUCE / DENY + motif + taille autorisée,
  - `fill`     : le résultat d'exécution — fill, MAE/MFE, R réalisé, frais + slippage RÉELS,
  - `ghost`    : trajectoire post-refus d'un signal REFUSÉ (trade fantôme).

POINT CRITIQUE — DATASET NON CENSURÉ : on journalise aussi les signaux REFUSÉS et on suit
leur trajectoire comme s'ils avaient été pris. Sans ça, on n'apprend que des trades acceptés
(échantillon biaisé) et on ne peut jamais savoir si un veto coupe des trades gagnants.

INVARIANTS :
- #6 socle : n'importe aucun module métier (stdlib + type SystemState du même socle N0, toléré).
- Persistance : disque LOCAL uniquement, JAMAIS un dossier synchronisé (OneDrive/Drive/Dropbox)
  — une base SQLite ouverte en écriture s'y corrompt silencieusement. Sauvegarde = export
  immuable (partitions closes), pas synchro (cf. règles de persistance du prompt).
- NON FATAL : journaliser ne doit jamais casser une décision/un ordre. Toute erreur est avalée.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _ROOT / "data" / "journal" / "titanium_journal.sqlite3"

VALID_KINDS = {"signal", "decision", "fill", "ghost", "adapt", "halt", "health"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_payload(obj: Any) -> str:
    """Sérialise un payload (dict, SystemState, ou objet) en JSON, best-effort."""
    if obj is None:
        return "{}"
    if hasattr(obj, "to_journal_dict"):            # SystemState
        obj = obj.to_journal_dict()
    elif hasattr(obj, "model_dump"):               # tout modèle pydantic
        obj = obj.model_dump(mode="json")
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"_unserializable": str(obj)}, ensure_ascii=False)


class Journal:
    """Journal SQLite local, append-only, thread-safe (verrou + connexion par usage)."""

    def __init__(self, db_path: Path | str = _DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")   # concurrence lecture/écriture locale
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS journal_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_utc TEXT NOT NULL,
                        correlation_id TEXT,
                        level TEXT,
                        kind TEXT NOT NULL,
                        symbol TEXT,
                        payload TEXT NOT NULL
                    );""")
                conn.execute("CREATE INDEX IF NOT EXISTS ix_corr ON journal_events(correlation_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS ix_kind ON journal_events(kind);")
                conn.execute("CREATE INDEX IF NOT EXISTS ix_ts ON journal_events(ts_utc);")
        except Exception:
            pass                                    # non fatal : le trading passe avant la traçabilité

    # ── écriture ──────────────────────────────────────────────────────────────
    def record(self, kind: str, *, correlation_id: Optional[str] = None,
               level: Optional[str] = None, symbol: Optional[str] = None,
               payload: Any = None) -> None:
        """Écrit un événement. `kind` ∈ VALID_KINDS. Jamais bloquant/fatal."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO journal_events (ts_utc, correlation_id, level, kind, symbol, payload)"
                    " VALUES (?,?,?,?,?,?)",
                    (_utcnow_iso(), correlation_id, level, str(kind), symbol, _to_payload(payload)))
        except Exception:
            pass

    def record_signal(self, state, *, accepted: bool = True) -> None:
        """Snapshot de l'état au signal (accepté OU refusé — dataset non censuré)."""
        corr = getattr(state, "correlation_id", None)
        sym = getattr(getattr(state, "market", None), "symbol", None)
        self.record("signal", correlation_id=corr, level="N3", symbol=sym,
                    payload={"accepted": bool(accepted), "state": state})

    def record_decision(self, correlation_id: str, decision: str, *, reason: str = "",
                        allowed_size: Optional[float] = None, symbol: Optional[str] = None,
                        extra: Optional[dict] = None) -> None:
        """Décision du RiskGate : ALLOW / REDUCE / DENY + motif + taille autorisée."""
        self.record("decision", correlation_id=correlation_id, level="N4", symbol=symbol,
                    payload={"decision": decision, "reason": reason,
                             "allowed_size": allowed_size, **(extra or {})})

    def record_fill(self, correlation_id: str, *, symbol: Optional[str] = None,
                    payload: Optional[dict] = None) -> None:
        """Résultat d'exécution réel : fill, MAE/MFE, R, frais/slippage subis."""
        self.record("fill", correlation_id=correlation_id, level="N5", symbol=symbol,
                    payload=payload or {})

    def record_ghost(self, correlation_id: str, *, symbol: Optional[str] = None,
                     payload: Optional[dict] = None) -> None:
        """Trajectoire post-refus d'un signal refusé (trade fantôme)."""
        self.record("ghost", correlation_id=correlation_id, level="N6", symbol=symbol,
                    payload=payload or {})

    # ── lecture ───────────────────────────────────────────────────────────────
    def read(self, *, correlation_id: Optional[str] = None, kind: Optional[str] = None,
             since_iso: Optional[str] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        try:
            q = "SELECT id, ts_utc, correlation_id, level, kind, symbol, payload FROM journal_events"
            cond, args = [], []
            if correlation_id:
                cond.append("correlation_id = ?"); args.append(correlation_id)
            if kind:
                cond.append("kind = ?"); args.append(kind)
            if since_iso:
                cond.append("ts_utc >= ?"); args.append(since_iso)
            if cond:
                q += " WHERE " + " AND ".join(cond)
            q += " ORDER BY id DESC LIMIT ?"; args.append(int(limit))
            with self._lock, self._connect() as conn:
                rows = conn.execute(q, args).fetchall()
            out = []
            for r in rows:
                try:
                    payload = json.loads(r[6])
                except Exception:
                    payload = {"_raw": r[6]}
                out.append({"id": r[0], "ts_utc": r[1], "correlation_id": r[2],
                            "level": r[3], "kind": r[4], "symbol": r[5], "payload": payload})
            return out
        except Exception:
            return []

    def counts_by_kind(self) -> Dict[str, int]:
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT kind, COUNT(*) FROM journal_events GROUP BY kind").fetchall()
            return {k: n for k, n in rows}
        except Exception:
            return {}


# Instance partagée (paresseuse) — infra N0 disponible depuis n'importe quel niveau.
_shared: Optional[Journal] = None
_shared_lock = threading.Lock()


def get_journal() -> Journal:
    global _shared
    if _shared is None:
        with _shared_lock:
            if _shared is None:
                _shared = Journal()
    return _shared
