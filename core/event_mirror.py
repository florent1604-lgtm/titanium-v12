"""core/event_mirror.py — C0 : MIROIR read-only des moteurs → faits dans l'EventPlane.

Séquence Codex (contrat fusion) : C0a = publisher miroir `confluence` + heartbeat, SANS
effet métier ; C0b = `consensus` + `leadlag` (ce module). Le miroir LIT l'état projeté
(status des moteurs) et PUBLIE des FAITS typés dans B0 (core.event_plane), conformes au
registre GELÉ (docs/contracts/eventplane-v1-registry.json). Il ne modifie AUCUN moteur, ne
déclenche AUCUN ordre. Idempotent par décision/observation (I-12) : re-mirer la même
observation ne crée pas de doublon. Une erreur de publication est VISIBLE (I-11), jamais
avalée silencieusement.

⚠️ read-only / observationnel. Aucun event ne peut déclencher une commande (I-10).
Tous les faits portent `decision_capability=false` / `orders_capability=false` : ce plan
est afférent (perception d'Hermes), pré-M2, jamais décisionnel.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Callable, Optional

from core.event_plane import EventDraft, EventScope, EventSource

_COMPONENT = "core.confluence_demo_engine"
_VERSION = "confluence/1.1.0"
_STATE_VERSION = "confluence/1.2.0"
_CONSENSUS_STATE_VERSION = "consensus-detection/1.0.0"
_LEADLAG_STATE_VERSION = "leadlag-explore/1.0.0"
_SIDE = {1: "long", -1: "short", 0: "neutral"}


def _parse_ts(s) -> datetime:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _compact_ts(s) -> str:
    """Timestamp → fragment d'identifiant conforme au pattern `id` du registre (le `+` du
    décalage horaire n'y est pas autorisé ; `:` `-` `.` le sont)."""
    return str(s).replace("+00:00", "Z").replace("+", "")


def _clamp(x, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _content_sig(payload: dict) -> str:
    """Signature courte et déterministe du CONTENU d'un fait. Sert à composer la clé
    d'idempotence : deux évaluations de MÊME empreinte de décision (`decision_id`) mais dont
    l'état mutable diffère (ex. `aggressive_eligible` bascule dans la barre selon l'émotion)
    sont des observations DIFFÉRENTES → clés différentes → pas d'IdempotencyConflict, et la
    transition est capturée au lieu d'être rejetée en boucle."""
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   default=str).encode("utf-8")).hexdigest()[:12]


def _n_pillars(summary: dict) -> int:
    return sum(1 for g in (summary.get("gates") or [])
              if g.get("passed") and g.get("name") != "data_valid")


def _publish_heartbeat(plane, *, task_id: str, owner: str, instance_id: str,
                       now: datetime, degraded: bool) -> None:
    """Fait de vie d'un miroir, conforme au registre (runtime.task.heartbeat.v1), dédupliqué
    à la minute PAR task_id (sinon les miroirs se masquent l'un l'autre). Fail-safe."""
    minute = now.replace(second=0, microsecond=0)
    try:
        plane.publish(EventDraft(
            event_type="runtime.task.heartbeat.v1", occurred_at=minute,
            source=EventSource("core.event_mirror", instance_id, "mirror/1.0.0"),
            idempotency_key=f"heartbeat:{task_id}:{minute.strftime('%Y%m%dT%H%M')}",
            partition_key=f"runtime:{task_id}", scope=EventScope("OBSERVE"),
            payload={
                "task_id": task_id, "owner": owner,
                "observed_at": minute.isoformat(),
                "state": "DEGRADED" if degraded else "HEALTHY",
                "heartbeat_age_seconds": 0.0, "criticality": "OBSERVATION",
                "restart_capability": True,
            }))
    except Exception:  # noqa: BLE001 — un heartbeat perdu ne casse pas le tour
        pass


