"""Immutable input/output models for the strategy contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class Action(str, Enum):
    NO_TRADE = "NO_TRADE"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"
    REVERSE = "REVERSE"


@dataclass(frozen=True)
class Bar:
    bar_id: str
    open_ts: datetime
    close_ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    closed: bool = True


@dataclass(frozen=True)
class MarketSnapshotAtClose:
    symbol: str
    timeframe: str
    bars: Tuple[Bar, ...]
    bar_id: str
    closed: bool
    source_ts: datetime
    decision_ts: datetime
    bid: float
    ask: float
    next_bar_id: Optional[str] = None


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    side: str
    quantity: float = 0.0
    entry_price: float = 0.0


@dataclass(frozen=True)
class PortfolioSnapshot:
    equity: float
    cash: float
    positions: Tuple[OpenPosition, ...] = ()
    realized_pnl: float = 0.0
    drawdown_pct: float = 0.0


@dataclass(frozen=True)
class FrozenStrategyConfig:
    strategy_id: str = "ema_cross_swing"
    strategy_version: str = "1.0.0"
    timeframe: str = "H4"
    ema_fast: int = 50
    ema_slow: int = 200
    atr_period: int = 14
    min_history: int = 220
    stop_atr: float = 2.0
    tp_ratios: Tuple[float, ...] = (1.5, 2.5, 4.0)
    risk_pct: float = 0.01
    max_spread_bps: float = 25.0
    max_data_age_seconds: int = 900


@dataclass(frozen=True)
class FrozenCostModel:
    account_currency: str = "EUR"
    commission_bps: float = 4.0
    slippage_bps: float = 2.0
    swap_bps_per_bar: float = 0.0
    spread_bps_fallback: float = 0.0


@dataclass(frozen=True)
class DecisionContext:
    strategy_id: str
    run_id: str
    expected_next_bar_id: Optional[str]
    session: str = "UNKNOWN"
    calendar_allows_entry: bool = True


@dataclass(frozen=True)
class DecisionIntent:
    action: Action
    symbol: str
    side: Optional[str]
    strategy_id: str
    strategy_version: str
    decision_bar_id: str
    execute_from_bar_id: Optional[str]
    entry_reference: Optional[str]
    entry_anchor: Optional[float]
    stop: Optional[float]
    targets: Tuple[float, ...]
    max_risk: float
    reason_codes: Tuple[str, ...]
    assumptions: Tuple[str, ...]
    decision_ts: datetime

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["decision_ts"] = self.decision_ts.isoformat()
        payload["targets"] = list(self.targets)
        payload["reason_codes"] = list(self.reason_codes)
        payload["assumptions"] = list(self.assumptions)
        return payload
