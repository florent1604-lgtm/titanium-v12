"""Porte neuronale v2 : le cerveau (consensus) FILTRE, l'émotion pilote la CONVICTION (taille),
le master (Florent) prime. Fail-safe."""
from core import brain_gate as bg


def _cons(status="UNCONFIRMED", side="long", score=40, coverage=0.7,
          conflict=False, emo_dir=0, emo_conf=0.0):
    return lambda sym: {
        "status": status, "side": side, "consensus_score": score, "coverage": coverage,
        "conflict": conflict, "engine_directions": ({"emotion": emo_dir} if emo_dir else {}),
        "engine_confirmation": {"emotion": {"confidence": emo_conf}},
    }


def _master(mode):
    return lambda sym: mode


# --- Le cerveau FILTRE (décisif mais pas figé) -------------------------------------------
def test_cerveau_autorise_lean_non_conflictuel():
    g = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons("UNCONFIRMED", "long"), master_fn=_master(bg.AUTO))
    assert g.allow and g.side == 1 and g.source == "BRAIN" and "BRAIN_ALLOW" in g.reason_codes


def test_cerveau_bloque_conflit():
    g = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons("CONFLICT", "long", conflict=True), master_fn=_master(bg.AUTO))
    assert not g.allow and g.reason_codes == ("BRAIN_CONFLICT",)


def test_cerveau_bloque_opposition():
    g = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons("UNCONFIRMED", "short"), master_fn=_master(bg.AUTO))
    assert not g.allow and g.reason_codes == ("BRAIN_SIDE_CONFLICT",)


def test_cerveau_bloque_insufficient():
    g = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons("INSUFFICIENT", "neutral"), master_fn=_master(bg.AUTO))
    assert not g.allow and g.reason_codes == ("BRAIN_INSUFFICIENT",)


def test_cerveau_sans_couverture_bloque():
    g = bg.gate_entry("XYZ", 1, consensus_fn=lambda s: None, master_fn=_master(bg.AUTO))
    assert not g.allow and g.reason_codes == ("BRAIN_NO_COVERAGE",)


# --- L'ÉMOTION pilote la CONVICTION (taille), sans bloquer -------------------------------
def test_emotion_alignee_forte_augmente_la_conviction():
    aligned = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(emo_dir=1, emo_conf=1.0), master_fn=_master(bg.AUTO))
    opposed = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(emo_dir=-1, emo_conf=1.0), master_fn=_master(bg.AUTO))
    assert aligned.allow and opposed.allow          # émotion ne bloque pas (sizing, pas veto)
    assert aligned.conviction > opposed.conviction  # alignée = plus grosse taille
    assert "EMO_ALIGNED" in aligned.reason_codes and "EMO_OPPOSED" in opposed.reason_codes
    assert opposed.conviction == bg._CONV_FLOOR      # opposée → taille plancher


def test_conviction_bornee_0_1():
    g = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(score=100, coverage=1.0, emo_dir=1, emo_conf=1.0), master_fn=_master(bg.AUTO))
    assert 0.0 < g.conviction <= 1.0


# --- Le MASTER prime toujours (conviction pleine sur un ordre forcé) ----------------------
def test_master_force_prime_et_conviction_pleine():
    g = bg.gate_entry("BTCUSD", -1, consensus_fn=_cons("CONFLICT", "short", conflict=True), master_fn=_master(bg.FORCE_LONG))
    assert g.allow and g.side == 1 and g.conviction == 1.0 and g.source == "MASTER"


def test_master_block_prime():
    g = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(), master_fn=_master(bg.BLOCK))
    assert not g.allow and g.source == "MASTER" and g.reason_codes == ("MASTER_BLOCK",)


# --- Store des directives (persistance) --------------------------------------------------
def test_store_master_set_get_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(bg, "_MASTER_PATH", tmp_path / "brain_master.json")
    bg.reset_cache()
    bg.set_master("XAUUSD", bg.FORCE_SHORT)
    bg.set_master("*", bg.PAUSE)
    assert bg.get_master("XAUUSD") == bg.FORCE_SHORT
    assert bg.get_master("EURUSD") == bg.PAUSE
    bg.reset_cache()
    assert bg.get_master("XAUUSD") == bg.FORCE_SHORT
    bg.set_master("XAUUSD", bg.AUTO)
    assert "XAUUSD" not in bg.all_masters()
