"""C0 miroir : moteurs → faits dans l'EventPlane, read-only, idempotent, fail-safe."""
import json
from core import event_mirror as mir
from core import event_plane as ep


def _status():
    return {"symbols": {
        "BTCUSD": {"decision_id": "d-btc-1", "verdict": "BLOCK", "side": -1,
                   "code": "BLOCK_PILLAR_MISSING", "setup_family": "reversal",
                   "venue": "crypto", "decided_at": "2026-07-19T07:30:00+00:00",
                   "rank": 2.0, "data_valid": True,
                   "gates": [{"name": "data_valid", "passed": True},
                             {"name": "trend_sr", "passed": True},
                             {"name": "fair_value", "passed": True},
                             {"name": "candle_confirmed", "passed": False}],
                   "aggressive": {"ready": False}},
        "EURUSD": {"decision_id": "d-eur-1", "verdict": "WAIT", "side": 0,
                   "code": "WAIT_NO_SETUP", "venue": "cfd", "rank": 0.0,
                   "data_valid": True, "setup_family": None,
                   "decided_at": "2026-07-19T07:30:00+00:00", "gates": []},
        "BROKEN": {"verdict": "ERROR", "error": "x"},          # ignoré (pas de decision_id)
    }}


def test_mirror_publie_un_fait_par_decision(tmp_path):
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    rep = mir.mirror_once(plane=plane, status_fn=_status)
    assert set(rep["published"]) == {"BTCUSD", "EURUSD"} and rep["n_errors"] == 0
    types = [e.event_type for e in plane.read(after_offset=0, limit=20)]
    assert types.count("confluence.evaluation.completed.v1") == 2
    assert "runtime.task.heartbeat.v1" in types
    # le fait BTC porte les infos décisionnelles conformes au registre gelé
    btc = [e for e in plane.read(after_offset=0, limit=20)
           if e.partition_key == "instrument:BTCUSD"][0]
    assert btc.payload["n_pillars"] == 2 and btc.payload["result"] == "BLOCK"
    assert btc.payload["side"] == "short" and btc.payload["reason_codes"] == ["BLOCK_PILLAR_MISSING"]


def test_mirror_est_idempotent(tmp_path):
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    mir.mirror_once(plane=plane, status_fn=_status)
    rep2 = mir.mirror_once(plane=plane, status_fn=_status)      # rejoué : mêmes decision_id
    assert rep2["n_published"] == 0 and rep2["n_duplicates"] == 2   # rien de neuf
    # un seul jeu de faits confluence en base
    n = sum(1 for e in plane.read(after_offset=0, limit=50)
            if e.event_type == "confluence.evaluation.completed.v1")
    assert n == 2


def test_mirror_capture_evolution_sans_conflit(tmp_path):
    """MÊME decision_id mais état mutable qui bascule (aggressive_eligible) → NOUVEAU fait,
    pas d'IdempotencyConflict (régression du bug consumer_failures 'mirror.confluence')."""
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    base = {"decision_id": "d-x-1", "verdict": "BLOCK", "side": -1,
            "code": "BLOCK_PILLAR_MISSING", "setup_family": "reversal", "venue": "crypto",
            "decided_at": "2026-07-20T07:30:00+00:00", "rank": 2.0, "data_valid": True,
            "gates": [{"name": "trend_sr", "passed": True}], "aggressive": {"ready": False}}
    mir.mirror_once(plane=plane, status_fn=lambda: {"symbols": {"X": dict(base)}})
    evolved = dict(base); evolved["aggressive"] = {"ready": True}   # l'éligibilité bascule
    rep = mir.mirror_once(plane=plane, status_fn=lambda: {"symbols": {"X": evolved}})
    assert rep["n_published"] == 1 and rep["n_errors"] == 0         # capturé, aucun conflit
    facts = [e for e in plane.read(after_offset=0, limit=20)
             if e.event_type == "confluence.evaluation.completed.v1"]
    assert {f.payload["aggressive_eligible"] for f in facts} == {False, True}


def test_mirror_deux_symboles_meme_decision_id(tmp_path):
    """decision_id n'encode PAS le symbole : deux instruments au même verdict/barre le
    partagent. Sans le sym dans la clé, le 2e entrait en IdempotencyConflict (scope différent).
    Régression du bug consumer_failures 'mirror.confluence'."""
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    shared = {"decision_id": "same-fp-1", "verdict": "BLOCK", "side": -1,
              "code": "BLOCK_PILLAR_MISSING", "setup_family": "reversal", "venue": "cfd",
              "decided_at": "2026-07-20T07:30:00+00:00", "rank": 1.0, "data_valid": True,
              "gates": [{"name": "trend_sr", "passed": True}], "aggressive": {"ready": False}}
    status = {"symbols": {"US500": dict(shared), "NAS100.fs": dict(shared)}}
    rep = mir.mirror_once(plane=plane, status_fn=lambda: status)
    assert rep["n_published"] == 2 and rep["n_errors"] == 0        # les DEUX passent, zéro conflit
    insts = {e.partition_key for e in plane.read(after_offset=0, limit=20)
             if e.event_type == "confluence.evaluation.completed.v1"}
    assert insts == {"instrument:US500", "instrument:NAS100.fs"}


def test_mirror_failsafe_erreur_publication(tmp_path):
    class _BadPlane:
        def publish(self, draft):
            raise RuntimeError("db down")
        def record_failure(self, **k):
            self.recorded = True
    bad = _BadPlane()
    rep = mir.mirror_once(plane=bad, status_fn=_status)
    assert rep["n_errors"] >= 1 and getattr(bad, "recorded", False)   # erreur VISIBLE


# ---- C0b : consensus + lead/lag -------------------------------------------------------

