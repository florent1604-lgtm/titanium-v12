"""Pure strategy function shared by paper execution and validation backtests."""
from __future__ import annotations

from typing import Iterable, List, Sequence

from .models import (
    Action,
    Bar,
    DecisionContext,
    DecisionIntent,
    FrozenCostModel,
    FrozenStrategyConfig,
    MarketSnapshotAtClose,
    PortfolioSnapshot,
)


def _ema(values: Sequence[float], span: int) -> float:
    alpha = 2.0 / (span + 1.0)
    value = float(values[0])
    for item in values[1:]:
        value = alpha * float(item) + (1.0 - alpha) * value
    return value


def _true_ranges(bars: Sequence[Bar]) -> List[float]:
    result: List[float] = []
    previous_close = None
    for bar in bars:
        if previous_close is None:
            result.append(float(bar.high - bar.low))
        else:
            result.append(max(
                float(bar.high - bar.low),
                abs(float(bar.high - previous_close)),
                abs(float(bar.low - previous_close)),
            ))
        previous_close = float(bar.close)
    return result


def _atr(bars: Sequence[Bar], period: int) -> float:
    ranges = _true_ranges(bars)
    window = ranges[-period:]
    return sum(window) / len(window) if window else 0.0


def _intent(
    action: Action,
    market: MarketSnapshotAtClose,
    config: FrozenStrategyConfig,
    context: DecisionContext,
    *,
    side: str | None = None,
    entry_anchor: float | None = None,
    stop: float | None = None,
    targets: Iterable[float] = (),
    max_risk: float = 0.0,
    reasons: Iterable[str] = (),
    assumptions: Iterable[str] = (),
) -> DecisionIntent:
    return DecisionIntent(
        action=action,
        symbol=market.symbol,
        side=side,
        strategy_id=config.strategy_id,
        strategy_version=config.strategy_version,
        decision_bar_id=market.bar_id,
        execute_from_bar_id=context.expected_next_bar_id or market.next_bar_id,
        entry_reference="NEXT_BAR_OPEN" if action is Action.OPEN else None,
        entry_anchor=entry_anchor,
        stop=stop,
        targets=tuple(float(item) for item in targets),
        max_risk=float(max_risk),
        reason_codes=tuple(reasons),
        assumptions=tuple(assumptions),
        decision_ts=market.decision_ts,
    )


def _no_trade(
    market: MarketSnapshotAtClose,
    config: FrozenStrategyConfig,
    context: DecisionContext,
    *reasons: str,
) -> DecisionIntent:
    return _intent(Action.NO_TRADE, market, config, context, reasons=reasons)


def _validate_input(
    market: MarketSnapshotAtClose,
    config: FrozenStrategyConfig,
    context: DecisionContext,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if context.strategy_id != config.strategy_id:
        reasons.append("STRATEGY_ID_MISMATCH")
    if market.timeframe != config.timeframe:
        reasons.append("TIMEFRAME_MISMATCH")
    if not market.closed or not market.bars or not market.bars[-1].closed:
        reasons.append("BAR_NOT_CLOSED")
    if not market.bars or market.bars[-1].bar_id != market.bar_id:
        reasons.append("BAR_ID_MISMATCH")
    if market.source_ts > market.decision_ts:
        reasons.append("SOURCE_AFTER_DECISION")
    else:
        age = (market.decision_ts - market.source_ts).total_seconds()
        if age > config.max_data_age_seconds:
            reasons.append("DATA_STALE")
    if context.expected_next_bar_id is None and market.next_bar_id is None:
        reasons.append("NEXT_BAR_UNKNOWN")
    previous_close = None
    for bar in market.bars:
        if not bar.closed:
            reasons.append("HISTORY_HAS_OPEN_BAR")
        if bar.close_ts > market.decision_ts:
            reasons.append("FUTURE_BAR")
        if previous_close is not None and bar.close_ts < previous_close:
            reasons.append("HISTORY_OUT_OF_ORDER")
        previous_close = bar.close_ts
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            reasons.append("INVALID_OHLC")
    if market.bid <= 0 or market.ask <= 0 or market.ask <= market.bid:
        reasons.append("INVALID_QUOTE")
    else:
        mid = (market.bid + market.ask) / 2.0
        spread_bps = (market.ask - market.bid) / mid * 10000.0
        if spread_bps > config.max_spread_bps:
            reasons.append("SPREAD_TOO_WIDE")
    return tuple(dict.fromkeys(reasons))


def decide_strategy(
    market: MarketSnapshotAtClose,
    portfolio: PortfolioSnapshot,
    config: FrozenStrategyConfig,
    cost_model: FrozenCostModel,
    context: DecisionContext,
) -> DecisionIntent:
    """Decide only from data known at the close of the supplied bar."""
    invalid = _validate_input(market, config, context)
    if invalid:
        return _no_trade(market, config, context, *invalid)
    if not context.calendar_allows_entry:
        return _no_trade(market, config, context, "CALENDAR_BLOCK")
    if any(position.symbol == market.symbol for position in portfolio.positions):
        return _no_trade(market, config, context, "POSITION_ALREADY_OPEN")
    if portfolio.equity <= 0 or not 0 < config.risk_pct <= 1:
        return _no_trade(market, config, context, "INVALID_PORTFOLIO_OR_RISK")
    minimum = max(config.min_history, config.ema_slow + 1, config.atr_period + 1)
    if len(market.bars) < minimum:
        return _no_trade(market, config, context, "INSUFFICIENT_HISTORY")

    closes = [float(bar.close) for bar in market.bars]
    fast_now = _ema(closes, config.ema_fast)
    slow_now = _ema(closes, config.ema_slow)
    fast_previous = _ema(closes[:-1], config.ema_fast)
    slow_previous = _ema(closes[:-1], config.ema_slow)
    if fast_now > slow_now and fast_previous <= slow_previous:
        side = "LONG"
    elif fast_now < slow_now and fast_previous >= slow_previous:
        side = "SHORT"
    else:
        return _no_trade(market, config, context, "NO_CROSS")

    anchor = closes[-1]
    atr = _atr(market.bars, config.atr_period)
    if anchor <= 0 or atr <= 0:
        return _no_trade(market, config, context, "INVALID_VOLATILITY")
    distance = config.stop_atr * atr
    sign = 1.0 if side == "LONG" else -1.0
    stop = anchor - sign * distance
    targets = tuple(anchor + sign * distance * ratio for ratio in config.tp_ratios)
    spread_bps = (market.ask - market.bid) / ((market.ask + market.bid) / 2) * 10000
    assumptions = (
        "entry=NEXT_BAR_OPEN",
        "decision_bar_closed=true",
        "spread_bps=%.4f" % spread_bps,
        "commission_bps=%.4f" % cost_model.commission_bps,
        "slippage_bps=%.4f" % cost_model.slippage_bps,
        "swap_bps_per_bar=%.4f" % cost_model.swap_bps_per_bar,
    )
    return _intent(
        Action.OPEN,
        market,
        config,
        context,
        side=side,
        entry_anchor=anchor,
        stop=stop,
        targets=targets,
        max_risk=portfolio.equity * config.risk_pct,
        reasons=("EMA_CROSS", "NEXT_BAR_EXECUTION"),
        assumptions=assumptions,
    )
