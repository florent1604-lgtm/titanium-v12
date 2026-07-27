"""core/confluence_gate.py — Portes ET de confluence (méthode de Florent).

Remplace la logique de score ADDITIF (/16) par la confluence de Florent : une
entrée n'est valide que si TOUS les piliers s'alignent sur le MÊME sens. Un pilier
fort ne compense JAMAIS un pilier absent (c'est le défaut de l'additif : un critère
corrélé peut masquer l'absence d'un autre).

Piliers (portes ET, chacun = un critère de collab/FLORENT_ENTRY_METHOD.md) :
  G0 data_valid        — bougies clôturées + données finies (fail-closed).
  G1 trend_sr          — tendance HTF définie ET prix sur un gros niveau S/R.  (n°1)
  G2 fair_value        — prix sur une zone de juste prix (VPOC/HVN).            (n°2)
  G3 liquidity         — sweep de liquidité / FVG dans le sens.                (n°3)
  G4 ote_ob            — dans la golden zone OTE (non invalidée) / OB valide.  (n°4)
  G5 candle_confirmed  — bougie de confirmation confirmée dans le sens.

Modérateurs (PAS des piliers) :
  emotion → WAIT (attendre un meilleur timing, ne pas entrer impulsif) ou BLOCK.  (n°5)
  cost    → BLOCK (frais du vendredi soir / hold week-end ; edge non prouvé en PROD).

Deux MODES (red-team Codex 17/07 — `edge_ok=True` était fail-OPEN) :
  · PROD (require_edge=True, défaut) : FAIL-CLOSED. Aucune entrée RÉELLE tant que
    l'edge n'est pas explicitement prouvé (edge_ok is True). C'est le garde-fou.
  · DÉMO / EXPLORE (require_edge=False) : on teste CHAQUE stratégie sur le compte
    démo MT5 pour MESURER (décision Florent : « on doit backtester chacune, on
    apprend de nos erreurs et on corrige »). L'edge n'est pas exigé — mais la
    confluence, l'émotion et le coût réel (week-end) s'appliquent toujours : on ne
    fausse jamais un résultat, on ne s'interdit jamais d'expérimenter.

Verdict : ENTER / WAIT / BLOCK. Le `rank` sert UNIQUEMENT à classer entre plusieurs
ENTER — jamais à décider. FAIL-CLOSED : toute porte non évaluable ⇒ BLOCK.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

GATE_VERSION = "1.2.0"          # incrémenter à chaque changement de logique de décision


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str
    code: str = ""              # code machine stable (ex: 'G1_TREND_SR', 'G1_TREND_SR_MISSING')


@dataclass(frozen=True)
class Decision:
    verdict: str                       # 'ENTER' | 'WAIT' | 'BLOCK'
    side: int                          # +1 long / −1 short / 0
    gates: List[GateResult] = field(default_factory=list)
    rank: float = 0.0                  # score de CLASSEMENT (non décisionnel)
    reasons: List[str] = field(default_factory=list)
    code: str = ""                     # reason-code stable du verdict
    mode: str = "prod"                 # 'prod' (edge exigé) | 'explore' (démo/labo)
    version: str = GATE_VERSION
    decided_at: Optional[str] = None   # horodatage ISO de la décision
    decision_id: str = ""              # empreinte stable (traçabilité dashboard)
    setup_family: str = ""             # 'continuation' | 'reversal'

    @property
    def entered(self) -> bool:
        return self.verdict == "ENTER"


def _aligned(value: Optional[int], side: int) -> bool:
    """value doit valoir exactement `side` (0/None = pilier absent = échec)."""
    return value is not None and value == side and side != 0


def _decision_id(decided_at: str, side: int, family: str, code: str, mode: str,
                 gates: List[GateResult], rank: float) -> str:
    """Empreinte reproductible d'une décision (pour le dashboard : clic → preuves)."""
    payload = "|".join([decided_at, str(side), family, code, mode, f"{rank:.4f}",
                        ",".join(f"{g.name}:{int(g.passed)}" for g in gates)])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def evaluate(feats: Dict, *, side: Optional[int] = None, require_edge: bool = True,
             decided_at: Optional[datetime] = None) -> Decision:
    """Évalue la confluence. `feats` = sorties DÉJÀ calculées des détecteurs
    (découplé de la donnée, donc pur et testable). Champs attendus :
      data_valid: bool ; trend: int ; setup_side: int|None ;
      setup_family: 'continuation'|'reversal'|None ;
      on_sr_level: bool ; fair_value: bool ; liquidity: int ; ote: int ; candle: int ;
      strengths: {gate: 0..1} (pour le rank) ;
      emotion: {filter_block: int|None, stale: bool, confidence: float, wait: bool} ;
      cost: {edge_ok: bool|None, weekend_block: bool}.
    `side` : doit correspondre à setup_side s'il est fourni explicitement.
    `require_edge` : True = PROD fail-closed (pas d'entrée sans edge prouvé) ;
                     False = DÉMO/EXPLORE (on teste pour mesurer)."""
    mode = "prod" if require_edge else "explore"
    trace_at = (feats.get("_trace") or {}).get("decided_at")
    if decided_at is None and trace_at:
        try:
            decided_at = datetime.fromisoformat(str(trace_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            decided_at = None
    at = (decided_at or datetime.now(timezone.utc))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at_iso = at.isoformat()

    family = ""

    def _decide(verdict, side_, gates_, code_, reasons_, rank_=0.0):
        return Decision(verdict, side_, gates_, rank=rank_, reasons=reasons_, code=code_,
                        mode=mode, decided_at=at_iso,
                        decision_id=_decision_id(at_iso, side_, family, code_, mode, gates_, rank_),
                        setup_family=family)

    # Porte 0 — données valides : préalable absolu (fail-closed).
    if not feats.get("data_valid", False):
        g = [GateResult("data_valid", False, "données non clôturées/valides", "G0_DATA_INVALID")]
        return _decide("BLOCK", 0, g, "BLOCK_DATA_INVALID", ["G0 données invalides → BLOCK"])

    try:
        trend = int(feats.get("trend", 0) or 0)
        setup_side = feats.get("setup_side")
        setup_side = int(setup_side) if setup_side is not None else None
    except (TypeError, ValueError):
        g = [GateResult("setup", False, "contrat setup non numérique", "G1_SETUP_INVALID")]
        return _decide("BLOCK", 0, g, "BLOCK_SETUP_INVALID", ["Setup invalide → BLOCK"])

    family_raw = feats.get("setup_family")
    if setup_side in (None, 0) and family_raw in (None, ""):
        g = [GateResult("setup", False, "aucun setup déclaré", "G1_NO_SETUP")]
        return _decide("WAIT", 0, g, "WAIT_NO_SETUP",
                       ["Aucun setup continuation/reversal à évaluer → WAIT"])

    family = str(family_raw or "").lower()
    try:
        explicit_side = int(side) if side is not None else setup_side
    except (TypeError, ValueError):
        explicit_side = None
    if (setup_side not in (-1, 1) or explicit_side not in (-1, 1)
            or explicit_side != setup_side or family not in ("continuation", "reversal")):
        g = [GateResult("setup", False, "side/famille de setup incohérents", "G1_SETUP_INVALID")]
        return _decide("BLOCK", 0, g, "BLOCK_SETUP_INVALID",
                       ["Setup incomplet ou incohérent → BLOCK"])
    side = setup_side

    gates: List[GateResult] = [GateResult("data_valid", True, "OK", "G0_OK")]

    # G1 structure : deux familles de setup (conseil archi Codex, demande Florent « ne pas
    # trop restreindre » : les reversals contre-tendance à un niveau sont autorisés).
    #  · CONTINUATION : exige tendance alignée ET sur niveau S/R.
    #  · REVERSAL : exige sur niveau S/R ; la tendance n'est qu'un CONTEXTE
    #    (elle ne bloque pas), la confirmation venant des autres piliers (liquidité/OTE/bougie).
    is_reversal = family == "reversal"
    structure_ok = bool(feats.get("on_sr_level")) and (True if is_reversal else _aligned(trend, side))
    structure_desc = ("setup reversal sur niveau S/R (tendance = contexte)" if is_reversal
                      else "tendance HTF + sur niveau S/R")

    # Piliers ET (tous doivent s'aligner sur `side`).
    checks = [
        ("trend_sr",  structure_ok, structure_desc, "G1_TREND_SR"),
        ("fair_value", bool(feats.get("fair_value")),
         "sur zone de juste prix (VPOC/HVN)", "G2_FAIR_VALUE"),
        ("liquidity", _aligned(feats.get("liquidity"), side),
         "sweep/FVG dans le sens", "G3_LIQUIDITY"),
        ("ote_ob",    _aligned(feats.get("ote"), side),
         "golden zone OTE valide / OB non cassé", "G4_OTE_OB"),
        ("candle_confirmed", _aligned(feats.get("candle"), side),
         "bougie de confirmation dans le sens", "G5_CANDLE"),
    ]
    for name, ok, desc, base_code in checks:
        gates.append(GateResult(name, bool(ok), desc if ok else f"MANQUE : {desc}",
                                base_code if ok else f"{base_code}_MISSING"))

    failed = [g.name for g in gates if not g.passed]
    if failed:
        return _decide("BLOCK", side, gates, "BLOCK_PILLAR_MISSING",
                       [f"Confluence incomplète, manque : {', '.join(failed)} → BLOCK"])

    # Modérateurs (les piliers sont tous alignés).
    emo = feats.get("emotion")
    cost = feats.get("cost")
    if (not isinstance(emo, dict)
            or not {"filter_block", "stale", "confidence", "wait"}.issubset(emo)):
        return _decide("BLOCK", side, gates, "BLOCK_EMOTION_UNAVAILABLE",
                       ["Émotion indisponible/incomplète → BLOCK"])
    if (not isinstance(cost, dict)
            or not {"edge_ok", "weekend_block"}.issubset(cost)):
        return _decide("BLOCK", side, gates, "BLOCK_COST_UNAVAILABLE",
                       ["Coût indisponible/incomplet → BLOCK"])
    if _aligned(emo.get("filter_block"), side):
        return _decide("BLOCK", side, gates, "BLOCK_EMOTION_SIDE",
                       ["Émotion BLOQUE ce côté (ex: ne pas acheter l'euphorie) → BLOCK"])
    if cost.get("weekend_block"):
        return _decide("BLOCK", side, gates, "BLOCK_COST_WEEKEND",
                       ["Coût : frais du vendredi soir / hold week-end → BLOCK"])

    # Coût/edge : FAIL-CLOSED en PROD (Codex : ne jamais laisser passer sans edge prouvé).
    edge_ok = cost.get("edge_ok")
    if edge_ok is False:                              # edge explicitement négatif → BLOCK partout
        return _decide("BLOCK", side, gates, "BLOCK_EDGE_NEGATIVE",
                       ["Coût : edge attendu < coût accepté → BLOCK"])
    if require_edge and edge_ok is not True:          # PROD : edge non prouvé → pas d'entrée réelle
        return _decide("BLOCK", side, gates, "BLOCK_EDGE_UNPROVEN",
                       ["PROD : edge non prouvé (labo requis) → BLOCK. "
                        "Utiliser le mode DÉMO/EXPLORE pour tester et mesurer."])

    if emo.get("stale") or emo.get("wait") or (emo.get("confidence", 1.0) < 0.35):
        return _decide("WAIT", side, gates, "WAIT_EMOTION_TIMING",
                       ["Émotion : timing pas mûr (attendre, ne pas entrer impulsif) → WAIT"])

    # Tous piliers alignés + modérateurs OK → ENTER. rank = qualité (classement seul).
    st = feats.get("strengths") or {}
    rank = round(sum(float(st.get(g.name, 0.0)) for g in gates if g.passed), 3)
    tag = "LONG" if side > 0 else "SHORT"
    note = "" if mode == "prod" else " [DÉMO/EXPLORE : pris pour mesurer]"
    return _decide("ENTER", side, gates, "ENTER_CONFLUENCE",
                   [f"Confluence complète {tag} → ENTER (rank {rank}){note}"], rank_=rank)