def mirror_once(*, plane=None, status_fn: Optional[Callable] = None,
                instance_id: str = "runtime", now: Optional[datetime] = None) -> dict:
    """C0a — un passage de miroir CONFLUENCE : publie un fait par décision (idempotent) +
    un heartbeat. `plane` et `status_fn` INJECTABLES (tests sans DB/moteur). Fail-safe :
    une erreur par symbole est enregistrée (record_failure) et n'interrompt pas le tour."""
    now = now or datetime.now(timezone.utc)
    if plane is None:
        from core.event_plane import get_event_plane
        plane = get_event_plane()
    if status_fn is None:
        from core.confluence_demo_engine import status_snapshot
        status_fn = status_snapshot

    snap = status_fn() or {}
    symbols = snap.get("symbols") or {}
    published, duplicates, errors = [], 0, 0

    for sym, s in symbols.items():
        did = s.get("decision_id")
        if not did or s.get("verdict") == "ERROR":
            continue
        aggr = s.get("aggressive") or {}
        # Payload CONFORME au registre gelé Codex (confluence.evaluation.completed.v1).
        payload = {
            "decision_id": did,
            "as_of": s.get("decided_at"),
            "state_version": _STATE_VERSION,
            "result": s.get("verdict") or "ERROR",
            "side": _SIDE.get(int(s.get("side") or 0), "neutral"),
            "reason_codes": [s.get("code") or "UNSPECIFIED"],
            "data_valid": bool(s.get("data_valid")),
            "setup_family": s.get("setup_family") or None,
            "rank": float(s.get("rank") or 0.0),
            "n_pillars": _n_pillars(s),
            "aggressive_eligible": bool(aggr.get("ready")),
            "decision_capability": False,
            "orders_capability": False,
        }
        # Clé d'idempotence = INSTRUMENT + décision + signature du contenu. L'instrument est
        # indispensable : `decision_id` n'encode PAS le symbole (empreinte du seul contenu de
        # décision), donc deux instruments au même verdict/barre le partagent — sans le `sym`
        # ici, leurs `scope` diffèrent et l'EventPlane lève IdempotencyConflict. La signature
        # du contenu capture en plus l'évolution intra-barre (ex. aggressive_eligible) comme un
        # NOUVEAU fait (I-12) au lieu d'un rejet en boucle.
        draft = EventDraft(
            event_type="confluence.evaluation.completed.v1",
            occurred_at=_parse_ts(s.get("decided_at")),
            source=EventSource(_COMPONENT, instance_id, _VERSION),
            idempotency_key=f"confluence:{sym}:{did}:{_content_sig(payload)}",
            partition_key=f"instrument:{sym}",
            scope=EventScope("OBSERVE", "axi-demo", sym, s.get("venue")),
            payload=payload,
        )
        try:
            r = plane.publish(draft)
            if r.duplicate:
                duplicates += 1
            else:
                published.append(sym)
        except Exception as exc:  # noqa: BLE001 — erreur VISIBLE, jamais avalée
            errors += 1
            try:
                plane.record_failure(consumer_id="mirror.confluence", event_id=did,
                                     reason_code="PUBLISH_FAILED", detail=repr(exc))
            except Exception:
                pass

    _publish_heartbeat(plane, task_id="eventplane.mirror.confluence",
                       owner="core.event_mirror", instance_id=instance_id,
                       now=now, degraded=errors > 0)
    return {"published": published, "n_published": len(published),
            "n_duplicates": duplicates, "n_errors": errors}


def mirror_consensus_once(*, plane=None, status_fn: Optional[Callable] = None,
                          instance_id: str = "runtime",
                          now: Optional[datetime] = None) -> dict:
    """C0b — miroir CONSENSUS : un fait `consensus.observation.updated.v1` par symbole
    (idempotent par cycle de consensus). Read-only. `consensus_score` est NORMALISÉ de
    l'échelle interne [-100,100] vers [-1,1] exigée par le registre gelé."""
    now = now or datetime.now(timezone.utc)
    if plane is None:
        from core.event_plane import get_event_plane
        plane = get_event_plane()
    if status_fn is None:
        from core.consensus_engine import status_snapshot
        status_fn = status_snapshot

    snap = status_fn() or {}
    symbols = snap.get("symbols") or {}
    as_of = (snap.get("heartbeat") or {}).get("last_cycle_at") or now.isoformat()
    tag = _compact_ts(as_of)
    published, duplicates, errors = [], 0, 0

    for sym, s in symbols.items():
        status = s.get("status")
        if not status or status == "ERROR":          # observations mal formées ignorées
            continue
        ec = s.get("engine_confirmation") or {}
        # « sources non confirmantes » : moteurs présents mais qui n'appuient pas le consensus.
        missing = sorted(name for name, v in ec.items() if not (v or {}).get("confirmed"))
        obs_id = f"consensus:{sym}:{tag}"
        payload = {
            "observation_id": obs_id,
            "as_of": as_of,
            "state_version": _CONSENSUS_STATE_VERSION,
            "status": status,
            "side": s.get("side") or "neutral",
            "consensus_score": _clamp((s.get("consensus_score") or 0) / 100.0, -1.0, 1.0),
            "coverage": _clamp(s.get("coverage") or 0.0, 0.0, 1.0),
            "agreement": bool(s.get("agreement")),
            "conflict": bool(s.get("conflict")),
            "missing_sources": missing,
            "m2_required": True,
            "decision_capability": False,
            "orders_capability": False,
        }
        # Le consensus met à jour ses symboles PROGRESSIVEMENT pendant un cycle, alors que
        # `as_of` (heartbeat du cycle) reste fixe : sans signature de contenu, un symbole
        # recalculé rejouait la même clé avec un contenu différent → IdempotencyConflict et
        # le fait était PERDU. La signature en fait un NOUVEAU fait (l'évolution est captée).
        draft = EventDraft(
            event_type="consensus.observation.updated.v1",
            occurred_at=_parse_ts(as_of),
            source=EventSource("core.consensus_engine", instance_id, "consensus/1.0.0"),
            idempotency_key=f"consensus:{sym}:{as_of}:{_content_sig(payload)}",
            partition_key=f"instrument:{sym}",
            scope=EventScope("OBSERVE", "axi-demo", sym, None),
            payload=payload,
        )
        try:
            r = plane.publish(draft)
            if r.duplicate:
                duplicates += 1
            else:
                published.append(sym)
        except Exception as exc:  # noqa: BLE001 — erreur VISIBLE, jamais avalée
            errors += 1
            try:
                plane.record_failure(consumer_id="mirror.consensus", event_id=obs_id,
                                     reason_code="PUBLISH_FAILED", detail=repr(exc))
            except Exception:
                pass

    _publish_heartbeat(plane, task_id="eventplane.mirror.consensus",
                       owner="core.event_mirror", instance_id=instance_id,
                       now=now, degraded=errors > 0)
    return {"published": published, "n_published": len(published),
            "n_duplicates": duplicates, "n_errors": errors}


