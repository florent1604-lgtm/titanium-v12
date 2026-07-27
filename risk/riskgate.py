"""risk/riskgate.py — LA PORTE UNIQUE (N4). Réorg Phase 1b (27/07/2026).

⚠️ CONSTRUIT EN SHADOW — NON CÂBLÉ AU RUNTIME. Consolidation des 7+ contrôles de risque
aujourd'hui dispersés (fondamentaux, circuit breaker, validations pré-entrée, filtre tendance,
filtre de coût, sizing, émotion) en UNE fonction `evaluate(state) -> Decision`. Doit être
validé par comparaison paper avant/après + revue Florent AVANT d'être branché (règle 4 du
prompt + stop N4). Tant qu'il n'est importé par aucun code runtime, il a zéro effet.

INVARIANTS :
- Ne dépend que du socle N0 (`core.state`, `core.config`) — LIT l'état, n'appelle aucun pôle.
- Décision EXPLICITE et journalisable : ALLOW / REDUCE / DENY + motif + taille autorisée, avec
  la trace de CHAQUE contrôle (traçabilité des refus = dataset non censuré).
- Coefficients de sizing (conf_tf, mult_regime, shrink_perf, mult_emotion) NON codés en dur :
  initialisés NEUTRES, destinés à être APPRIS par la mesure (N6, cf. 6.3/6.7). Ici = neutres.

Ordre des contrôles (entonnoir) : HALT → veto fondamentaux → circuit breaker → validations
pré-entrée → filtre tendance → filtre de coût → sizing (émotion+régime) → caps.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.state import SystemState


class RiskCoeffs(BaseModel):
    """Coefficients de sizing — INITIALISÉS NEUTRES, à apprendre (N6). Jamais codés en dur."""
    model_config = ConfigDict(extra="forbid")
    conf_tf: Dict[str, float] = Field(default_factory=dict)   # tf -> facteur (défaut 1.0 = neutre)
    mult_regime: float = 1.0                                  # cohérence spectrale
    shrink_perf: float = 1.0                                  # feedback N6, borné [0.5, 1.2]
    mult_emotion: float = 1.0                                 # modulation émotion (extrêmes)

    def conf_for(self, tf: Optional[str]) -> float:
        return float(self.conf_tf.get(tf or "", 1.0))


class Decision(BaseModel):
    """Décision de la porte unique. Journalisable telle quelle."""
    model_config = ConfigDict(extra="forbid")
    verdict: str = "DENY"                     # ALLOW / REDUCE / DENY
    reason: str = ""
    side: int = 0
    allowed_risk_money: float = 0.0
    size_factor: float = 0.0                  # facteur appliqué (émotion×régime×conf_tf×shrink)
    pillar_size: float = 1.0                  # correction de lot PAR PILIERS (barème RiskGate)
    sl: Optional[float] = None
    tp: Optional[float] = None
    stop_distance: Optional[float] = None
    checks: List[Dict[str, Any]] = Field(default_factory=list)

    def _add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"gate": name, "passed": bool(passed), "detail": detail})


class RiskGate:
    """Porte unique. `evaluate(state)` consolide tous les contrôles et rend une Decision.
    Pure : aucune I/O, aucun ordre — c'est l'appelant (N5) qui exécute un ALLOW/REDUCE."""

    def __init__(self, settings=None, coeffs: Optional[RiskCoeffs] = None,
                 *, cost_ratio_min: float = 2.0, sl_atr_k: float = 1.5,
                 max_exposure_pct: float = 100.0, pillar_ladder: Optional[Dict[int, float]] = None):
        if settings is None:
            from core.config import get_settings
            settings = get_settings()
        self.s = settings
        self.coeffs = coeffs or RiskCoeffs()
        self.cost_ratio_min = cost_ratio_min
        self.sl_atr_k = sl_atr_k
        self.max_exposure_pct = max_exposure_pct
        self.pillar_ladder = pillar_ladder if pillar_ladder is not None else self._load_pillar_ladder()

    @staticmethod
    def _load_pillar_ladder() -> Dict[int, float]:
        """Barème de sizing par piliers depuis la config ('n:facteur,...'). Fail-safe."""
        try:
            import os
            raw = os.getenv("RISKGATE_PILLAR_LADDER", "1:1.0,2:1.0,3:0.8,4:0.55,5:0.55")
            out: Dict[int, float] = {}
            for part in raw.split(","):
                n, f = part.split(":")
                out[int(n.strip())] = float(f.strip())
            return out or {}
        except Exception:
            return {1: 1.0, 2: 1.0, 3: 0.8, 4: 0.55, 5: 0.55}

    def pillar_size(self, n_pillars) -> float:
        """Facteur de lot selon le nb de piliers (aplati/plafonné pour les setups à nombreux
        piliers, cf. données : plus de piliers ≠ meilleur). Défaut 1.0 hors barème."""
        try:
            n = int(n_pillars or 0)
        except (TypeError, ValueError):
            return 1.0
        if n in self.pillar_ladder:
            return float(self.pillar_ladder[n])
        return float(self.pillar_ladder.get(max(self.pillar_ladder) if self.pillar_ladder else 0, 1.0)) if n > (max(self.pillar_ladder) if self.pillar_ladder else 0) else 1.0

    def evaluate(self, state: SystemState) -> Decision:
        d = Decision()
        side = int(state.scoring.side or 0)
        d.side = side

        # 0) HALT souverain (Phase 8.5) — prime sur tout.
        if state.risk.halted:
            d.verdict = "DENY"; d.reason = "HALT_ACTIF"; d._add("halt", False, "HALT actif"); return d
        d._add("halt", True)

        # 1) Veto fondamentaux (les FAITS) — block dur, sinon réduction.
        reduce_factor = 1.0
        if state.fundamentals.would_block:
            d.verdict = "DENY"; d.reason = "FONDAMENTAUX_BLOCK"
            d._add("fundamentals", False, f"risk={state.fundamentals.risk_score}"); return d
        if state.fundamentals.would_reduce:
            reduce_factor *= 0.5
            d._add("fundamentals", True, "réduction (zone intermédiaire)")
        else:
            d._add("fundamentals", True)

        # 2) Circuit breaker (winrate/drawdown).
        if state.risk.circuit_breaker_active:
            d.verdict = "DENY"; d.reason = "CIRCUIT_BREAKER"; d._add("circuit_breaker", False); return d
        d._add("circuit_breaker", True)

        # 3) Validations pré-entrée : sens défini + données de marché exploitables.
        tf = state.market.operational_tf or self.s.confluence_demo_ltf
        frame = state.market.frames.get(tf) if state.market.frames else None
        atr = getattr(frame, "atr", None)
        price = state.market.price or getattr(frame, "last_close", None)
        if side == 0:
            d.verdict = "DENY"; d.reason = "PAS_DE_SENS"; d._add("side", False); return d
        if not price or not atr or atr <= 0:
            d.verdict = "DENY"; d.reason = "DONNEES_INSUFFISANTES"
            d._add("market_data", False, f"price={price} atr={atr}"); return d
        d._add("side", True); d._add("market_data", True, f"tf={tf} atr={atr}")

        # 4) Filtre de TENDANCE anti-fade : ne pas fader une tendance H4 nette (26/07).
        trend = int(state.regime.trend or 0)
        if trend != 0 and side == -trend:
            d.verdict = "DENY"; d.reason = "CONTRE_TENDANCE"
            d._add("trend_align", False, f"side={side} vs trend={trend}"); return d
        d._add("trend_align", True)

        # 5) Sizing — stop normalisé ATR de la TF courante ; coefficients NEUTRES (à apprendre).
        stop = self.sl_atr_k * float(atr)
        equity = state.risk.equity or 0.0
        mult_emotion = self._emotion_mult(state)
        size_factor = (self.coeffs.conf_for(tf) * self.coeffs.mult_regime
                       * self.coeffs.shrink_perf * mult_emotion * reduce_factor)
        risk_base = equity * (self.s.demo_risk_pct / 100.0)
        allowed_risk = max(0.0, risk_base * size_factor)
        d.size_factor = round(size_factor, 4)
        d.pillar_size = round(self.pillar_size(state.scoring.n_pillars), 4)   # correction lot par piliers
        d.stop_distance = round(stop, 8)
        d._add("sizing", True, f"stop={stop:.6g} risk={allowed_risk:.2f} sf={size_factor:.3f}")

        # 6) Filtre de COÛT (gate dur) : mouvement attendu doit couvrir 2×frais+spread+slippage.
        #    Inputs de coût réels = journal MT5 démo (Phase 1c). Absents → check "inconnu", non
        #    bloquant en shadow (à durcir une fois les coûts mesurés câblés dans l'état).
        cost = state.notes.get("roundtrip_cost")
        if cost:
            try:
                if (stop / float(cost)) < self.cost_ratio_min:
                    d.verdict = "DENY"; d.reason = "COUT_TROP_ELEVE"
                    d._add("cost_filter", False, f"ratio={stop/float(cost):.2f}<{self.cost_ratio_min}"); return d
                d._add("cost_filter", True)
            except Exception:
                d._add("cost_filter", True, "coût illisible — ignoré")
        else:
            d._add("cost_filter", True, "coût inconnu (à mesurer Phase 1c)")

        # 7) SL/TP + caps d'exposition.
        sign = 1 if side > 0 else -1
        d.sl = round(price - sign * stop, 8)
        d.tp = round(price + sign * stop * 2.0, 8)     # R:R 2:1 par défaut (à paramétrer/apprendre)
        gross = state.risk.gross_exposure_pct or 0.0
        if gross >= self.max_exposure_pct:
            d.verdict = "DENY"; d.reason = "EXPOSITION_MAX"
            d._add("exposure_cap", False, f"gross={gross}%>={self.max_exposure_pct}%"); return d
        d._add("exposure_cap", True)

        # Verdict : REDUCE si une réduction s'est appliquée, sinon ALLOW.
        d.allowed_risk_money = round(allowed_risk, 2)
        d.verdict = "REDUCE" if (reduce_factor < 1.0 or size_factor < 1.0) else "ALLOW"
        d.reason = "OK" if d.verdict == "ALLOW" else "réduction appliquée"
        return d

    def _emotion_mult(self, state: SystemState) -> float:
        """Modulation émotion : plancher si l'émotion voudrait bloquer, sinon neutre.
        Courbe suiveuse/contrarienne paramétrable = Phase 6b.4 (ici : plancher simple)."""
        if state.emotion.available and state.emotion.would_block:
            return 0.5
        return float(self.coeffs.mult_emotion)


def evaluate(state: SystemState, **kwargs) -> Decision:
    """Raccourci fonctionnel (porte par défaut)."""
    return RiskGate(**kwargs).evaluate(state)
