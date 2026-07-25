"""Moteur de confluence DÉMO : décision EXPLORE + placement injecté (aucun MT5/réseau).
On vérifie le câblage (décision→placement), le mode EXPLORE, et la sûreté fail-safe."""
import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import confluence_demo_engine as de
from core.brain_gate import BrainGate


def _allow_gate(sym, side):
    """Porte cerveau de test qui AUTORISE (sens concordant, conviction pleine)."""
    return BrainGate(True, side or 1, 1.0, "BRAIN", "UNCONFIRMED", ("BRAIN_ALLOW", "EMO_NEUTRAL"))


def _block_gate(sym, side):
    """Porte cerveau de test qui BLOQUE (consensus en conflit)."""
    return BrainGate(False, 0, 0.0, "BRAIN", "CONFLICT", ("BRAIN_CONFLICT",))


def _mk(end_ts, step_min, n=200, trend_up=True):
    idx = pd.date_range(end=end_ts, periods=n, freq=f"{step_min}min", tz="UTC")
    base = np.linspace(100, 112, n) if trend_up else np.linspace(112, 100, n)
    close = base + np.sin(np.arange(n) / 5) * 0.5
    return pd.DataFrame({"open": close - 0.1, "high": close + 0.4, "low": close - 0.4,
                         "close": close, "v": np.random.default_rng(1).uniform(50, 150, n)},
                        index=idx)


def _now():
    return datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)   # lundi, marché ouvert


def _frames(now):
    end = pd.Timestamp(now).floor("4h")
    return {"M15": _mk(end - pd.Timedelta(minutes=15), 15),
            "H4": _mk(end - pd.Timedelta(hours=4), 240)}


def test_decide_est_pur_et_explore():
    now = _now(); f = _frames(now)
    decision, feats = de.decide("XAUUSD", f["M15"], f["H4"], ltf_tf="M15", htf_tf="H4",
                                venue="cfd", now=now, run_emotion=False)
    assert decision.verdict in ("ENTER", "WAIT", "BLOCK")
    assert decision.mode == "explore"           # démo = on teste pour mesurer
    assert feats["data_valid"] is True


