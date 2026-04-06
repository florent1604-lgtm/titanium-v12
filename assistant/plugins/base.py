"""assistant/plugins/base.py — Classe de base pour les plugins Titan.

Un plugin intercepte certaines catégories d'intentions et génère
une réponse directe (sans passer par le LLM) si la requête est
suffisamment claire.

Avantages vs LLM direct :
  - Réponse instantanée (< 50ms vs 2-5s)
  - Données exactes depuis l'API interne
  - Pas de hallucination possible
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List


class TitanPlugin(ABC):
    """Classe de base pour les plugins de l'assistant Titan.

    Chaque plugin déclare les intentions qu'il gère (``intents``)
    et le seuil de confiance minimal (``min_confidence``) à partir
    duquel il accepte de traiter la requête.
    """

    #: Nom du plugin (pour les logs)
    name: str = "base"

    #: Noms d'intentions gérées (doit correspondre aux labels du classificateur)
    intents: List[str] = []

    #: Confiance minimale du classificateur pour activer ce plugin
    min_confidence: float = 0.58

    def can_handle(self, intent: str, confidence: float) -> bool:
        """Retourne True si ce plugin peut traiter la requête."""
        return intent in self.intents and confidence >= self.min_confidence

    @abstractmethod
    async def handle(
        self,
        text: str,
        intent: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """Traite la requête et retourne une réponse textuelle.

        Args:
            text:    Texte brut de l'utilisateur.
            intent:  Intention classifiée.
            context: Données contextuelles supplémentaires (ex: état API).

        Returns:
            Réponse textuelle, ou None pour déléguer au LLM.
        """
        ...
