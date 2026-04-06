"""assistant/plugins — Système de plugins Titan.

Les plugins interceptent les intentions classifiées et répondent
directement (sans LLM) quand la requête est suffisamment claire.

Pipeline de traitement :
  1. IntentClassifier → (intent, confidence)
  2. dispatch() → cherche un plugin compatible
  3. Plugin.handle() → réponse directe si possible
  4. Sinon → LLM (titan_agent.ask_titan)

Ajouter un plugin :
  1. Créer un fichier dans assistant/plugins/
  2. Hériter de TitanPlugin
  3. Déclarer ``intents`` et ``min_confidence``
  4. Implémenter ``handle()``
  5. Importer ici dans _init_plugins()
"""
from __future__ import annotations
import logging
from typing import List, Optional, Dict, Any

from assistant.plugins.base import TitanPlugin

logger = logging.getLogger(__name__)

_plugins: List[TitanPlugin] = []
_initialized = False


def _init_plugins() -> None:
    """Charge tous les plugins disponibles."""
    global _plugins, _initialized
    if _initialized:
        return
    _initialized = True

    for cls_path in [
        ("assistant.plugins.trading_plugin", "TradingPlugin"),
        ("assistant.plugins.system_plugin",  "SystemPlugin"),
    ]:
        module_path, cls_name = cls_path
        try:
            import importlib
            mod    = importlib.import_module(module_path)
            cls    = getattr(mod, cls_name)
            plugin = cls()
            _plugins.append(plugin)
            logger.info("[PLUGIN] %s chargé (intents: %s)", cls_name, plugin.intents)
        except Exception as e:
            logger.debug("[PLUGIN] %s non chargé: %s", cls_name, e)


async def dispatch(
    text: str,
    intent: str,
    confidence: float,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Distribue la requête aux plugins enregistrés.

    Args:
        text:       Texte de l'utilisateur.
        intent:     Intention classifiée.
        confidence: Score de confiance du classificateur (0-1).
        context:    Données contextuelles optionnelles.

    Returns:
        Réponse textuelle du premier plugin qui accepte la requête,
        ou None si aucun plugin ne gère l'intention.
    """
    _init_plugins()
    ctx = context or {}

    for plugin in _plugins:
        if plugin.can_handle(intent, confidence):
            try:
                result = await plugin.handle(text, intent, ctx)
                if result is not None:
                    logger.info(
                        "[PLUGIN] '%s' géré par %s (confiance=%.2f)",
                        intent, plugin.name, confidence,
                    )
                    return result
            except Exception as e:
                logger.warning("[PLUGIN] Erreur %s: %s", plugin.name, e)

    return None


def get_plugins() -> List[TitanPlugin]:
    """Retourne la liste des plugins chargés."""
    _init_plugins()
    return list(_plugins)
