"""assistant/knowledge — Base de connaissances de Titan.

Charge des fichiers JSON depuis ce dossier et injecte
le contenu pertinent dans le contexte du LLM en fonction
de l'intention détectée.

Usage :
    from assistant.knowledge import get_context_for_intent
    extra_ctx = get_context_for_intent("signal")
    # → chaîne formatée à ajouter au system_prompt
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = Path(__file__).parent
_cache: Dict[str, Any] = {}

# Mapping intent → clés de connaissance à injecter
_INTENT_KEYS: Dict[str, List[str]] = {
    "signal":   ["smc", "ob_fvg", "scoring", "indicators"],
    "position": ["paper_trading", "pnl"],
    "risk":     ["risk_management", "circuit_breaker"],
    "report":   ["report_format", "scoring"],
    "optim":    ["optimization"],
    "system":   [],
    "general":  ["symbols"],
}


def _load(name: str) -> Dict[str, Any]:
    """Charge (et met en cache) un fichier JSON de connaissance."""
    if name in _cache:
        return _cache[name]
    path = _KNOWLEDGE_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache[name] = data
        logger.debug("[KNOWLEDGE] Chargé: %s (%d entrées)", name, len(data))
        return data
    except Exception as e:
        logger.warning("[KNOWLEDGE] Erreur chargement %s: %s", name, e)
        return {}


def get_context_for_intent(intent: str) -> str:
    """Retourne un bloc de contexte à injecter dans le prompt LLM.

    Args:
        intent: Intention classifiée (signal, position, risk, …).

    Returns:
        Chaîne vide si aucune connaissance pertinente,
        sinon bloc formaté prêt à être ajouté au system_prompt.
    """
    concepts = _load("trading_concepts")
    keys     = _INTENT_KEYS.get(intent, [])

    parts: List[str] = []
    for key in keys:
        content = concepts.get(key, "")
        if content:
            label = key.upper().replace("_", " ")
            parts.append(f"[{label}] {content}")

    if not parts:
        return ""

    return "\n\n[BASE DE CONNAISSANCES]\n" + "\n".join(parts)


def reload_all() -> None:
    """Vide le cache (rechargement à la prochaine demande)."""
    _cache.clear()
    logger.info("[KNOWLEDGE] Cache vidé")