def test_donnees_insuffisantes_ne_placent_rien():
    now = _now()
    calls = []
    async def place_fn(*a, **k):
        calls.append((a, k)); return {"sent": True}
    def rates_fn(sym, tf, n):
        return _mk(pd.Timestamp(now).floor("4h"), 15, n=10)   # trop court → data_valid False
    rep = asyncio.run(de.run_once([{"symbol": "EURUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                                  now=now, rates_fn=rates_fn, place_fn=place_fn))
    assert rep["placed"] == [] and calls == []
    assert rep["decisions"][0]["verdict"] in ("BLOCK", "WAIT")


def test_enter_declenche_le_placement_demo():
    now = _now(); f = _frames(now)
    placed_calls = []
    async def place_fn(symbol, side, atr, **k):
        placed_calls.append((symbol, side, atr))
        return {"sent": True, "lot": 0.1, "price": 111.0}
    def rates_fn(sym, tf, n):
        return f[tf]
    # on force une décision ENTER en injectant un gate stub via monkeypatch léger
    import core.confluence_gate as cg

    class _Dec:
        verdict = "ENTER"; side = 1; code = "ENTER_CONFLUENCE"; mode = "explore"
        rank = 2.0; decision_id = "abc"; decided_at = now.isoformat(); reasons = ["ok"]
        gates = []; setup_family = "continuation"
        entered = True
    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        rep = asyncio.run(de.run_once([{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                                      now=now, rates_fn=rates_fn, place_fn=place_fn,
                                      entry_gate=_allow_gate))
    finally:
        cg.evaluate = orig
    assert len(placed_calls) == 1 and placed_calls[0][0] == "XAUUSD"
    assert placed_calls[0][1] == "long" and placed_calls[0][2] > 0
    assert rep["placed"] and rep["placed"][0]["symbol"] == "XAUUSD"


def test_enter_short_mappe_bien_le_side():
    now = _now(); f = _frames(now)
    placed_calls = []
    async def place_fn(symbol, side, atr, **k):
        placed_calls.append(side); return {"sent": True, "lot": 0.1, "price": 111.0}
    import core.confluence_gate as cg

    class _Dec:
        verdict = "ENTER"; side = -1; code = "ENTER_CONFLUENCE"; mode = "explore"
        rank = 1.0; decision_id = "z"; decided_at = now.isoformat(); reasons = []
        gates = []; setup_family = "reversal"; entered = True
    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        asyncio.run(de.run_once([{"symbol": "EURUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                                now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
                                entry_gate=_allow_gate))
    finally:
        cg.evaluate = orig
    assert placed_calls == ["short"]


def test_heartbeat_bat_a_chaque_cycle():
    now = _now(); f = _frames(now)
    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}
    asyncio.run(de.run_once([{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                            now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn))
    hb = de.status_snapshot()["heartbeat"]
    assert hb["last_cycle_at"] and hb["last_cycle_ok"] is True and hb["n_decisions"] == 1


def test_fail_safe_un_symbole_ne_casse_pas_le_tour():
    now = _now(); f = _frames(now)
    def rates_fn(sym, tf, n):
        if sym == "BOOM":
            raise RuntimeError("provider down")
        return f[tf]
    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}
    rep = asyncio.run(de.run_once(
        [{"symbol": "BOOM", "ltf": "M15", "htf": "H4", "venue": "cfd"},
         {"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
        now=now, rates_fn=rates_fn, place_fn=place_fn))
    verdicts = {d["symbol"]: d["verdict"] for d in rep["decisions"]}
    assert verdicts["BOOM"] == "ERROR"           # isolé
    assert "XAUUSD" in verdicts and verdicts["XAUUSD"] != "ERROR"


def test_levels_entry_sl_tps():
    lv = de._levels(100.0, -1, 2.0, sl_atr=1.5, tp_ladder=(1.5, 2.5, 4.0))
    assert lv["side"] == "short" and lv["entry"] == 100.0
    assert lv["sl"] == 103.0                                  # short : SL au-dessus (100 + 1.5×2)
    assert [t["price"] for t in lv["tps"]] == [97.0, 95.0, 92.0]
    assert lv["tps"][0]["rr"] == 1.0                          # 1.5 / 1.5
    # sans direction ou sans ATR → pas de plan
    assert de._levels(100.0, 0, 2.0, sl_atr=1.5, tp_ladder=(1.5,)) is None
    assert de._levels(100.0, 1, 0, sl_atr=1.5, tp_ladder=(1.5,)) is None


def test_run_once_ajustement_binance():
    now = _now(); f = _frames(now)
    def ref_fn(sym):
        return 111.0                                       # prix Binance de référence (crypto)
    async def place_fn(*a, **k):
        return {"sent": False, "reason": "X"}
    rep = asyncio.run(de.run_once(
        [{"symbol": "BTCUSD", "ltf": "M15", "htf": "H4", "venue": "crypto"}],
        now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn, ref_fn=ref_fn))
    ref = rep["decisions"][0]["reference"]
    assert ref and ref["source"] == "binance" and ref["price"] == 111.0
    assert "divergence_pct" in ref


def test_reference_binance_reserve_aux_symboles_crypto():
    now = _now(); f = _frames(now)
    referenced = []

    def ref_fn(sym):
        referenced.append(sym)
        return 111.0

    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}

    async def notify_fn(*a, **k):
        return False

    rep = asyncio.run(de.run_once(
        [{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"},
         {"symbol": "BTCUSD", "ltf": "M15", "htf": "H4", "venue": "crypto"}],
        now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
        notify_fn=notify_fn, ref_fn=ref_fn))

    assert referenced == ["BTCUSD"]
    by_symbol = {d["symbol"]: d for d in rep["decisions"]}
    assert by_symbol["XAUUSD"]["venue"] == "cfd"
    assert by_symbol["XAUUSD"]["reference"] is None
    assert by_symbol["BTCUSD"]["venue"] == "crypto"
    assert by_symbol["BTCUSD"]["reference"]["source"] == "binance"


def test_panne_reference_binance_ne_bloque_pas_le_symbole_crypto():
    now = _now(); f = _frames(now)

    def ref_fn(sym):
        raise TimeoutError("binance indisponible")

    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}

    async def notify_fn(*a, **k):
        return False

    rep = asyncio.run(de.run_once(
        [{"symbol": "BTCUSD", "ltf": "M15", "htf": "H4", "venue": "crypto"}],
        now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
        notify_fn=notify_fn, ref_fn=ref_fn))

    assert rep["decisions"][0]["verdict"] != "ERROR"
    assert rep["decisions"][0]["reference"] is None


def test_aggressive_eligible_respecte_veto_emotion_et_cout():
    from core.confluence_demo_engine import _aggressive_eligible

    class _G:
        def __init__(self, n, ok): self.name, self.passed = n, ok

    def _dec(code="BLOCK_PILLAR_MISSING", side=1, full=False):
        gates = [_G("data_valid", True), _G("trend_sr", True), _G("fair_value", True),
                 _G("liquidity", True), _G("ote_ob", True), _G("candle_confirmed", full)]
        d = type("D", (), {})()
        d.entered = False; d.side = side; d.code = code; d.gates = gates
        return d

    feats_ok = {"emotion": {"filter_block": None}, "cost": {"weekend_block": False}}
    # 4/5 (candle manquant) + émotion neutre + hors week-end → éligible
    assert _aggressive_eligible(_dec(), feats_ok, 4)["ready"]
    # émotion s'oppose au côté (filter_block == side) → veto
    assert _aggressive_eligible(_dec(side=1), {"emotion": {"filter_block": 1}, "cost": {}}, 4) is None
    # coût week-end → veto
    assert _aggressive_eligible(_dec(), {"emotion": {}, "cost": {"weekend_block": True}}, 4) is None
    # WAIT_EMOTION_TIMING (5/5 bloqué par l'émotion) → JAMAIS éligible (P0 Codex)
    assert _aggressive_eligible(_dec(code="WAIT_EMOTION_TIMING", full=True), feats_ok, 4) is None


def test_aggressif_detecte_et_execute_un_4_sur_5():
    now = _now(); f = _frames(now)
    placed = []
    async def place_fn(symbol, side, atr, *, engine="?", **k):
        placed.append((engine, side)); return {"sent": True, "lot": 0.1, "price": 111.0}
    import core.confluence_gate as cg

    class _G:
        def __init__(self, name, ok): self.name, self.passed, self.code = name, ok, name

    class _Dec:                              # 4/5 piliers, structure OK, confluence incomplète
        verdict = "BLOCK"; side = 1; code = "BLOCK_PILLAR_MISSING"; mode = "explore"
        rank = 0.0; decision_id = "x"; decided_at = now.isoformat(); reasons = ["manque bougie"]
        setup_family = "continuation"; entered = False
        gates = [_G("data_valid", True), _G("trend_sr", True), _G("fair_value", True),
                 _G("liquidity", True), _G("ote_ob", True), _G("candle_confirmed", False)]
    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        rep = asyncio.run(de.run_once(
            [{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
            now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
            aggressive_min=4, aggressive_exec=True, entry_gate=_allow_gate))
    finally:
        cg.evaluate = orig
    d = rep["decisions"][0]
    assert d["aggressive"] and d["aggressive"]["ready"] and d["aggressive"]["n_pillars"] == 4
    assert ("confluence-aggr", "long") in placed          # exécuté avec le tag agressif
    assert d["aggressive"]["placed"]["sent"] is True


def test_cerveau_bloque_le_placement_sans_confirmation():
    """Nouveau design : sans feu vert du cerveau, AUCUNE exécution — même sur un ENTER complet.
    L'observation, elle, reste présente (summary['brain'] trace le refus)."""
    now = _now(); f = _frames(now)
    placed = []
    async def place_fn(*a, **k):
        placed.append(a); return {"sent": True}
    import core.confluence_gate as cg

    class _Dec:
        verdict = "ENTER"; side = 1; code = "ENTER_CONFLUENCE"; mode = "explore"
        rank = 2.0; decision_id = "b"; decided_at = now.isoformat(); reasons = []
        gates = []; setup_family = "continuation"; entered = True
    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        rep = asyncio.run(de.run_once([{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                                      now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
                                      entry_gate=_block_gate))
    finally:
        cg.evaluate = orig
    d = rep["decisions"][0]
    assert placed == [] and rep["placed"] == []                  # cerveau a bloqué
    assert d["brain"]["allow"] is False and d["placed"]["reason"] == "BRAIN_GATE_BLOCK"


def test_master_force_execute_via_run_once():
    """Le MASTER (Florent) prime : même si le réflexe local ne déclenche rien, une entrée
    complète gouvernée par un FORCE master s'exécute dans le sens forcé."""
    now = _now(); f = _frames(now)
    placed = []
    async def place_fn(symbol, side, atr, **k):
        placed.append(side); return {"sent": True, "lot": 0.1, "price": 100.0}
    import core.confluence_gate as cg

    class _Dec:
        verdict = "ENTER"; side = 1; code = "ENTER_CONFLUENCE"; mode = "explore"
        rank = 1.0; decision_id = "m"; decided_at = now.isoformat(); reasons = []
        gates = []; setup_family = "continuation"; entered = True
    def _master_force(sym, side):
        return BrainGate(True, -1, 1.0, "MASTER", None, ("MASTER_FORCE_SHORT",))
    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        rep = asyncio.run(de.run_once([{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                                      now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
                                      entry_gate=_master_force))
    finally:
        cg.evaluate = orig
    assert placed == ["short"]                                   # master a forcé le sens
    assert rep["decisions"][0]["brain"]["source"] == "MASTER"


def test_aggressif_non_execute_si_desarme():
    now = _now(); f = _frames(now)
    placed = []
    async def place_fn(symbol, side, atr, *, engine="?", **k):
        placed.append(engine); return {"sent": True}
    import core.confluence_gate as cg

    class _G:
        def __init__(self, name, ok): self.name, self.passed, self.code = name, ok, name

    class _Dec:
        verdict = "BLOCK"; side = -1; code = "BLOCK_PILLAR_MISSING"; mode = "explore"
        rank = 0.0; decision_id = "y"; decided_at = now.isoformat(); reasons = []
        setup_family = "continuation"; entered = False
        gates = [_G("data_valid", True), _G("trend_sr", True), _G("fair_value", True),
                 _G("liquidity", True), _G("ote_ob", True), _G("candle_confirmed", False)]
    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        rep = asyncio.run(de.run_once(
            [{"symbol": "EURUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
            now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn,
            aggressive_min=4, aggressive_exec=False))    # désarmé
    finally:
        cg.evaluate = orig
    d = rep["decisions"][0]
    assert d["aggressive"] and d["aggressive"]["ready"] and d["aggressive"]["placed"] is None
    assert placed == []                                   # rien exécuté


def test_run_once_notifie_chaque_decision():
    now = _now(); f = _frames(now)
    notified = []
    async def notify_fn(sym, summary):
        notified.append((sym, summary.get("verdict")))
    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}
    asyncio.run(de.run_once([{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                            now=now, rates_fn=lambda s, tf, n: f[tf],
                            place_fn=place_fn, notify_fn=notify_fn))
    assert len(notified) == 1 and notified[0][0] == "XAUUSD"


def test_status_snapshot_expose_les_decisions():
    now = _now(); f = _frames(now)
    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}
    asyncio.run(de.run_once([{"symbol": "GBPUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
                            now=now, rates_fn=lambda s, tf, n: f[tf], place_fn=place_fn))
    snap = de.status_snapshot()
    assert "GBPUSD" in snap["symbols"] and snap["recent"]


def test_shadow_observer_est_appele_en_observation_pure():
    now = _now(); f = _frames(now)
    calls = []

    async def place_fn(symbol, side, atr, **k):
        return {"sent": True, "lot": 0.1, "price": 111.0}

    def shadow_observer(symbol, side, score, *, emitted, score_min=None, extra=None):
        calls.append({
            "symbol": symbol,
            "side": side,
            "score": score,
            "emitted": emitted,
            "score_min": score_min,
            "extra": extra,
        })
        return "AGREE_ALLOW"

    import core.confluence_gate as cg

    class _Dec:
        verdict = "ENTER"; side = 1; code = "ENTER_CONFLUENCE"; mode = "explore"
        rank = 2.0; decision_id = "obs"; decided_at = now.isoformat(); reasons = []
        gates = []; setup_family = "continuation"; entered = True

    orig = cg.evaluate
    cg.evaluate = lambda feats, **k: _Dec()
    try:
        asyncio.run(de.run_once(
            [{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
            now=now,
            rates_fn=lambda s, tf, n: f[tf],
            place_fn=place_fn,
            shadow_observer=shadow_observer,
            entry_gate=_allow_gate,
        ))
    finally:
        cg.evaluate = orig

    assert len(calls) == 1
    assert calls[0]["symbol"] == "XAUUSD"
    assert calls[0]["side"] == 1
    assert calls[0]["emitted"] is True
    assert calls[0]["extra"]["path"] == "confluence_demo"


def test_shadow_observer_en_erreur_ne_casse_pas_le_cycle():
    now = _now(); f = _frames(now)

    def shadow_observer(*a, **k):
        raise RuntimeError("observer down")

    async def place_fn(*a, **k):
        return {"sent": False, "reason": "DEMO_DISARMED"}

    rep = asyncio.run(de.run_once(
        [{"symbol": "XAUUSD", "ltf": "M15", "htf": "H4", "venue": "cfd"}],
        now=now,
        rates_fn=lambda s, tf, n: f[tf],
        place_fn=place_fn,
        shadow_observer=shadow_observer,
    ))
    assert rep["decisions"][0]["verdict"] != "ERROR"
