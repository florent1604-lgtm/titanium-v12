"""core/state.py — SystemState : l'ÉTAT PARTAGÉ TYPÉ UNIQUE (N0, socle).

Réorg pyramide (Phase 1.1, 27/07/2026). Aujourd'hui l'état circule via des dicts ad hoc
et ~8 fichiers JSON par moteur. `SystemState` le remplace par UN modèle Pydantic v2 validé
que chaque niveau écrit et lit à travers le socle (jamais par appel direct entre modules).

INVARIANTS respectés :
- #6 « le socle ne dépend de rien » : ce module n'importe AUCUN module métier (que pydantic
  + stdlib). C'est ce qui permet à tous les niveaux d'y accéder sans créer de cycle.
- Blocs immutables là où c'est raisonnable ; l'assemblage reste incrémental (chaque pôle
  remplit son bloc), puis `snapshot()` fige une copie profonde pour le journal.
- Multi-TF de première classe : `market` est un flux unique décrit à plusieurs RÉSOLUTIONS
  (cf. Phase 6.1), pas des sources séparées.

Rien n'importe encore ce module au moment de sa création — adoption progressive (Phase 1.4).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TFFrame(BaseModel):
    """Résumé d'une résolution (timeframe) du flux unique."""
    model_config = ConfigDict(extra="forbid")
    tf: str
    last_close: Optional[float] = None
    atr: Optional[float] = None
    tick_volume: Optional[float] = None          # ⚠️ MT5 CFD = volume de TICKS, pas réel (Phase 9.2)
    last_bar_utc: Optional[datetime] = None
    stale: bool = False                          # fraîcheur (politique MTF)


class MarketBlock(BaseModel):
    """Bloc marché MULTI-TF : le même flux à plusieurs résolutions."""
    model_config = ConfigDict(extra="forbid")
    symbol: Optional[str] = None
    venue: Optional[str] = None                  # crypto / cfd
    price: Optional[float] = None                # prix de référence courant
    frames: Dict[str, TFFrame] = Field(default_factory=dict)   # tf -> frame
    operational_tf: Optional[str] = None         # TF opérationnelle choisie (Phase 6.2)
    dominant_cycle_bars: Optional[float] = None  # du pôle spectral (choix de TF)


class ScoringBlock(BaseModel):
    """Pôle SMC/technique : score sur N critères + biais directionnel."""
    model_config = ConfigDict(extra="forbid")
    score: Optional[float] = None
    max_score: int = 16
    criteria: Dict[str, float] = Field(default_factory=dict)    # nom -> 0/1 (ou poids)
    side: int = 0                                # +1 long / -1 short / 0 neutre
    n_pillars: Optional[int] = None              # confluence (piliers en place)


class RegimeBlock(BaseModel):
    """Pôle géométrique/spectral (geometrix) : régime + structure d'échelles."""
    model_config = ConfigDict(extra="forbid")
    regime: Optional[str] = None                 # ex. trending / ranging / incoherent
    coherence: Optional[float] = None            # cohérence spectrale [0,1]
    dominant_cycle_bars: Optional[float] = None
    trend: int = 0                               # +1 / -1 / 0 (EMA200 HTF)


class FundamentalsBlock(BaseModel):
    """Pôle fondamentaux = LES FAITS (macro/événements), score 0-100."""
    model_config = ConfigDict(extra="forbid")
    risk_score: Optional[float] = None           # 0-100
    level: Optional[str] = None                  # low / medium / high
    would_block: bool = False
    would_reduce: bool = False


class EmotionBlock(BaseModel):
    """Pôle émotion = L'ÉTAT DU MARCHÉ (peur/avidité), distinct des faits. Read-only,
    module le sizing via le RiskGate (n'ouvre jamais de position — invariant 6b.3)."""
    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = None
    valence: Optional[float] = None              # [-1,1]
    arousal: Optional[float] = None              # [0,1]
    intensity: Optional[float] = None            # 0-100
    would_block: bool = False
    would_fade: bool = False                     # biais contrarien aux extrêmes
    available: bool = False


class PositionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    side: int                                    # +1 / -1
    volume: float
    entry: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    pnl: Optional[float] = None
    pillars: Optional[int] = None
    ticket: Optional[int] = None


class PositionsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    open: List[PositionInfo] = Field(default_factory=list)
    count: int = 0


class RiskBlock(BaseModel):
    """État de risque agrégé (renseigné par le RiskGate / portfolio_risk)."""
    model_config = ConfigDict(extra="forbid")
    equity: Optional[float] = None
    gross_exposure_pct: Optional[float] = None
    net_exposure_pct: Optional[float] = None
    circuit_breaker_active: bool = False
    day_start_equity: Optional[float] = None
    halted: bool = False                         # HALT souverain (Phase 8.5)


class SystemState(BaseModel):
    """L'état partagé unique d'un cycle de décision. Assemblé incrémentalement par les
    niveaux, puis figé (`snapshot`) pour journalisation avec son `correlation_id`."""
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    correlation_id: str
    ts_utc: datetime = Field(default_factory=_utcnow)
    market: MarketBlock = Field(default_factory=MarketBlock)
    scoring: ScoringBlock = Field(default_factory=ScoringBlock)
    regime: RegimeBlock = Field(default_factory=RegimeBlock)
    fundamentals: FundamentalsBlock = Field(default_factory=FundamentalsBlock)
    emotion: EmotionBlock = Field(default_factory=EmotionBlock)
    positions: PositionsBlock = Field(default_factory=PositionsBlock)
    risk: RiskBlock = Field(default_factory=RiskBlock)
    pole_status: Dict[str, str] = Field(default_factory=dict)   # pôle -> online/degraded/offline
    notes: Dict[str, str] = Field(default_factory=dict)         # traces libres (ex. dégradation LLM)

    def snapshot(self) -> "SystemState":
        """Copie profonde figée pour le journal (l'état continue d'évoluer par ailleurs)."""
        return self.model_copy(deep=True)

    def to_journal_dict(self) -> dict:
        """Dict JSON-sérialisable pour l'écriture au journal (core/journal.py, Phase 1.2)."""
        return self.model_dump(mode="json")


def new_state(correlation_id: str, *, symbol: Optional[str] = None,
              venue: Optional[str] = None) -> SystemState:
    """Fabrique un état vierge pour un nouveau cycle/signal."""
    st = SystemState(correlation_id=correlation_id)
    if symbol:
        st.market.symbol = symbol
    if venue:
        st.market.venue = venue
    return st
