"""EventPlane B0: canonical, append-only, idempotent and hash-chained."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from core import event_plane as ep


VALID_C0A = {
    "decision_id": "d1",
    "as_of": "2026-07-19T07:30:00+00:00",
    "state_version": "confluence/1.1.0",
    "result": "BLOCK",
    "side": "short",
    "reason_codes": ["BLOCK_PILLAR_MISSING"],
    "data_valid": True,
    "setup_family": "reversal",
    "rank": 2.0,
    "n_pillars": 2,
    "aggressive_eligible": False,
    "decision_capability": False,
    "orders_capability": False,
}


def _heartbeat_payload():
    return {
        "task_id": "eventplane.mirror.confluence",
        "owner": "core.event_mirror",
        "observed_at": "2026-07-19T07:30:00+00:00",
        "state": "HEALTHY",
        "heartbeat_age_seconds": 0.0,
        "criticality": "OBSERVATION",
        "restart_capability": True,
    }


def _plane(tmp_path):
    return ep.EventPlane(db_path=tmp_path / "ev.sqlite3")


def _draft(key="k1", payload=None, etype="confluence.evaluation.completed.v1",
           part="instrument:BTCUSD"):
    return ep.EventDraft(
        event_type=etype,
        occurred_at=datetime(2026, 7, 19, 7, 30, tzinfo=timezone.utc),
        source=ep.EventSource("core.confluence_demo_engine", "boot-1", "v1"),
        idempotency_key=key, partition_key=part,
        scope=ep.EventScope("OBSERVE", "axi-demo", "BTCUSD", "crypto"),
        payload=VALID_C0A if payload is None else payload)


def test_publish_alloue_offset_seq_et_chaine_de_hash(tmp_path):
    p = _plane(tmp_path)
    r1 = p.publish(_draft("k1"))
    r2 = p.publish(_draft("k2", payload={**VALID_C0A, "decision_id": "d2", "result": "ENTER"}))
    assert r1.global_offset == 1 and r1.stream_seq == 1 and not r1.duplicate
    assert r2.global_offset == 2 and r2.stream_seq == 2         # même stream (même partition)
    ev = p.read(after_offset=0, limit=10)
    assert ev[0].prev_event_hash is None                        # 1er de la chaîne
    assert ev[1].prev_event_hash == ev[0].event_hash           # chaîné
    assert p.verify_integrity()["ok"] is True


def test_idempotence_meme_contenu_retourne_le_recu(tmp_path):
    p = _plane(tmp_path)
    r1 = p.publish(_draft("same"))
    r2 = p.publish(_draft("same"))                              # rejoué à l'identique
    assert r2.duplicate is True and r2.event_id == r1.event_id
    assert len(p.read(after_offset=0, limit=10)) == 1          # PAS de doublon inséré


def test_idempotence_contenu_different_est_un_conflit(tmp_path):
    p = _plane(tmp_path)
    p.publish(_draft("dup"))
    with pytest.raises(ep.IdempotencyConflict):
        p.publish(_draft("dup", payload={**VALID_C0A, "decision_id": "AUTRE", "result": "ENTER"}))


def test_read_after_offset_et_filtre_type(tmp_path):
    p = _plane(tmp_path)
    p.publish(_draft("a", etype="confluence.evaluation.completed.v1"))
    p.publish(_draft("b", payload=_heartbeat_payload(),
                     etype="runtime.task.heartbeat.v1", part="runtime:mirror"))
    only_hb = p.read(after_offset=0, event_types=("runtime.task.heartbeat.v1",))
    assert len(only_hb) == 1 and only_hb[0].event_type == "runtime.task.heartbeat.v1"
    assert len(p.read(after_offset=1)) == 1                     # strictement > offset


def test_consumer_offset_ack(tmp_path):
    p = _plane(tmp_path)
    p.publish(_draft("a")); p.publish(_draft("b", part="instrument:ETHUSD"))
    assert p.consumer_offset("hermes") == 0
    p.ack(consumer_id="hermes", global_offset=2)
    assert p.consumer_offset("hermes") == 2
    p.ack(consumer_id="hermes", global_offset=1)               # jamais régresser
    assert p.consumer_offset("hermes") == 2


def test_validation_schema_stricte(tmp_path):
    p = _plane(tmp_path)
    with pytest.raises(ep.SchemaViolation):
        p.publish(_draft(etype="MAUVAIS_TYPE"))                 # pas le motif .vN
    with pytest.raises(ep.SchemaViolation):
        p.publish(ep.EventDraft(
            event_type="x.y.v1", occurred_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
            source=ep.EventSource("c", "i", "v"), idempotency_key="k", partition_key="p",
            scope=ep.EventScope("OBSERVE"), payload={"bad": float("nan")}))   # NaN refusé


def test_occurred_at_doit_etre_aware(tmp_path):
    p = _plane(tmp_path)
    d = ep.EventDraft(
        event_type="x.y.v1", occurred_at=datetime(2026, 7, 19),   # naïf
        source=ep.EventSource("c", "i", "v"), idempotency_key="k", partition_key="p",
        scope=ep.EventScope("OBSERVE"), payload={"ok": 1})
    with pytest.raises(ep.SchemaViolation):
        p.publish(d)


def test_unknown_type_and_secret_are_rejected_before_insert(tmp_path):
    p = _plane(tmp_path)
    with pytest.raises(ep.SchemaViolation, match="UNKNOWN_EVENT_TYPE"):
        p.publish(_draft(etype="unknown.fact.v1"))
    with pytest.raises(ep.SchemaViolation, match="SECRET_DETECTED") as caught:
        p.publish(_draft(payload={"api_key": "never-store-this-value"}))
    assert "never-store-this-value" not in str(caught.value)
    assert p.health()["n_events"] == 0


def test_sparse_global_offset_is_not_integrity_failure(tmp_path):
    p = _plane(tmp_path)
    first = p.publish(_draft("first"))
    p._cx.execute("UPDATE sqlite_sequence SET seq=10 WHERE name='events'")
    second = p.publish(_draft("second", payload={**VALID_C0A, "decision_id": "d2"}))
    assert (first.global_offset, second.global_offset) == (1, 11)
    assert p.verify_integrity()["ok"] is True


def test_concurrent_publish_has_unique_contiguous_stream_seq(tmp_path):
    p = _plane(tmp_path)

    def publish(index):
        return p.publish(_draft(
            f"key-{index}",
            payload={**VALID_C0A, "decision_id": f"decision-{index}"},
        ))

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(publish, range(32)))
    assert sorted(receipt.stream_seq for receipt in receipts) == list(range(1, 33))
    assert p.verify_integrity()["ok"] is True


def test_close_and_reopen_preserve_integrity(tmp_path):
    db_path = tmp_path / "ev.sqlite3"
    p = ep.EventPlane(db_path=db_path)
    receipt = p.publish(_draft("persisted"))
    p.close()

    reopened = ep.EventPlane(db_path=db_path)
    assert reopened.read(after_offset=0)[0].event_id == receipt.event_id
    assert reopened.verify_integrity()["ok"] is True
    health = reopened.health()
    assert health["registry_version"] == "eventplane-registry/1.0.0"
    assert health["transport_mode"] == "SQLITE_FALLBACK"
    assert "db" not in health
    reopened.close()
