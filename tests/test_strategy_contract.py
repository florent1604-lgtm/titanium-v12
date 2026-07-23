from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain.models import (
    Action,
    Bar,
    DecisionContext,
    FrozenCostModel,
    FrozenStrategyConfig,
    MarketSnapshotAtClose,
    PortfolioSnapshot,
)
from domain.strategy import decide_strategy


def _market(closes, *, closed=True, source_age=0):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for index, close in enumerate(closes):
        value = float(close)
        bars.append(Bar(
            bar_id=f"H4-{index}",
            open_ts=base + timedelta(hours=4 * index),
            close_ts=base + timedelta(hours=4 * index + 4),
            open=value,
            high=value + 1.0,
            low=value - 1.0,
            close=value,
            volume=100.0,
            closed=closed,
        ))
    decision_ts = bars[-1].close_ts
    source_ts = decision_ts - timedelta(seconds=source_age)
    return MarketSnapshotAtClose(
        symbol="USTECH",
        timeframe="H4",
        bars=tuple(bars),
        bar_id=bars[-1].bar_id,
        closed=closed,
        source_ts=source_ts,
        decision_ts=decision_ts,
        bid=float(closes[-1]) - 0.5,
        ask=float(closes[-1]) + 0.5,
        next_bar_id=f"H4-{len(bars)}",
    )


def _context(next_bar="H4-next"):
    return DecisionContext(
        strategy_id="ema_cross_swing",
        run_id="test-run",
        expected_next_bar_id=next_bar,
    )


def test_open_intent_is_next_bar_only_and_deterministic():
    market = _market([100.0] * 219 + [400.0])
    config = FrozenStrategyConfig(min_history=220)
    portfolio = PortfolioSnapshot(equity=10_000.0, cash=10_000.0)
    cost = FrozenCostModel()

    first = decide_strategy(market, portfolio, config, cost, _context())
    second = decide_strategy(market, portfolio, config, cost, _context())

    assert first.to_dict() == second.to_dict()
    assert first.action is Action.OPEN
    assert first.side == "LONG"
    assert first.execute_from_bar_id == "H4-next"
    assert first.entry_reference == "NEXT_BAR_OPEN"
    assert first.decision_bar_id == "H4-219"


def test_open_bar_is_a_hard_no_trade():
    market = _market([100.0] * 219 + [400.0], closed=False)
    intent = decide_strategy(
        market,
        PortfolioSnapshot(equity=10_000.0, cash=10_000.0),
        FrozenStrategyConfig(min_history=220),
        FrozenCostModel(),
        _context(),
    )
    assert intent.action is Action.NO_TRADE
    assert "BAR_NOT_CLOSED" in intent.reason_codes


def test_stale_data_and_open_position_are_explicit_no_trade():
    stale = _market([100.0] * 219 + [400.0], source_age=901)
    config = FrozenStrategyConfig(min_history=220, max_data_age_seconds=900)
    intent = decide_strategy(
        stale,
        PortfolioSnapshot(equity=10_000.0, cash=10_000.0),
        config,
        FrozenCostModel(),
        _context(),
    )
    assert intent.action is Action.NO_TRADE
    assert "DATA_STALE" in intent.reason_codes

