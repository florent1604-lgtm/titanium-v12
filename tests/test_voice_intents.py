"""Slice 3 — mappage intention vocale → capacité (déterministe, fail-closed)."""
from domain import voice_intents as vi


def test_read_intents():
    assert vi.map_intent("Jarvis, combien j'ai gagné ?") == "get_pnl"
    assert vi.map_intent("quel est mon p&l") == "get_pnl"
    assert vi.map_intent("montre mes positions") == "get_positions"
    assert vi.map_intent("statut du swing") == "get_swing_status"
    assert vi.map_intent("quel est le risque portefeuille") == "get_risk_exposure"
    assert vi.map_intent("mon exposition ?") == "get_risk_exposure"
    assert vi.map_intent("des opportunités ?") == "get_opportunities"


def test_no_false_positive_on_common_speech():
    # motifs génériques ne doivent PAS déclencher (orchestrateur passe en 1er)
    for q in ("y a-t-il un risque de pluie demain",
              "quelle est la performance de mon PC",
              "quel est le solde de mon compte bancaire"):
        assert vi.map_intent(q) is None, q


def test_mutate_intents_need_action_verb():
    assert vi.map_intent("lance un scan swing") == "run_swing_scan"
    assert vi.map_intent("scanne les opportunités") == "run_opportunity_scan"
    assert vi.map_intent("réinitialise le circuit breaker") == "reset_circuit_breaker"
    # une simple question sur le swing n'est PAS une action
    assert vi.map_intent("comment va le swing aujourd'hui") == "get_swing_status"


def test_accent_and_case_insensitive():
    assert vi.map_intent("EXPOSITION") == "get_risk_exposure"
    assert vi.map_intent("Opportunité") == "get_opportunities"


def test_unknown_returns_none():
    for q in ("quelle heure est-il", "raconte une blague",
              "quel temps fait-il", "ouvre le navigateur", ""):
        assert vi.map_intent(q) is None, q


def test_is_mutating():
    assert vi.is_mutating("run_swing_scan") is True
    assert vi.is_mutating("get_pnl") is False
    assert vi.is_mutating("inconnu") is False


def test_returned_ids_exist_in_registry():
    import domain.agent_registry as reg
    for _, cap_id in vi._RULES:
        assert reg.get_capability(cap_id) is not None, cap_id


# ── Confirmation vocale des mutations (P0 revue Codex) ───────────────────────

def _clk():
    t = {"v": 100.0}
    def clock(): return t["v"]
    def advance(d): t["v"] += d
    clock.advance = advance
    return clock


def test_mutation_requires_confirmation():
    clock = _clk()
    g = vi.VoiceMutationGate(ttl_seconds=30, clock=clock)
    prompt = g.propose("run_swing_scan", "Force un scan swing")
    assert "confirme" in prompt.lower() and g.has_pending()
    # une transcription anodine n'est PAS une confirmation
    assert not g.is_confirmation("quelle heure est-il")
    # confirmation valide
    assert g.is_confirmation("oui confirme")
    assert g.take_confirmed() == "run_swing_scan"
    assert not g.has_pending()   # consommé


def test_confirmation_expires_with_ttl():
    clock = _clk()
    g = vi.VoiceMutationGate(ttl_seconds=30, clock=clock)
    g.propose("reset_circuit_breaker", "reset")
    clock.advance(31)            # au-delà du TTL
    assert not g.has_pending()
    assert g.take_confirmed() is None   # trop tard → rien exécuté


def test_cancellation_clears_pending():
    g = vi.VoiceMutationGate()
    g.propose("run_swing_scan", "scan")
    assert g.is_cancellation("annule")
    g.clear()
    assert not g.has_pending()
