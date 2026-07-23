"""domain/orchestrator.py — Orchestration 4 étapes (patron A, slices 1-2).

Pipeline validé par Florent (audit MSJARVIS, patron A) :

    PLAN (JSON du LLM)  →  VALIDATION fail-closed  →  EXÉCUTION (handler codé)
                                                    →  SYNTHÈSE

Garde-fous (Claude + Hermes + Codex) :
  - le plan est une donnée NON FIABLE : validé contre le registre FERMÉ ;
  - le plan est JOURNALISÉ AVANT exécution ;
  - la SYNTHÈSE ne transforme JAMAIS un échec en succès ;
  - MUTATE : refusé fail-closed sauf `allow_mutate=True` ET jeton admin présent ;
    l'endpoint applique aussi `require_admin` (défense en profondeur) ; jamais
    d'ordre réel (paper-only) ;
  - aucune exception ne fuit : tout défaut devient un refus motivé.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from domain.agent_registry import (
    Deps, default_http_get, get_capability, make_http_post,
)

logger = logging.getLogger(__name__)

OK = "OK"
PLAN_INVALID_JSON = "PLAN_INVALID_JSON"
PLAN_MALFORMED = "PLAN_MALFORMED"
CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
PARAMS_INVALID = "PARAMS_INVALID"
MUTATE_FORBIDDEN = "MUTATE_FORBIDDEN"
EXECUTION_ERROR = "EXECUTION_ERROR"


@dataclass
class OrchestratorResult:
    status: str                       # OK | REFUSED | ERROR
    code: str
    capability: Optional[str] = None
    synthesis: str = ""
    data: Optional[dict] = None
    plan: Optional[dict] = None

    @property
    def ok(self) -> bool:
        return self.status == OK


_ALLOWED_PLAN_KEYS = {"capability", "params"}


def _parse_plan(plan: Any):
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (json.JSONDecodeError, ValueError):
            return None, OrchestratorResult("REFUSED", PLAN_INVALID_JSON,
                                            synthesis="Plan illisible (JSON invalide).")
    if not isinstance(plan, dict) or "capability" not in plan:
        return None, OrchestratorResult("REFUSED", PLAN_MALFORMED,
                                        synthesis="Plan mal formé (capacité absente).")
    # capability DOIT être une chaîne (sinon get_capability lèverait TypeError
    # sur une liste/dict non hashable — probe Codex #2).
    if not isinstance(plan["capability"], str):
        return None, OrchestratorResult("REFUSED", PLAN_MALFORMED,
                                        synthesis="Plan mal formé (capacité non textuelle).")
    # clés top-level inattendues (command/url injectés par le LLM) → refus strict.
    extra = set(plan) - _ALLOWED_PLAN_KEYS
    if extra:
        return None, OrchestratorResult("REFUSED", PLAN_MALFORMED,
                                        synthesis=f"Plan mal formé (clés interdites : "
                                                  f"{sorted(extra)}).")
    return plan, None


def run_plan(plan: Any, *, allow_mutate: bool = False, admin_token: str = "",
             deps: Optional[Deps] = None,
             log_sink: Callable[[dict], None] | None = None) -> OrchestratorResult:
    """Exécute UN plan {capability, params?} en 4 étapes, fail-closed.

    allow_mutate + admin_token : requis TOUS DEUX pour exécuter une capacité
    MUTATE (slice 2). READ ne les requiert pas. `deps` injectable pour les tests.
    """
    # ── 1. PLAN ──────────────────────────────────────────────────────────────
    parsed, refusal = _parse_plan(plan)
    if refusal is not None:
        return refusal
    cap_id = parsed["capability"]
    # params : si présent, DOIT être un dict (pas de coercition de [] → {} —
    # probe Codex #1). Absent = dict vide.
    params = parsed.get("params", {})
    if not isinstance(params, dict):
        return OrchestratorResult("REFUSED", PARAMS_INVALID, capability=cap_id,
                                  synthesis=f"Paramètres refusés : params doit être "
                                            f"un objet ({type(params).__name__}).")

    # ── 2. VALIDATION (fail-closed) ──────────────────────────────────────────
    cap = get_capability(cap_id)
    if cap is None:
        return OrchestratorResult("REFUSED", CAPABILITY_UNKNOWN, capability=str(cap_id),
                                  synthesis=f"Capacité inconnue : {cap_id!r}. "
                                            f"Refusé (registre fermé).")
    if cap.mode == "MUTATE":
        if not allow_mutate:
            return OrchestratorResult("REFUSED", MUTATE_FORBIDDEN, capability=cap.id,
                                      synthesis=f"Action {cap.id} refusée : mutations "
                                                f"désactivées.")
        if not admin_token:
            return OrchestratorResult("REFUSED", MUTATE_FORBIDDEN, capability=cap.id,
                                      synthesis=f"Action {cap.id} refusée : jeton admin "
                                                f"requis.")
    ok, reason = cap.validate_params(params)
    if not ok:
        return OrchestratorResult("REFUSED", PARAMS_INVALID, capability=cap.id,
                                  synthesis=f"Paramètres refusés : {reason}")

    validated_plan = {"capability": cap.id, "mode": cap.mode, "params": params}

    # ── 3. JOURNALISATION AVANT EXÉCUTION ────────────────────────────────────
    logger.info("[ORCH] plan validé avant exécution: %s", validated_plan)
    if log_sink is not None:
        try:                              # un sink défaillant ne fuit jamais (probe #4)
            log_sink(dict(validated_plan))
        except Exception:
            logger.warning("[ORCH] log_sink a échoué (ignoré).")

    # ── dépendances (par défaut : API locale ; POST porteur du jeton admin) ───
    if deps is None:
        deps = Deps(get=default_http_get, post=make_http_post(admin_token))

    # ── 4. EXÉCUTION puis SYNTHÈSE (échec jamais maquillé) ────────────────────
    try:
        data = cap.handler(params, deps)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ORCH] échec exécution %s: %r", cap.id, exc)
        return OrchestratorResult("ERROR", EXECUTION_ERROR, capability=cap.id,
                                  synthesis=f"L'exécution de {cap.id} a échoué "
                                            f"(donnée/action indisponible).",
                                  plan=validated_plan)
    # une réponse non-dict (ex. [] d'un endpoint) NE doit pas devenir un faux
    # succès via une synth qui lève puis retombe sur un message générique (probe #3).
    if not isinstance(data, dict):
        logger.warning("[ORCH] %s: réponse non exploitable (%s)", cap.id, type(data).__name__)
        return OrchestratorResult("ERROR", EXECUTION_ERROR, capability=cap.id,
                                  synthesis=f"L'exécution de {cap.id} a renvoyé une "
                                            f"donnée inattendue.",
                                  plan=validated_plan)
    try:
        synthesis = cap.synth(data)
    except Exception:
        logger.warning("[ORCH] synth %s a échoué sur donnée valide.", cap.id)
        synthesis = f"{cap.id} exécuté (synthèse indisponible)."
    return OrchestratorResult(OK, OK, capability=cap.id, synthesis=synthesis,
                              data=data, plan=validated_plan)
