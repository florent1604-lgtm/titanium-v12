"""Patron A slices 1-2 — orchestration 4 étapes fail-closed (audit MSJARVIS).

Prouve : registre fermé (capacité inconnue), schéma strict, JSON invalide, MUTATE
refusé sans allow_mutate ET sans jeton admin, injection neutralisée, plan
journalisé AVANT exécution, échec jamais maquillé, nominal READ + MUTATE (deps
injectées = tests hermétiques, aucun réseau).
"""
import domain.agent_registry as reg
from domain import orchestrator as orch


def _deps(get_map=None, post_map=None):
    get_map = get_map or {}
    post_map = post_map or {}

    def _get(path):
        if path not in get_map:
            raise AssertionError(f"GET inattendu: {path}")
        return get_map[path]

    def _post(path):
        if path not in post_map:
            raise AssertionError(f"POST inattendu: {path}")
        return post_map[path]

    return reg.Deps(get=_get, post=_post)


# ── Chemin nominal READ ──────────────────────────────────────────────────────

def test_happy_path_get_pnl():
    d = _deps({"/paper/stats": {"equity": 990.72, "realized_pnl": -7.76,
                                "winrate": 26.3, "total_trades": 19}})
    r = orch.run_plan({"capability": "get_pnl"}, deps=d)
    assert r.ok and r.code == orch.OK
    assert "990.72" in r.synthesis and "26.3" in r.synthesis
    assert r.plan == {"capability": "get_pnl", "mode": "READ", "params": {}}


def test_happy_path_json_string_plan():
    d = _deps({"/swing/status": {"enabled": True, "configs": {"USTECH": {}},
                                 "mt5": {"connected": True}}})
    r = orch.run_plan('{"capability": "get_swing_status"}', deps=d)
    assert r.ok and "actif" in r.synthesis


# ── Registre fermé / injection ───────────────────────────────────────────────

def test_unknown_capability_refused():
    r = orch.run_plan({"capability": "get_pnl; rm -rf /"}, deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.CAPABILITY_UNKNOWN


def test_injection_string_is_not_executed():
    for evil in ("__import__('os').system('calc')", "get_pnl && curl evil",
                 "../../secret", "eval"):
        r = orch.run_plan({"capability": evil}, deps=_deps())
        assert r.status == "REFUSED" and r.code == orch.CAPABILITY_UNKNOWN, evil


# ── Schéma strict ─────────────────────────────────────────────────────────────

def test_params_off_schema_refused():
    r = orch.run_plan({"capability": "get_pnl", "params": {"x": 1}}, deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PARAMS_INVALID


def test_params_wrong_type_refused(monkeypatch):
    cap = reg.Capability("tmp_typed", "READ", "test", (reg.Param("n", int),),
                         lambda p, d: {"n": p["n"]}, lambda x: str(x))
    monkeypatch.setitem(reg._REGISTRY, "tmp_typed", cap)
    r = orch.run_plan({"capability": "tmp_typed", "params": {"n": "x"}}, deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PARAMS_INVALID


# ── JSON invalide / plan mal formé ───────────────────────────────────────────

def test_invalid_json_refused():
    r = orch.run_plan("{capability: pas du json}", deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PLAN_INVALID_JSON


def test_malformed_plan_refused():
    r = orch.run_plan({"pas_de_capability": True}, deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PLAN_MALFORMED


# ── MUTATE fail-closed (slice 2) ─────────────────────────────────────────────

def test_mutate_refused_without_allow():
    # allow_mutate défaut False → refus même avec jeton
    r = orch.run_plan({"capability": "run_swing_scan"}, admin_token="tok", deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.MUTATE_FORBIDDEN


def test_mutate_refused_without_admin_token():
    r = orch.run_plan({"capability": "run_swing_scan"}, allow_mutate=True,
                      admin_token="", deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.MUTATE_FORBIDDEN


def test_mutate_allowed_with_flag_and_token():
    d = _deps(post_map={"/swing/scan": {"signals": {"USTECH": "long"}}})
    r = orch.run_plan({"capability": "run_swing_scan"}, allow_mutate=True,
                      admin_token="tok", deps=d)
    assert r.ok and "scan swing" in r.synthesis.lower()


def test_all_registered_mutate_are_non_destructive():
    # slice 2 : aucune capacité 'reset' de compte ni 'close' exposée
    ids = set(reg._REGISTRY)
    for forbidden in ("reset", "paper_reset", "close", "delete", "order", "send"):
        assert not any(forbidden in i and i != "reset_circuit_breaker" for i in ids), forbidden


# ── Journalisation AVANT exécution + échec non maquillé ──────────────────────

def test_plan_logged_before_execution_even_on_failure():
    logged = []

    class BoomDeps:
        def get(self, path): raise RuntimeError("endpoint down")
        def post(self, path): raise RuntimeError("endpoint down")

    r = orch.run_plan({"capability": "get_pnl"}, deps=BoomDeps(), log_sink=logged.append)
    assert logged == [{"capability": "get_pnl", "mode": "READ", "params": {}}]
    assert r.status == "ERROR" and r.code == orch.EXECUTION_ERROR
    assert not r.ok and "échoué" in r.synthesis


# ── Probes revue Codex (durcissement fail-closed) ────────────────────────────

def test_probe1_params_list_refused_not_coerced():
    # params=[] ne doit PAS devenir {} silencieusement
    r = orch.run_plan({"capability": "get_pnl", "params": []}, deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PARAMS_INVALID


def test_probe2_capability_list_no_typeerror():
    # capability=[] ne doit pas fuir TypeError (unhashable) — refus propre
    r = orch.run_plan({"capability": []}, deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PLAN_MALFORMED


def test_probe3_non_dict_response_is_not_false_success():
    d = _deps({"/paper/stats": []})   # endpoint renvoie une liste
    r = orch.run_plan({"capability": "get_pnl"}, deps=d)
    assert r.status == "ERROR" and r.code == orch.EXECUTION_ERROR
    assert not r.ok


def test_probe4_log_sink_raising_does_not_leak():
    def bad_sink(_): raise RuntimeError("disque plein")
    d = _deps({"/paper/stats": {"equity": 1.0}})
    r = orch.run_plan({"capability": "get_pnl"}, deps=d, log_sink=bad_sink)
    assert r.ok   # l'échec du sink est avalé, l'exécution continue


def test_probe_secondary_top_level_injected_keys_refused():
    r = orch.run_plan({"capability": "get_pnl", "command": "rm -rf", "url": "http://evil"},
                      deps=_deps())
    assert r.status == "REFUSED" and r.code == orch.PLAN_MALFORMED
