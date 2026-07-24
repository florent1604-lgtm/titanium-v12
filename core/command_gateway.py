"""core/command_gateway.py — Porte d'ORDRES EventPlane (C1 SHADOW → C1 WRITE).

Futur : Hermes proposera des ordres via CommandRequest → EventPlane.
Aujourd'hui (C1 SHADOW) : structure figée, ZÉRO handlers, aucun effet.

Réservé pour phase C2 (Hermes autonome local, PolicyKernel déterministe).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CommandRequest:
    """Proposition d'ordre (Hermes → PolicyKernel)."""
    symbol: str
    side: str  # "long" | "short"
    size_factor: float  # [0, 1] conviction
    strategy: str  # signal_engine, confluence, swing, forex, crypto
    reason: str  # trace
    proposed_at: str = ""  # timestamp ISO
    decision_id: str = ""  # lien vers EventPlane decision
    
    def __post_init__(self):
        if not self.proposed_at:
            object.__setattr__(self, "proposed_at", datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class CommandAuthorization:
    """Verdict de PolicyKernel (déterministe, jamais IA)."""
    allowed: bool
    reason: str
    authorized_at: str = ""
    authorizations: Dict[str, Any] = field(default_factory=dict)  # {policy: result}
    
    def __post_init__(self):
        if not self.authorized_at:
            object.__setattr__(self, "authorized_at", datetime.now(timezone.utc).isoformat())


class PolicyKernel:
    """Arbitre déterministe C1 : aucune IA, contrat figé.
    
    Phase C1 SHADOW : aucun handler, aucun effet. Structure figée pour audit.
    """
    
    def __init__(self):
        self.authorizations: List[CommandAuthorization] = []
    
    def evaluate_command(self, cmd: CommandRequest) -> CommandAuthorization:
        """Évalue un CommandRequest. C1 SHADOW retourne TOUJOURS False."""
        # C1 SHADOW : zero handlers, no dispatch permitted
        return CommandAuthorization(
            allowed=False,
            reason="C1_SHADOW: authorizations disabled (await C2)",
            authorizations={},
        )
    
    def authorize(self, cmd: CommandRequest) -> bool:
        """True = l'ordre peut être exécuté. C1 SHADOW = jamais."""
        auth = self.evaluate_command(cmd)
        self.authorizations.append(auth)
        return auth.allowed


# Instance singleton (C1 SHADOW)
_policy_kernel = PolicyKernel()


def get_policy_kernel() -> PolicyKernel:
    """Accès au noyau de politique (lecture seule jusqu'à C2)."""
    return _policy_kernel


async def request_order(cmd: CommandRequest) -> bool:
    """Demande d'ordre asynchrone → PolicyKernel.
    
    Retourne : True = exécuter, False = bloquer.
    
    C1 SHADOW : retourne TOUJOURS False (aucun effet).
    C2+ : integration avec EventPlane write + Hermes autonomy.
    """
    kernel = get_policy_kernel()
    allowed = kernel.authorize(cmd)
    
    if allowed:
        logger.info(f"[GATEWAY] Order AUTHORIZED: {cmd.symbol} {cmd.side}")
    else:
        logger.debug(f"[GATEWAY] Order BLOCKED: {cmd.symbol} (C1 SHADOW or policy denied)")
    
    return allowed