def _consensus_status():
    return {"heartbeat": {"last_cycle_at": "2026-07-20T07:30:00+00:00", "last_cycle_ok": True},
            "symbols": {
        "BTCUSD": {"status": "CONFIRMED", "side": "long", "consensus_score": 80,
                   "coverage": 0.75, "agreement": True, "conflict": False,
                   "engine_confirmation": {"confluence": {"confirmed": True},
                                           "scoring": {"confirmed": True},
                                           "emotion": {"confirmed": False}}},
        "EURUSD": {"status": "INSUFFICIENT", "side": "neutral", "consensus_score": 0,
                   "coverage": 0.2, "agreement": False, "conflict": False,
                   "engine_confirmation": {"confluence": {"confirmed": False},
                                           "scoring": {"confirmed": False},
                                           "emotion": {"confirmed": False}}},
        "BROKEN": {"status": "ERROR", "error": "x"},        # ignoré
    }}


def test_mirror_consensus_conforme_et_normalise(tmp_path):
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    rep = mir.mirror_consensus_once(plane=plane, status_fn=_consensus_status)
    assert set(rep["published"]) == {"BTCUSD", "EURUSD"} and rep["n_errors"] == 0
    events = plane.read(after_offset=0, limit=20)
    assert [e.event_type for e in events].count("consensus.observation.updated.v1") == 2
    btc = [e for e in events if e.partition_key == "instrument:BTCUSD"][0]
    # consensus_score NORMALISÉ de [-100,100] vers [-1,1] (80 → 0.8) + m2_required const true
    assert btc.payload["consensus_score"] == 0.8
    assert btc.payload["m2_required"] is True and btc.payload["decision_capability"] is False
    assert btc.payload["missing_sources"] == ["emotion"]     # seule source non confirmante


def test_mirror_consensus_capture_evolution_intra_cycle(tmp_path):
    """Le consensus met ses symboles à jour PROGRESSIVEMENT alors que `as_of` (heartbeat du
    cycle) reste fixe. Sans signature de contenu le 2e état entrait en IdempotencyConflict et
    le fait était PERDU (régression du bug consumer_failures 'mirror.consensus')."""
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    base = {"heartbeat": {"last_cycle_at": "2026-07-21T05:00:00+00:00"},
            "symbols": {"BTCUSD": {"status": "UNCONFIRMED", "side": "long",
                                   "consensus_score": 20, "coverage": 0.5,
                                   "agreement": False, "conflict": False,
                                   "engine_confirmation": {"emotion": {"confirmed": False}}}}}
    mir.mirror_consensus_once(plane=plane, status_fn=lambda: base)
    evolved = json.loads(json.dumps(base))          # même cycle, contenu recalculé
    evolved["symbols"]["BTCUSD"]["status"] = "CONFIRMED"
    evolved["symbols"]["BTCUSD"]["consensus_score"] = 70
    rep = mir.mirror_consensus_once(plane=plane, status_fn=lambda: evolved)
    assert rep["n_published"] == 1 and rep["n_errors"] == 0      # capturé, aucun fait perdu
    facts = [e for e in plane.read(after_offset=0, limit=20)
             if e.event_type == "consensus.observation.updated.v1"]
    assert {f.payload["status"] for f in facts} == {"UNCONFIRMED", "CONFIRMED"}


def test_mirror_consensus_idempotent(tmp_path):
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    mir.mirror_consensus_once(plane=plane, status_fn=_consensus_status)
    rep2 = mir.mirror_consensus_once(plane=plane, status_fn=_consensus_status)
    assert rep2["n_published"] == 0 and rep2["n_duplicates"] == 2   # même cycle → dédupliqué


def _leadlag_status():
    return {"ts": "2026-07-20T07:30:00+00:00", "by_tf": {
        "H4": {"strong": [
            {"leader": "NAS100.fs", "follower": "US500", "lag": 2, "corr": 0.71,
             "hit_rate": 0.63, "flip_rate": 0.12, "n": 40, "persistence": {"rate": 0.8, "seen": 10}},
            {"leader": "BTCUSD", "follower": "ETHUSD", "lag": 0, "corr": 0.9},   # lag<1 → ignoré
        ]},
        "M5": {"strong": [{"leader": "X", "follower": "Y", "lag": 1, "corr": 0.5}]},  # TF hors enum
    }}


def test_mirror_leadlag_conforme_et_filtre(tmp_path):
    plane = ep.EventPlane(db_path=tmp_path / "ev.sqlite3")
    rep = mir.mirror_leadlag_once(plane=plane, status_fn=_leadlag_status)
    assert rep["n_published"] == 1 and rep["n_errors"] == 0   # lag<1 et TF hors enum écartés
    ll = [e for e in plane.read(after_offset=0, limit=20)
          if e.event_type == "leadlag.observation.updated.v1"]
    assert len(ll) == 1
    p = ll[0].payload
    assert p["timeframe"] == "H4" and p["leader"] == "NAS100.fs" and p["lag"] == 2
    assert p["persistence_rate"] == 0.8 and p["m2_eligible"] is False


def test_mirror_all_isole_les_miroirs(tmp_path, monkeypatch):
    """mirror_all_once agrège les 3 ; l'échec d'un moteur n'arrête pas les autres."""
    monkeypatch.setattr(mir, "mirror_once", lambda **k: {"n_published": 1})
    def _boom(**k):
        raise RuntimeError("consensus mort")
    monkeypatch.setattr(mir, "mirror_consensus_once", _boom)
    monkeypatch.setattr(mir, "mirror_leadlag_once", lambda **k: {"n_published": 2})
    out = mir.mirror_all_once()
    assert out["confluence"]["n_published"] == 1 and out["leadlag"]["n_published"] == 2
    assert "error" in out["consensus"] and out["n_published_total"] == 3
