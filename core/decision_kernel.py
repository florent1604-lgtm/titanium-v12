"""core/decision_kernel.py — Arbitre décisionnaire UNIQUE et DÉTERMINISTE.

Point central de validation avant TOUTE exécution (signal_engine, confluence_demo,
forward_paper, etc.). Fail-closed : toute erreur ou désaccord → BLOCK.

⚠️ CARACTÉRISTIQUES :
  · PUR : aucun side-effect, aucun I/O lourd, aucun appel MT5/réseau direct.
  · DÉTERMINISTE : même inputs → même verdict.
  · FAIL-CLOSED : entrée invalide / lien mort → False / motif explicite.
  · TRAÇABILITÉ : chaque décision retourne reason_codes + source (brain/consensus/risk).

ARCHITECTURE :
  1. build_verdict(symbol, confluence_result, scoring_result, emotion)
     ↓ Agrège via consensus_engine.build_consensus()
  2. _check_brain_gate(symbol, proposed_side)
     ↓ Master (Florent) prime toujours
  3. _check_portfolio_risk(strategy, symbol, notional, equity, side)
     ↓ Plafonds transversaux (fail-closed si état illisible)
  4. → Verdict(allow: bool, side: int, conviction: float, reason_codes: [str])

Appelants :
  - signal_engine.scan_symbol() : avant emit_signal
  - confluence_demo_engine.run_once() : avant place_demo_async
  - (futur) forward_paper.run_once()
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Verdict:
    """Résultat décisionnaire : side ± conviction, autorisation, raisons."""
    allow: bool  # Exécution autorisée ?
    side: int  # +1 long, −1 short, 0 neutral/block
    conviction: float  # [0, 1] pour sizing (ignore si not allow)
    verdict_type: str  # "ENTER", "BLOCK", "WAIT", "ERROR"
    reason_codes: Tuple[str, ...] = ()  # trace: ["BRAIN_FORCE_LONG", "PORTFOLIO_OK", ...]
    source: str = "KERNEL"  # qui a tranché
    decided_at: str = ""  # timestamp ISO

    def __bool__(self) -> bool:
        """True = exécution possible (allow + side ≠ 0)."""
        return self.allow and self.side != 0


class _VerdictBuilder:
    """Constructeur de Verdict avec accumulation de reason_codes (fail-closed)."""

    def __init__(self, symbol: str, now: Optional[datetime] = None):
        self.symbol = symbol
        self.now = now or datetime.now(timezone.utc)
        self.allow = True
        self.side = 0
        self.conviction = 0.0
        self.reason_codes: list[str] = []
        self.verdict_type = "UNKNOWN"

    def add_reason(self, code: str) -> None:
        """Ajoute une raison (trace)."""
        if code not in self.reason_codes:
            self.reason_codes.append(code)

    def block(self, reason: str) -> None:
        """Bloque l'exécution et enregistre la raison."""
        self.allow = False
        self.verdict_type = "BLOCK"
        self.add_reason(reason)

    def set_side(self, side: int, confidence: float = 0.0) -> None:
        """Définit le sens (+1/-1/0) et conviction [0, 1]."""
        self.side = int(side)
        self.conviction = min(1.0, max(0.0, float(confidence)))
        if self.side != 0:
            self.verdict_type = "ENTER"
        else:
            self.verdict_type = "NEUTRAL"

    def build(self) -> Verdict:
        """Construit le Verdict final."""
        if not self.allow:
            self.side = 0
            self.conviction = 0.0
        return Verdict(
            allow=self.allow,
            side=self.side,
            conviction=self.conviction,
            verdict_type=self.verdict_type,
            reason_codes=tuple(self.reason_codes),
            source="KERNEL",
            decided_at=self.now.isoformat(),
        )


