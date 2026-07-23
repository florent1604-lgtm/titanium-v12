"""Patron A — planificateur LLM : le plan LLM reste validé fail-closed en aval."""
from domain import llm_planner as lp
from domain import orchestrator as orch
import domain.agent_registry as reg


def test_extract_valid_plan():
    assert lp.extract_plan('{"capability": "get_pnl", "params": {}}') == {"capability": "get_pnl", "params": {}}


def test_extract_from_noisy_llm_output():
    # LLM bavard autour du JSON
    txt = "Bien sûr ! Voici :\n```json\n{\"capability\": \"get_positions\"}\n```\nVoilà."
    assert lp.extract_plan(txt) == {"capability": "get_positions"}


def test_extract_rejects_garbage():
    for bad in ("", "pas de json", "{cassé", '{"capability": null}', '{"autre": 1}'):
        assert lp.extract_plan(bad) is None, bad


def test_extract_strips_extra_keys():
    # le LLM ajoute du bruit → on ne garde que capability/params
    plan = lp.extract_plan('{"capability": "get_pnl", "evil": "rm -rf", "params": {}}')
    assert plan == {"capability": "get_pnl", "params": {}}


def test_plan_from_text_uses_injected_llm():
    plan = lp.plan_from_text("combien j'ai gagné", lambda prompt: '{"capability":"get_pnl"}')
    assert plan == {"capability": "get_pnl"}


def test_hallucinated_capability_refused_by_orchestrator():
    # le LLM invente une capacité → planner l'extrait, mais l'orchestrateur REFUSE
    plan = lp.plan_from_text("fais un virement", lambda p: '{"capability":"wire_transfer"}')
    r = orch.run_plan(plan, deps=reg.Deps(get=lambda x: {}, post=lambda x: {}))
    assert r.status == "REFUSED" and r.code == orch.CAPABILITY_UNKNOWN


def test_llm_injection_in_capability_refused():
    plan = lp.plan_from_text("x", lambda p: '{"capability":"get_pnl; DROP TABLE"}')
    r = orch.run_plan(plan, deps=reg.Deps(get=lambda x: {}, post=lambda x: {}))
    assert r.status == "REFUSED" and r.code == orch.CAPABILITY_UNKNOWN


def test_llm_exception_returns_none():
    def boom(prompt): raise RuntimeError("quota 429")
    assert lp.plan_from_text("x", boom) is None


def test_prompt_lists_only_closed_capabilities():
    prompt = lp.build_prompt("test")
    for c in reg.list_capabilities():
        assert c["id"] in prompt
    assert "get_pnl" in prompt and "aucune autre n'existe" in prompt