def mirror_leadlag_once(*, plane=None, status_fn: Optional[Callable] = None,
                        instance_id: str = "runtime",
                        now: Optional[datetime] = None) -> dict:
    """C0b — miroir LEAD/LAG : un fait `leadlag.observation.updated.v1` par candidat notable
    (paire leader→follower persistante), par timeframe. EXPLORATOIRE / pré-M2 : `m2_eligible`
    et `decision_capability` restent false. Read-only, idempotent par scan."""
    now = now or datetime.now(timezone.utc)
    if plane is None:
        from core.event_plane import get_event_plane
        plane = get_event_plane()
    if status_fn is None:
        from core.lead_lag_engine import status_snapshot
        status_fn = status_snapshot

    snap = status_fn() or {}
    as_of = snap.get("ts") or now.isoformat()
    tag = _compact_ts(as_of)
    by_tf = snap.get("by_tf") or {}
    published, duplicates, errors = [], 0, 0

    for tf, data in by_tf.items():
        if tf not in ("M15", "H1", "H4"):            # enum figé du registre
            continue
        for d in (data or {}).get("strong", []):
            try:
                lag = int(d.get("lag") or 0)
            except (TypeError, ValueError):
                lag = 0
            leader, follower = d.get("leader"), d.get("follower")
            if lag < 1 or not leader or not follower:  # lag>=1 exigé par le registre
                continue
            persist = (d.get("persistence") or {}).get("rate")
            obs_id = f"leadlag:{tf}:{leader}:{follower}:{tag}"
            payload = {
                "observation_id": obs_id,
                "as_of": as_of,
                "state_version": _LEADLAG_STATE_VERSION,
                "timeframe": tf,
                "leader": leader,
                "follower": follower,
                "lag": lag,
                "corr": _clamp(d.get("corr") or 0.0, -1.0, 1.0),
                "hit_rate": None if d.get("hit_rate") is None else _clamp(d["hit_rate"], 0.0, 1.0),
                "flip_rate": None if d.get("flip_rate") is None else _clamp(d["flip_rate"], 0.0, 1.0),
                "n": int(d.get("n") or 0),
                "persistence_rate": None if persist is None else _clamp(persist, 0.0, 1.0),
                "m2_eligible": False,
                "decision_capability": False,
            }
            draft = EventDraft(          # signature de contenu : défensif, même classe de bug
                event_type="leadlag.observation.updated.v1",
                occurred_at=_parse_ts(as_of),
                source=EventSource("core.lead_lag_engine", instance_id, "leadlag/1.0.0"),
                idempotency_key=f"leadlag:{tf}:{leader}:{follower}:{as_of}:{_content_sig(payload)}",
                partition_key=f"pair:{leader}>{follower}",
                scope=EventScope("OBSERVE", "axi-demo", follower, None),
                payload=payload,
            )
            try:
                r = plane.publish(draft)
                if r.duplicate:
                    duplicates += 1
                else:
                    published.append(f"{tf}:{leader}>{follower}")
            except Exception as exc:  # noqa: BLE001 — erreur VISIBLE, jamais avalée
                errors += 1
                try:
                    plane.record_failure(consumer_id="mirror.leadlag", event_id=obs_id,
                                         reason_code="PUBLISH_FAILED", detail=repr(exc))
                except Exception:
                    pass

    _publish_heartbeat(plane, task_id="eventplane.mirror.leadlag",
                       owner="core.event_mirror", instance_id=instance_id,
                       now=now, degraded=errors > 0)
    return {"published": published, "n_published": len(published),
            "n_duplicates": duplicates, "n_errors": errors}


def mirror_all_once(*, instance_id: str = "runtime",
                    now: Optional[datetime] = None) -> dict:
    """Un tour complet du plan afférent : confluence + consensus + lead/lag. Chaque miroir est
    isolé (l'échec de l'un ne bloque pas les autres). Utilisé par la boucle runtime."""
    out = {}
    for name, fn in (("confluence", mirror_once),
                     ("consensus", mirror_consensus_once),
                     ("leadlag", mirror_leadlag_once)):
        try:
            out[name] = fn(instance_id=instance_id, now=now)
        except Exception as exc:  # noqa: BLE001 — un miroir mort n'arrête pas les autres
            out[name] = {"error": repr(exc), "n_published": 0, "n_errors": 1}
    out["n_published_total"] = sum(v.get("n_published", 0) for v in out.values()
                                   if isinstance(v, dict))
    return out
