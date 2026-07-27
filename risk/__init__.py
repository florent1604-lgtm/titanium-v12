"""risk/ — N4 : la PORTE UNIQUE (RiskGate). Sommet de l'entonnoir.

Rien n'atteint l'exécution (N5) sans traverser le RiskGate. Ce paquet ne dépend que du
socle N0 (SystemState) — il LIT l'état, n'appelle aucun pôle (invariant #1).
"""
from risk.riskgate import RiskGate, Decision, RiskCoeffs, evaluate  # noqa: F401
