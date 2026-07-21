"""Cortex (E0) : état projeté unifié, lecture seule, fail-safe. Sources monkeypatchées."""
from core import cortex


def _patch(monkeypatch, conf=None, cons=None, ll=None, evp=None):
    monkeypatch.setattr(cortex, "_confluence", lambda: conf if conf is not None else {})
    monkeypatch.setattr(cortex, "_consensus", lambda: cons if cons is not None else {})
    monkeypatch.setattr(cortex, "_leadlag", lambda: ll if ll is not None else {})
    monkeypatch.setattr(cortex, "_eventplane",
                        lambda: evp if evp is not None else {
                            "n_events": 0, "last_offset": 0,
                            "integrity": {"ok": True},
                        })


def test_snapshot_agrege_la_sante_des_moteurs(monkeypatch):
    _patch(monkeypatch,
           conf={"heartbeat": {"last_cycle_ok": True, "last_cycle_at": "t", "n_errors": 0},
                 "symbols": {"BTCUSD": {"aggressive": {"ready": True}}, "ETHUSD": {}}},
           cons={"heartbeat": {"last_cycle_at": "t", "last_cycle_ok": True},
                 "m2_required": True, "decision_capability": False,
                 "symbols": {"X": {}}},
           ll={"ts": "t", "by_tf": {"M15": {"strong": []}, "H4": {"strong": [{"a": 1}]}}})
    snap = cortex.snapshot()
    assert snap["overall_health"] == "ok"
    assert snap["engines"]["confluence"]["n_aggressive_ready"] == 1
    assert snap["engines"]["confluence"]["n_symbols"] == 2
    assert snap["engines"]["consensus"]["decision_capability"] is False
    assert snap["engines"]["leadlag"]["n_strong_candidates"] == 1


def test_source_en_echec_ne_casse_pas_le_cortex(monkeypatch):
    def boom():
        raise RuntimeError("moteur mort")
    monkeypatch.setattr(cortex, "_confluence", boom)
    monkeypatch.setattr(cortex, "_consensus",
                        lambda: {"heartbeat": {"last_cycle_at": "t", "last_cycle_ok": True}})
    monkeypatch.setattr(cortex, "_leadlag", lambda: {"ts": "t", "by_tf": {}})
    monkeypatch.setattr(cortex, "_eventplane",
                        lambda: {"n_events": 0, "last_offset": 0,
                                 "integrity": {"ok": True}})
    snap = cortex.snapshot()
    assert snap["overall_health"] == "degraded"
    assert snap["engines"]["confluence"]["health"] == "down"      # isolé, pas de crash


def test_full_expose_le_detail(monkeypatch):
    _patch(monkeypatch, conf={"heartbeat": {"last_cycle_ok": True}, "symbols": {}},
           cons={"heartbeat": {"last_cycle_at": "t", "last_cycle_ok": True}},
           ll={"ts": "t", "by_tf": {}})
    snap = cortex.snapshot(full=True)
    assert "detail" in snap and "confluence" in snap["detail"]
    assert "detail" not in cortex.snapshot(full=False)


def test_consensus_live_shape_uses_heartbeat_and_symbols(monkeypatch):
    _patch(monkeypatch,
           conf={"heartbeat": {"last_cycle_ok": True, "last_cycle_at": "t"},
                 "symbols": {}},
           cons={"heartbeat": {"last_cycle_at": "t", "last_cycle_ok": True},
                 "symbols": {"BTCUSD": {}, "ETHUSD": {}},
                 "decision_capability": False},
           ll={"ts": "t", "by_tf": {}})

    summary = cortex.snapshot()["engines"]["consensus"]

    assert summary["health"] == "ok"
    assert summary["n_assets"] == 2


def test_eventplane_integrity_is_fail_closed(monkeypatch):
    _patch(monkeypatch,
           conf={"heartbeat": {"last_cycle_ok": True, "last_cycle_at": "t"},
                 "symbols": {}},
           cons={"heartbeat": {"last_cycle_at": "t", "last_cycle_ok": True},
                 "symbols": {}},
           ll={"ts": "t", "by_tf": {}},
           evp={"n_events": 4, "last_offset": 4})

    snap = cortex.snapshot()

    assert snap["engines"]["eventplane"]["health"] == "unknown"
    assert snap["overall_health"] == "degraded"
