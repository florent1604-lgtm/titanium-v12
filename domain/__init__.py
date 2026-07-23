"""Pure, deterministic trading-domain primitives shared by paper and backtest."""

from .models import (
    Action,
    Bar,
    DecisionContext,
    DecisionIntent,
    FrozenCostModel,
    FrozenStrategyConfig,
    MarketSnapshotAtClose,
    OpenPosition,
    PortfolioSnapshot,
)
from .strategy import decide_strategy

__all__ = [
    "Action",
    "Bar",
    "DecisionContext",
    "DecisionIntent",
    "FrozenCostModel",
    "FrozenStrategyConfig",
    "MarketSnapshotAtClose",
    "OpenPosition",
    "PortfolioSnapshot",
    "decide_strategy",
]