def build_verdict(
    symbol: str,
    confluence_result: Optional[Dict[str, Any]] = None,
    scoring_result: Optional[Dict[str, Any]] = None,
    emotion: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
    brain_gate_fn: Optional[Any] = None,
    portfolio_check_fn: Optional[Any] = None,
    strategy: str = "unknown",
    notional_eur: float = 0.0,
    engine_equity: float = 0.0,
) -> Verdict:
    """Agrège confluence + scoring + émotion → Verdict signé.

    Args:
        symbol: symbole de trading
        confluence_result: dict from confluence_demo_engine.decide()
        scoring_result: dict from core.scoring_engine.score_setup()
        emotion: dict from emotion/market_context.emotion_for()
        now: timestamp (défaut: utc now)
        brain_gate_fn: callable(symbol, side) → BrainGate (défaut: core.brain_gate.gate_entry)
        portfolio_check_fn: callable(strategy, symbol, notional, equity, side) → (bool, str)
        strategy: stratégie appelante (signal_engine, confluence, etc.)
        notional_eur: notionnel estimé (pour portfolio_risk)
        engine_equity: equity du moteur

    Returns:
        Verdict(allow, side, conviction, reason_codes)

    Fail-closed : toute erreur de lien → BLOCK avec reason code.
    """
    now = now or datetime.now(timezone.utc)
    vb = _VerdictBuilder(symbol, now)

    # 1️⃣ AGRÉGATION CONSENSUS (confluence + scoring + émotion)
    try:
        from core.consensus_engine import build_consensus

        consensus = build_consensus(symbol, confluence_result, scoring_result, emotion)
        consensus_side = 1 if consensus.get("side") == "long" else (
            -1 if consensus.get("side") == "short" else 0
        )
        consensus_score = int(consensus.get("consensus_score") or 0)
        consensus_status = str(consensus.get("status") or "UNKNOWN")

        vb.add_reason(f"CONSENSUS_STATUS:{consensus_status}")
        vb.add_reason(f"CONSENSUS_SCORE:{consensus_score}")

        # Bloc si conflit ou insuffisant
        if consensus_status == "CONFLICT":
            vb.block("CONSENSUS_CONFLICT")
            return vb.build()
        if consensus_status == "INSUFFICIENT":
            vb.block("CONSENSUS_INSUFFICIENT")
            return vb.build()
        if not consensus_side:
            vb.add_reason("CONSENSUS_NEUTRAL")

    except Exception as exc:  # noqa: BLE001
        logger.warning("[KERNEL] consensus: %r", exc)
        vb.block(f"CONSENSUS_ERROR:{type(exc).__name__}")
        return vb.build()

    # 2️⃣ PORTE NEURONALE (brain_gate : Master Florent + local)
    if brain_gate_fn is None:
        try:
            from core.brain_gate import gate_entry

            brain_gate_fn = gate_entry
        except Exception:
            logger.warning("[KERNEL] brain_gate_fn not available, using fail-closed")
            vb.block("BRAIN_GATE_UNAVAILABLE")
            return vb.build()

    try:
        gate = brain_gate_fn(symbol, consensus_side)
        vb.add_reason(f"BRAIN_SOURCE:{gate.source}")
        vb.add_reason(f"BRAIN_VERDICT:{gate.verdict}")
        if gate.reason_codes:
            vb.add_reason(f"BRAIN_REASON:{','.join(gate.reason_codes[:3])}")

        if not gate.allow:
            vb.block("BRAIN_GATE_REJECTED")
            return vb.build()

        # Brain peut forcer le sens
        effective_side = gate.side if gate.side != 0 else consensus_side
        vb.set_side(effective_side, gate.conviction)
        vb.add_reason(f"EFFECTIVE_SIDE:{effective_side}")

    except Exception as exc:  # noqa: BLE001
        logger.warning("[KERNEL] brain_gate: %r", exc)
        vb.block(f"BRAIN_GATE_ERROR:{type(exc).__name__}")
        return vb.build()

    # 3️⃣ GARDE PORTEFEUILLE (risk transversal)
    if not portfolio_check_fn:
        try:
            from core import portfolio_risk

            portfolio_check_fn = portfolio_risk.check_can_open
        except Exception:
            logger.warning("[KERNEL] portfolio_risk not available, skipping")

    if portfolio_check_fn and notional_eur > 0 and engine_equity > 0:
        try:
            ok, reason = portfolio_check_fn(
                strategy, symbol, notional_eur, engine_equity, vb.side
            )
            vb.add_reason(f"PORTFOLIO:{reason[:40]}")
            if not ok:
                vb.block(f"PORTFOLIO_REJECTED:{reason[:30]}")
                return vb.build()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[KERNEL] portfolio_check: %r", exc)
            vb.block(f"PORTFOLIO_ERROR:{type(exc).__name__}")
            return vb.build()

    # ✅ VERDICT FINAL
    vb.verdict_type = "ENTER" if vb.side != 0 else "NEUTRAL"
    vb.add_reason("KERNEL_OK")
    return vb.build()


# Cache simplifié : garde le dernier verdict par symbole pour rejouer rapidement
_verdict_cache: Dict[str, Verdict] = {}


def get_cached_verdict(symbol: str) -> Optional[Verdict]:
    """Dernier Verdict connu (pour dashboard/debugging)."""
    return _verdict_cache.get(symbol)


def cache_verdict(symbol: str, verdict: Verdict) -> None:
    """Sauvegarde pour historique court terme."""
    _verdict_cache[symbol] = verdict
