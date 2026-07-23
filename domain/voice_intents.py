"""domain/voice_intents.py — Mappage déterministe intention vocale → capacité.

Slice 3 (patron A) : traduit une commande en langage naturel vers l'ID d'une
capacité DU REGISTRE FERMÉ (domain/agent_registry.py). Pur, sans réseau, sans
LLM, entièrement testable. Le cerveau JARVIS appelle ceci PUIS l'orchestrateur ;
si aucune intention ne matche → None → repli sur Hermes/Claude/Ollama.

Ne renvoie JAMAIS autre chose qu'un ID de capacité connu (ou None) : c'est une
seconde barrière (après le registre fermé) contre l'exécution arbitraire.
"""
from __future__ import annotations

import unicodedata
from typing import Optional

from domain.agent_registry import get_capability


def _norm(texte: str) -> str:
    """minuscule + sans accents pour un matching robuste."""
    t = unicodedata.normalize("NFD", str(texte).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# Règles ordonnées : la 1re dont TOUS/au moins un motif matche gagne.
# (motifs, capability_id). Les MUTATE exigent des verbes d'action explicites.
# Règles resserrées « spécifiques trading » : l'orchestrateur passe AVANT le
# reste du routage JARVIS, donc les motifs doivent éviter les faux positifs de
# conversation courante (« risque de pluie », « performance du PC »…).
_RULES = [
    # ── ACTIONS (MUTATE) — verbes explicites d'abord ────────────────────────
    (("lance", "scan", "swing"), "run_swing_scan"),
    (("scanne", "swing"), "run_swing_scan"),
    (("lance", "scan", "opportunit"), "run_opportunity_scan"),
    (("scanne", "opportunit"), "run_opportunity_scan"),
    (("lance", "opportunit"), "run_opportunity_scan"),
    (("reinitialise", "circuit"), "reset_circuit_breaker"),
    (("reset", "circuit"), "reset_circuit_breaker"),
    (("debloque", "circuit"), "reset_circuit_breaker"),
    # ── LECTURES (READ) — motifs trading spécifiques ─────────────────────────
    (("exposition",), "get_risk_exposure"),
    (("plafond",), "get_risk_exposure"),
    (("risque", "portefeuille"), "get_risk_exposure"),
    (("risque", "portfolio"), "get_risk_exposure"),
    (("positions",), "get_positions"),          # pluriel = plus spécifique
    (("position", "ouvert"), "get_positions"),
    (("statut", "swing"), "get_swing_status"),
    (("etat", "swing"), "get_swing_status"),
    (("moteur", "swing"), "get_swing_status"),
    (("swing",), "get_swing_status"),
    (("opportunit",), "get_opportunities"),
    (("pnl",), "get_pnl"),
    (("p&l",), "get_pnl"),
    (("combien", "gagn"), "get_pnl"),
    (("combien", "perd"), "get_pnl"),
    (("equity",), "get_pnl"),
    (("paper", "trading"), "get_pnl"),
]


def map_intent(texte: str) -> Optional[str]:
    """Retourne l'ID de capacité correspondant, ou None si aucune intention.
    Garantie : l'ID retourné existe dans le registre fermé (sinon None)."""
    t = _norm(texte)
    for patterns, cap_id in _RULES:
        if all(p in t for p in patterns):
            # double barrière : ne renvoyer que si la capacité existe vraiment
            return cap_id if get_capability(cap_id) else None
    return None


def is_mutating(cap_id: str) -> bool:
    cap = get_capability(cap_id)
    return bool(cap and cap.mode == "MUTATE")


# ── Confirmation vocale des mutations (P0 revue Codex) ────────────────────────
# Une transcription (ASR) ne doit JAMAIS déclencher une mutation directement :
# une erreur de reconnaissance pourrait lancer un scan ou réinitialiser un garde.
# Toute mutation vocale exige une CONFIRMATION séparée, avec TTL court.
import time as _time

_CONFIRM = ("confirme", "confirmer", "je confirme", "oui confirme", "valide", "vas-y")
_CANCEL = ("annule", "annuler", "laisse tomber", "non merci", "stop")


class VoiceMutationGate:
    """File d'attente à une entrée : une mutation proposée doit être confirmée
    par une commande séparée avant expiration (TTL). Injecte `clock` pour tester."""

    def __init__(self, ttl_seconds: float = 30.0, clock=_time.monotonic):
        self.ttl = ttl_seconds
        self._clock = clock
        self._pending: Optional[str] = None
        self._expiry: float = 0.0

    def has_pending(self) -> bool:
        return self._pending is not None and self._clock() < self._expiry

    def propose(self, cap_id: str, description: str) -> str:
        self._pending = cap_id
        self._expiry = self._clock() + self.ttl
        return (f"Confirmez-vous : {description} ? "
                f"Dites « confirme » dans les {int(self.ttl)} secondes, ou « annule ».")

    def is_confirmation(self, texte: str) -> bool:
        t = _norm(texte)
        return any(w in t for w in _CONFIRM)

    def is_cancellation(self, texte: str) -> bool:
        t = _norm(texte)
        return any(w in t for w in _CANCEL)

    def take_confirmed(self) -> Optional[str]:
        """Retourne la capacité en attente si valide/non expirée, puis vide la
        file. None si rien en attente ou expiré."""
        cap = self._pending if self.has_pending() else None
        self._pending, self._expiry = None, 0.0
        return cap

    def clear(self) -> None:
        self._pending, self._expiry = None, 0.0
