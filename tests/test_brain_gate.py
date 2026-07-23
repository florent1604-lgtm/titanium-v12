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
def test_emotion_est_une_piece_pas_le_pilier():
    """Correction Florent (21/07/2026) : l'émotion est UNE PIÈCE du noyau de calcul, pas le
    pilier décisionnaire. Elle agit via les familles du consensus (déjà comptées dans
    consensus_score) — elle ne doit donc PLUS re-pondérer la taille ici. Son tag reste
    retourné pour l'observabilité."""
    aligned = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(emo_dir=1, emo_conf=1.0), master_fn=_master(bg.AUTO))
    opposed = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(emo_dir=-1, emo_conf=1.0), master_fn=_master(bg.AUTO))
    assert aligned.allow and opposed.allow                    # l'émotion ne bloque jamais
    assert aligned.conviction == opposed.conviction           # équilibre : plus de domination
    assert "EMO_ALIGNED" in aligned.reason_codes              # mais l'apport reste VISIBLE
    assert "EMO_OPPOSED" in opposed.reason_codes


def test_conviction_utilise_la_preuve_pas_la_disponibilite():
    """Audit Hermes (21/07/2026) : `coverage` compte une famille dès qu'un moteur RÉPOND,
    même en votant zéro. La taille doit suivre `directional_coverage` (preuve signée), sinon
    de la simple présence se transforme en engagement."""
    dispo_pleine_sans_preuve = lambda s: {  # noqa: E731
        "status": "UNCONFIRMED", "side": "long", "consensus_score": 60,
        "coverage": 1.0, "directional_coverage": 0.2, "conflict": False,
        "engine_directions": {}, "engine_confirmation": {}}
    preuve_pleine = lambda s: {  # noqa: E731
        "status": "UNCONFIRMED", "side": "long", "consensus_score": 60,
        "coverage": 1.0, "directional_coverage": 1.0, "conflict": False,
        "engine_directions": {}, "engine_confirmation": {}}
    faible = bg.gate_entry("BTCUSD", 1, consensus_fn=dispo_pleine_sans_preuve, master_fn=_master(bg.AUTO))
    solide = bg.gate_entry("BTCUSD", 1, consensus_fn=preuve_pleine, master_fn=_master(bg.AUTO))
    assert solide.conviction > faible.conviction     # la preuve dimensionne, pas la présence
    assert faible.conviction >= bg._CONV_FLOOR       # plancher CONSERVÉ (phase de test)


def test_conviction_suit_l_equilibre_du_consensus():
    """La taille suit la force de l'équilibre (coverage × |consensus_score|), pas un levier isolé."""
    faible = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(score=10, coverage=0.2), master_fn=_master(bg.AUTO))
    fort = bg.gate_entry("BTCUSD", 1, consensus_fn=_cons(score=90, coverage=1.0), master_fn=_master(bg.AUTO))
    assert fort.conviction > faible.conviction
    assert faible.conviction >= bg._CONV_FLOOR                # un setup faible s'ouvre petit


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
