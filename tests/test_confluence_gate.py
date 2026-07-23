"""Portes ET de confluence : tous les piliers alignés ou pas d'entrée ;
émotion/coût = WAIT/BLOCK ; le rank ne décide jamais."""
from core import confluence_gate as cg


def _full_long(**over):
    f = {"data_valid": True, "trend": +1, "setup_side": +1,
         "setup_family": "continuation", "on_sr_level": True, "fair_value": True,
         "liquidity": +1, "ote": +1, "candle": +1,
         "strengths": {"trend_sr": 0.8, "fair_value": 0.6, "liquidity": 0.7,
                       "ote_ob": 0.7, "candle_confirmed": 0.6},
         "emotion": {"filter_block": None, "stale": False, "confidence": 0.7, "wait": False},
         "cost": {"edge_ok": True, "weekend_block": False}}
    f.update(over)
    return f


def test_confluence_complete_entre():
    d = cg.evaluate(_full_long())
    assert d.verdict == "ENTER" and d.side == +1 and d.rank > 0


def test_un_pilier_manquant_bloque():
    # même avec tous les autres parfaits, si le juste-prix manque → BLOCK (pas d'additif)
    d = cg.evaluate(_full_long(fair_value=False))
    assert d.verdict == "BLOCK"
    assert any(g.name == "fair_value" and not g.passed for g in d.gates)


def test_pilier_desaligne_bloque():
    # liquidité côté SHORT alors qu'on est LONG → confluence rompue
    d = cg.evaluate(_full_long(liquidity=-1))
    assert d.verdict == "BLOCK"


def test_donnees_invalides_bloque():
    assert cg.evaluate(_full_long(data_valid=False)).verdict == "BLOCK"


def test_pas_de_tendance_bloque():
    assert cg.evaluate(_full_long(trend=0)).verdict == "BLOCK"


def test_emotion_bloque_le_cote():
    # émotion "ne pas acheter l'euphorie" = filter_block long → BLOCK malgré confluence
    d = cg.evaluate(_full_long(emotion={"filter_block": +1, "stale": False,
                                        "confidence": 0.8, "wait": False}))
    assert d.verdict == "BLOCK"


def test_emotion_wait_si_timing_pas_mur():
    d = cg.evaluate(_full_long(emotion={"filter_block": None, "stale": True,
                                        "confidence": 0.8, "wait": False}))
    assert d.verdict == "WAIT"


def test_cout_weekend_bloque():
    d = cg.evaluate(_full_long(cost={"edge_ok": True, "weekend_block": True}))
    assert d.verdict == "BLOCK"


def test_rank_ne_decide_pas():
    # un rank élevé ne force pas ENTER si un pilier manque
    d = cg.evaluate(_full_long(candle=0, strengths={"trend_sr": 9, "fair_value": 9}))
    assert d.verdict == "BLOCK"


# ── edge_ok : plus de fail-OPEN (P0 Codex) ; mode PROD vs DÉMO/EXPLORE ─────────

def test_prod_bloque_sans_edge_prouve():
    # PROD (require_edge=True par défaut) : edge inconnu (None) → BLOCK, pas d'entrée réelle
    d = cg.evaluate(_full_long(cost={"edge_ok": None, "weekend_block": False}))
    assert d.verdict == "BLOCK" and d.code == "BLOCK_EDGE_UNPROVEN"


def test_demo_explore_entre_pour_mesurer():
    # DÉMO/EXPLORE (require_edge=False) : on teste la stratégie sur MT5 même sans edge prouvé
    d = cg.evaluate(_full_long(cost={"edge_ok": None, "weekend_block": False}),
                    require_edge=False)
    assert d.verdict == "ENTER" and d.mode == "explore"


def test_edge_negatif_bloque_meme_en_explore():
    # edge explicitement négatif (labo l'a mesuré perdant) → BLOCK partout
    d = cg.evaluate(_full_long(cost={"edge_ok": False, "weekend_block": False}),
                    require_edge=False)
    assert d.verdict == "BLOCK" and d.code == "BLOCK_EDGE_NEGATIVE"


def test_short_confluence_entre():
    short = _full_long(trend=-1, setup_side=-1, liquidity=-1, ote=-1, candle=-1)
    d = cg.evaluate(short)
    assert d.verdict == "ENTER" and d.side == -1


def test_setup_side_porte_le_reversal():
    # tendance haussière (CONTEXTE) mais setup SHORT sur résistance : le side vient du setup,
    # la tendance ne bloque pas le reversal (demande Florent : ne pas trop restreindre).
    f = _full_long(trend=+1, setup_side=-1, setup_family="reversal",
                   liquidity=-1, ote=-1, candle=-1)
    d = cg.evaluate(f)
    assert d.side == -1 and d.verdict == "ENTER"


def test_reversal_exige_quand_meme_le_niveau_sr():
    # un reversal sans niveau S/R sous le prix n'est pas un setup → BLOCK (pas de laxisme)
    f = _full_long(trend=+1, setup_side=-1, setup_family="reversal",
                   on_sr_level=False, liquidity=-1, ote=-1, candle=-1)
    d = cg.evaluate(f)
    assert d.verdict == "BLOCK"


def test_absence_de_setup_attend_sans_interdire_experimentation():
    d = cg.evaluate(_full_long(setup_side=None, setup_family=None), require_edge=False)
    assert d.verdict == "WAIT" and d.code == "WAIT_NO_SETUP"


def test_side_externe_ne_peut_pas_contredire_le_setup():
    d = cg.evaluate(_full_long(), side=-1)
    assert d.verdict == "BLOCK" and d.code == "BLOCK_SETUP_INVALID"


def test_famille_inconnue_bloque_fail_closed():
    d = cg.evaluate(_full_long(setup_family="opportuniste"), require_edge=False)
    assert d.verdict == "BLOCK" and d.code == "BLOCK_SETUP_INVALID"


def test_moderateurs_absents_ne_passent_pas_en_explore():
    assert cg.evaluate(_full_long(emotion=None), require_edge=False).code == "BLOCK_EMOTION_UNAVAILABLE"
    assert cg.evaluate(_full_long(cost=None), require_edge=False).code == "BLOCK_COST_UNAVAILABLE"


def test_decided_at_repris_de_la_trace_adaptateur():
    at = "2026-07-20T12:00:00+00:00"
    d = cg.evaluate(_full_long(_trace={"decided_at": at}))
    assert d.decided_at == at


def test_trace_reason_code_et_id_presents():
    d = cg.evaluate(_full_long())
    assert d.code == "ENTER_CONFLUENCE" and d.version and d.decision_id and d.decided_at
    # décision reproductible : même entrée + même horodatage → même id
    from datetime import datetime, timezone
    at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    a = cg.evaluate(_full_long(), decided_at=at)
    b = cg.evaluate(_full_long(), decided_at=at)
    assert a.decision_id == b.decision_id
