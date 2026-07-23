"""domain/llm_planner.py — Planificateur LLM (patron A, évolution HuggingGPT).

Étape « le LLM produit le plan » de l'orchestration en 4 étapes. Le LLM (Hermes,
ou tout autre) reçoit la liste des capacités du REGISTRE FERMÉ et renvoie un plan
JSON `{"capability": "...", "params": {...}}`.

SÉCURITÉ (audit MSJARVIS) : le plan LLM reste une donnée NON FIABLE. Ce module
se contente de l'EXTRAIRE proprement ; c'est l'orchestrateur (run_plan) qui le
VALIDE fail-closed contre le registre. Un LLM qui hallucine une capacité, injecte
une commande ou renvoie du bruit → plan rejeté en aval, jamais exécuté.

`llm_fn` est injecté (pur, testable, sans réseau ici). Il prend un prompt et
renvoie du texte. Le prompt liste UNIQUEMENT les capacités déclarées.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from domain.agent_registry import list_capabilities

LlmFn = Callable[[str], str]


def build_prompt(texte: str) -> str:
    """Construit le prompt de planification (capacités fermées + consigne stricte)."""
    caps = list_capabilities()
    lignes = [f'  - "{c["id"]}" ({c["mode"]}) : {c["description"]}' for c in caps]
    return (
        "Tu es le planificateur de Titanium. Traduis la demande de l'utilisateur "
        "en UNE capacité de la liste ci-dessous, et RIEN d'autre.\n"
        "Capacités autorisées (aucune autre n'existe) :\n"
        + "\n".join(lignes) +
        "\n\nRéponds UNIQUEMENT par un objet JSON strict : "
        '{"capability": "<id exact de la liste>", "params": {}}.\n'
        "Si la demande ne correspond à AUCUNE capacité, réponds {\"capability\": null}.\n"
        f"\nDemande : {texte}\n"
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_plan(reponse: str) -> Optional[dict]:
    """Extrait le 1er objet JSON d'une réponse LLM (souvent entourée de texte).
    Retourne None si rien d'exploitable ou capability nulle/absente."""
    if not reponse:
        return None
    m = _JSON_RE.search(str(reponse))
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or not obj.get("capability"):
        return None
    # ne garder que les clés attendues (le reste = bruit LLM ignoré)
    plan = {"capability": obj["capability"]}
    if isinstance(obj.get("params"), dict):
        plan["params"] = obj["params"]
    return plan


def plan_from_text(texte: str, llm_fn: LlmFn) -> Optional[dict]:
    """Demande un plan au LLM et l'extrait. None si le LLM ne propose rien
    d'exploitable. Ne VALIDE pas (c'est le rôle de l'orchestrateur) — mais ne
    laisse jamais passer autre chose qu'un dict {capability[, params]}."""
    try:
        reponse = llm_fn(build_prompt(texte))
    except Exception:
        return None
    return extract_plan(reponse)
