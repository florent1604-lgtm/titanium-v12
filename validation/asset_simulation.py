"""Pure, dependency-free primitives for the 2026-07-15 asset calibration.

The orchestration/data adapter lives in ``tools/asset_optimizer_m2.py``.  This
module stays importable in the guard venv so execution semantics can be tested
without pandas, NumPy, MetaTrader, or a terminal connection.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping, Sequence


PARTS = (0.33, 0.33, 0.34)
_SAFE_CANDIDATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class CalibrationWindow:
    start: datetime
    dev_end: datetime
    selection_end: datetime
    end: datetime


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    atr: float
    signal: int = 0


@dataclass(frozen=True)
class CostModel:
    spread_bps: float
    slippage_bps: float
    swap_long_bps_per_rollover: float
    swap_short_bps_per_rollover: float
    triple_swap_weekday: int
    commission_bps: float = 0.0
    rollover_multipliers: tuple[float, ...] | None = None
    swap_mode: str | None = None
    swap_long_raw: float | None = None
    swap_short_raw: float | None = None
    point: float | None = None
    contract_size: float | None = None
    currency_base: str | None = None
    currency_profit: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.spread_bps,
            self.slippage_bps,
            self.swap_long_bps_per_rollover,
            self.swap_short_bps_per_rollover,
            self.commission_bps,
        )
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("cost values must be finite")
        if self.spread_bps < 0 or self.slippage_bps < 0 or self.commission_bps < 0:
            raise ValueError("spread, slippage, and commission must be non-negative")
        if self.triple_swap_weekday not in range(7):
            raise ValueError("triple_swap_weekday must use Python weekday 0..6")
        multipliers = self.rollover_multipliers
        if multipliers is None:
            multipliers = tuple(
                3.0 if weekday == self.triple_swap_weekday else 1.0
                for weekday in range(7)
            )
            object.__setattr__(self, "rollover_multipliers", multipliers)
        if len(multipliers) != 7 or any(
            not math.isfinite(float(value)) or float(value) < 0 for value in multipliers
        ):
            raise ValueError("rollover_multipliers must contain seven finite non-negative values")
        raw_swap_fields = (self.swap_long_raw, self.swap_short_raw, self.point)
        if self.swap_mode is None:
            if any(value is not None for value in raw_swap_fields):
                raise ValueError("raw swap fields require swap_mode")
        elif any(value is None or not math.isfinite(float(value)) for value in raw_swap_fields):
            raise ValueError("swap_mode requires finite raw swap values and point")
        elif float(self.point) <= 0:
            raise ValueError("swap point must be positive")
        if self.contract_size is not None and (
            not math.isfinite(float(self.contract_size)) or float(self.contract_size) <= 0
        ):
            raise ValueError("contract_size must be finite and positive")
        if str(self.swap_mode).upper() == "CURRENCY_SYMBOL" and self.contract_size is None:
            raise ValueError("CURRENCY_SYMBOL swap requires contract_size")
        if str(self.swap_mode).upper() == "CURRENCY_SYMBOL" and (
            not str(self.currency_base or "").strip()
            or not str(self.currency_profit or "").strip()
        ):
            raise ValueError(
                "CURRENCY_SYMBOL swap requires currency_base and currency_profit"
            )


@dataclass(frozen=True)
class SimulatedTrade:
    entry_timestamp: datetime
    exit_timestamp: datetime
    side: int
    initial_risk_bps: float
    gross_bps: float
    execution_cost_bps: float
    swap_cost_bps: float
    net_bps: float


def summarize_trade_economics(
    trades: Sequence[SimulatedTrade],
    *,
    trading_day_count: int,
    risk_fraction: float,
    account_balance: float,
    observed_spread_bps: float,
    spread_multiplier: float,
    commission_bps: float,
) -> dict[str, float | int | None]:
    """Summarize the net edge, frequency, cost drag, and spread headroom."""
    numeric = (
        risk_fraction,
        account_balance,
        observed_spread_bps,
        spread_multiplier,
        commission_bps,
    )
    if any(not math.isfinite(float(value)) for value in numeric):
        raise ValueError("economic metric inputs must be finite")
    if isinstance(trading_day_count, bool) or trading_day_count < 1:
        raise ValueError("trading_day_count must be a positive integer")
    if risk_fraction <= 0 or risk_fraction > 1 or account_balance <= 0:
        raise ValueError("risk_fraction and account_balance must be positive")
    if observed_spread_bps < 0 or spread_multiplier <= 0 or commission_bps < 0:
        raise ValueError("spread and commission inputs must be non-negative")
    if not trades:
        return {
            "trades": 0,
            "trades_per_day": 0.0,
            "expectancy_net_bps": None,
            "expectancy_currency": None,
            "net_pnl_per_day_pct": 0.0,
            "net_pnl_per_day_currency": 0.0,
        }

    net = tuple(float(trade.net_bps) for trade in trades)
    gross = tuple(float(trade.gross_bps) for trade in trades)
    execution = tuple(float(trade.execution_cost_bps) for trade in trades)
    swap = tuple(float(trade.swap_cost_bps) for trade in trades)
    wins = tuple(value for value in net if value > 0)
    losses = tuple(value for value in net if value < 0)
    account_returns = tuple(
        trade.net_bps / trade.initial_risk_bps * risk_fraction for trade in trades
    )
    count = len(trades)
    mean_gross = sum(gross) / count
    mean_swap = sum(swap) / count
    total_cost = sum(execution) + sum(swap)
    gross_profit = sum(max(value, 0.0) for value in gross)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = (
        avg_win / abs(avg_loss)
        if avg_win is not None and avg_loss is not None and avg_loss != 0
        else None
    )
    break_even_spread = (mean_gross - mean_swap - commission_bps) / spread_multiplier
    expectancy_return = sum(account_returns) / count
    total_return = sum(account_returns)
    return {
        "trades": count,
        "trades_per_day": count / trading_day_count,
        "expectancy_gross_bps": mean_gross,
        "expectancy_net_bps": sum(net) / count,
        "expectancy_currency": expectancy_return * account_balance,
        "avg_win_net_bps": avg_win,
        "avg_loss_net_bps": avg_loss,
        "payoff_ratio": payoff,
        "avg_execution_cost_bps": sum(execution) / count,
        "avg_swap_cost_bps": mean_swap,
        "total_cost_bps": total_cost,
        "cost_pct_of_gross_profit": total_cost / gross_profit * 100.0 if gross_profit > 0 else None,
        "net_pnl_per_day_pct": total_return / trading_day_count * 100.0,
        "net_pnl_per_day_currency": total_return * account_balance / trading_day_count,
        "break_even_spread_bps": break_even_spread,
        "spread_safety_margin_bps": break_even_spread - observed_spread_bps,
    }


def split_calibration_window(start: datetime, end: datetime) -> CalibrationWindow:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("calibration window timestamps must include a timezone")
    if start >= end:
        raise ValueError("calibration window start must precede end")
    span = end - start
    return CalibrationWindow(
        start=start,
        dev_end=start + span * 0.50,
        selection_end=start + span * 0.70,
        end=end,
    )


def normalize_mt5_category(path: str) -> str:
    category = str(path).split("\\", 1)[0]
    return category[4:] if category.startswith("ROW_") else category


def derive_rollover_multipliers(
    mt5_triple_weekday: int,
    *,
    weekend_open: bool,
) -> tuple[float, ...]:
    """Derive the schedule exposed incompletely by MetaTrader5's Python API.

    MQL weekdays are Sunday=0..Saturday=6; Python uses Monday=0..Sunday=6.
    """
    if (
        isinstance(mt5_triple_weekday, bool)
        or not isinstance(mt5_triple_weekday, int)
        or mt5_triple_weekday not in range(7)
    ):
        raise ValueError("MT5 triple-swap weekday must be an integer in 0..6")
    if not isinstance(weekend_open, bool):
        raise ValueError("weekend_open must be boolean")
    python_triple = (mt5_triple_weekday + 6) % 7
    multipliers = [1.0] * 7
    if not weekend_open:
        multipliers[5] = 0.0
        multipliers[6] = 0.0
    multipliers[python_triple] = 3.0
    return tuple(multipliers)


def bounded_bar_request_count(
    start: datetime,
    end: datetime,
    timeframe_minutes: int,
    terminal_max_bars: int,
    api_request_cap: int = 60_000,
) -> int:
    """Return a conservative MT5 history request capped by terminal policy."""
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("bar request timestamps must be timezone-aware and ordered")
    if (
        isinstance(timeframe_minutes, bool)
        or not isinstance(timeframe_minutes, int)
        or timeframe_minutes < 1
    ):
        raise ValueError("timeframe_minutes must be a positive integer")
    if (
        isinstance(terminal_max_bars, bool)
        or not isinstance(terminal_max_bars, int)
        or terminal_max_bars < 1
    ):
        raise ValueError("terminal_max_bars must be a positive integer")
    if (
        isinstance(api_request_cap, bool)
        or not isinstance(api_request_cap, int)
        or api_request_cap < 1
    ):
        raise ValueError("api_request_cap must be a positive integer")
    requested = math.ceil((end - start).total_seconds() / (timeframe_minutes * 60)) + 2
    return min(requested, terminal_max_bars, api_request_cap)


def chunked_time_ranges(
    start: datetime,
    end: datetime,
    *,
    chunk_days: int,
) -> tuple[tuple[datetime, datetime], ...]:
    """Partition a locked UTC-style window backwards into bounded requests."""
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("chunk timestamps must be timezone-aware and ordered")
    if isinstance(chunk_days, bool) or not isinstance(chunk_days, int) or chunk_days < 1:
        raise ValueError("chunk_days must be a positive integer")
    result = []
    cursor = end
    delta = timedelta(days=chunk_days)
    while cursor > start:
        chunk_start = max(start, cursor - delta)
        result.append((chunk_start, cursor))
        cursor = chunk_start
    return tuple(result)


def swap_bps_per_rollover(
    mode: str,
    raw_swap_value: float,
    *,
    point: float,
    price: float,
    current_price: float | None = None,
    contract_size: float | None = None,
    currency_base: str | None = None,
    currency_profit: str | None = None,
) -> float:
    """Convert a broker swap quote to a return cost in basis points.

    Negative MT5 swap values are costs and therefore become positive here;
    positive broker credits become negative costs. Interest modes use MT5's
    360-day bank year. ``price`` is the position entry price;
    ``current_price`` is the close used for an ``INTEREST_CURRENT`` rollover.
    ``CURRENCY_SYMBOL`` is money in the symbol base currency per lot. It is
    converted to the profit currency when needed, then divided by the entry
    notional to obtain a return.
    """
    values = (raw_swap_value, point, price)
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("swap inputs must be finite")
    if point <= 0 or price <= 0:
        raise ValueError("point and price must be positive")
    normalized_mode = str(mode).upper()
    if normalized_mode == "DISABLED":
        return 0.0
    if normalized_mode in {"POINTS", "REOPEN_CURRENT", "REOPEN_BID"}:
        return -float(raw_swap_value) * point / price * 10_000.0
    if normalized_mode == "INTEREST_OPEN":
        return -float(raw_swap_value) / 360.0 * 100.0
    if normalized_mode == "INTEREST_CURRENT":
        if current_price is None or not math.isfinite(float(current_price)):
            raise ValueError("INTEREST_CURRENT swap requires finite current_price")
        if float(current_price) <= 0:
            raise ValueError("current_price must be positive")
        return (
            -float(raw_swap_value)
            / 360.0
            * 100.0
            * float(current_price)
            / price
        )
    if normalized_mode == "CURRENCY_SYMBOL":
        if contract_size is None or not math.isfinite(float(contract_size)):
            raise ValueError("CURRENCY_SYMBOL swap requires finite contract_size")
        if float(contract_size) <= 0:
            raise ValueError("contract_size must be positive")
        base = str(currency_base or "").strip().upper()
        profit = str(currency_profit or "").strip().upper()
        if not base or not profit:
            raise ValueError(
                "CURRENCY_SYMBOL swap requires currency_base and currency_profit"
            )
        base_to_profit = 1.0
        if base != profit:
            if current_price is None or not math.isfinite(float(current_price)):
                raise ValueError(
                    "cross-currency CURRENCY_SYMBOL swap requires finite current_price"
                )
            if float(current_price) <= 0:
                raise ValueError("current_price must be positive")
            base_to_profit = float(current_price)
        return (
            -float(raw_swap_value)
            * base_to_profit
            / (float(contract_size) * price)
            * 10_000.0
        )
    raise ValueError(f"unsupported swap mode {mode}")


def candidate_id(
    style: str,
    align_ema50: bool,
    rsi_gate: bool,
    sl_atr: float,
    tp_ladder: Sequence[float],
) -> str:
    ladder = "-".join(format(float(value), ".4g") for value in tp_ladder)
    value = (
        f"{style}.a{int(bool(align_ema50))}.r{int(bool(rsi_gate))}."
        f"sl{format(float(sl_atr), '.4g')}.tp{ladder}"
    )
    if not _SAFE_CANDIDATE.fullmatch(value):
        raise ValueError("candidate id is unsafe")
    return value


def fastest_validated_style(reports: Mapping[str, Mapping[str, object]]) -> str | None:
    for style in ("scalp", "intraday", "swing"):
        report = reports.get(style, {})
        if report.get("status") == "VALIDATED_FOR_FORWARD_PAPER":
            return style
    return None


def aggregate_daily_returns(
    trades: Sequence[SimulatedTrade],
    trading_days: Sequence[date],
    *,
    risk_fraction: float | None = None,
) -> tuple[float, ...]:
    if risk_fraction is not None and (
        not math.isfinite(float(risk_fraction)) or risk_fraction <= 0 or risk_fraction > 1
    ):
        raise ValueError("risk_fraction must be in (0, 1]")
    if len(set(trading_days)) != len(trading_days):
        raise ValueError("trading_days must be unique")
    ordered_days = tuple(sorted(trading_days))
    by_day = {day: 0.0 for day in ordered_days}
    for trade in trades:
        day = trade.exit_timestamp.date()
        if day not in by_day:
            raise ValueError("trade exit falls outside the supplied trading-day grid")
        if risk_fraction is None:
            trade_return = trade.net_bps / 10_000.0
        else:
            trade_return = trade.net_bps / trade.initial_risk_bps * risk_fraction
        by_day[day] += trade_return
    return tuple(by_day[day] for day in ordered_days)


def _rollover_units(
    entry: datetime, exit: datetime, rollover_multipliers: Sequence[float]
) -> float:
    if exit < entry:
        raise ValueError("trade exit precedes entry")
    units = 0.0
    day = entry.date()
    while day < exit.date():
        units += float(rollover_multipliers[day.weekday()])
        day += timedelta(days=1)
    return units


def _position_swap_cost_bps(
    bars: Sequence[Bar],
    entry_index: int,
    exit_index: int,
    *,
    entry_price: float,
    entry_timestamp: datetime,
    side: int,
    costs: CostModel,
) -> float:
    exit_timestamp = bars[exit_index].timestamp
    if costs.swap_mode is None:
        per_rollover = (
            costs.swap_long_bps_per_rollover
            if side > 0
            else costs.swap_short_bps_per_rollover
        )
        return _rollover_units(
            entry_timestamp, exit_timestamp, costs.rollover_multipliers
        ) * per_rollover

    raw_swap = costs.swap_long_raw if side > 0 else costs.swap_short_raw
    normalized_mode = str(costs.swap_mode).upper()
    requires_daily_price = normalized_mode == "INTEREST_CURRENT" or (
        normalized_mode == "CURRENCY_SYMBOL"
        and str(costs.currency_base).upper() != str(costs.currency_profit).upper()
    )
    if not requires_daily_price:
        per_rollover = swap_bps_per_rollover(
            costs.swap_mode,
            float(raw_swap),
            point=float(costs.point),
            price=entry_price,
            contract_size=costs.contract_size,
            currency_base=costs.currency_base,
            currency_profit=costs.currency_profit,
        )
        return _rollover_units(
            entry_timestamp, exit_timestamp, costs.rollover_multipliers
        ) * per_rollover

    rollover_prices: dict[date, float] = {}
    for bar in bars[entry_index : exit_index + 1]:
        if bar.timestamp.date() < exit_timestamp.date():
            rollover_prices[bar.timestamp.date()] = bar.close
    total = 0.0
    day = entry_timestamp.date()
    while day < exit_timestamp.date():
        multiplier = float(costs.rollover_multipliers[day.weekday()])
        if multiplier:
            current_price = rollover_prices.get(day)
            if current_price is None:
                raise ValueError(
                    f"missing {normalized_mode} rollover price for {day.isoformat()}"
                )
            total += multiplier * swap_bps_per_rollover(
                costs.swap_mode,
                float(raw_swap),
                point=float(costs.point),
                price=entry_price,
                current_price=current_price,
                contract_size=costs.contract_size,
                currency_base=costs.currency_base,
                currency_profit=costs.currency_profit,
            )
        day += timedelta(days=1)
    return total


def _validate_bars(bars: Sequence[Bar]) -> None:
    previous = None
    for bar in bars:
        values = (bar.open, bar.high, bar.low, bar.close, bar.atr)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("bar values must be finite")
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0 or bar.atr <= 0:
            raise ValueError("bar prices and ATR must be positive")
        if bar.low > min(bar.open, bar.close, bar.high) or bar.high < max(
            bar.open, bar.close, bar.low
        ):
            raise ValueError("bar OHLC is inconsistent")
        if bar.signal not in (-1, 0, 1):
            raise ValueError("bar signal must be -1, 0, or 1")
        if bar.timestamp.tzinfo is None:
            raise ValueError("bar timestamps must include a timezone")
        if previous is not None and bar.timestamp <= previous:
            raise ValueError("bars must be strictly chronological")
        previous = bar.timestamp


def simulate(
    bars: Sequence[Bar],
    *,
    sl_atr: float,
    tp_ladder: Sequence[float],
    time_stop_bars: int,
    costs: CostModel,
) -> tuple[SimulatedTrade, ...]:
    """Simulate next-open entries with conservative SL-before-TP ordering.

    A signal on bar ``i-1`` opens at bar ``i``.  The entry bar itself is
    exposed to SL/TP.  A trade closing during a bar cannot be retroactively
    replaced at that same bar's open.  Any final open position is marked at the
    last close, so losing tail positions cannot disappear from evidence.
    """
    _validate_bars(bars)
    if not math.isfinite(float(sl_atr)) or sl_atr <= 0:
        raise ValueError("sl_atr must be finite and positive")
    ladder = tuple(float(item) for item in tp_ladder)
    if len(ladder) != 3 or any(not math.isfinite(item) or item <= 0 for item in ladder):
        raise ValueError("tp_ladder must contain three finite positive values")
    if tuple(sorted(ladder)) != ladder:
        raise ValueError("tp_ladder must be ascending")
    if isinstance(time_stop_bars, bool) or not isinstance(time_stop_bars, int) or time_stop_bars < 1:
        raise ValueError("time_stop_bars must be a positive integer")
    if len(bars) < 2:
        return ()

    trades: list[SimulatedTrade] = []
    position = None
    for index in range(1, len(bars)):
        bar = bars[index]
        if position is None and bars[index - 1].signal:
            side = bars[index - 1].signal
            entry = bar.open
            atr = bars[index - 1].atr
            stop = entry - side * sl_atr * atr
            targets = tuple(entry + side * multiple * atr for multiple in ladder)
            initial_risk_bps = sl_atr * atr / entry * 10_000.0
            position = {
                "side": side,
                "entry": entry,
                "entry_ts": bar.timestamp,
                "stop": stop,
                "targets": targets,
                "filled": [0.0, 0.0, 0.0],
                "bars": 0,
                "initial_risk_bps": initial_risk_bps,
                "entry_index": index,
            }
        if position is None:
            continue

        side = position["side"]
        entry = position["entry"]
        stop = position["stop"]
        targets = position["targets"]
        filled = position["filled"]
        hit_stop = bar.low <= stop if side > 0 else bar.high >= stop
        exit_price = None
        if hit_stop:
            exit_price = stop
        else:
            for target_index, target in enumerate(targets):
                if filled[target_index] != 0:
                    continue
                hit_target = bar.high >= target if side > 0 else bar.low <= target
                if hit_target:
                    filled[target_index] = PARTS[target_index]
                    if target_index == 0:
                        position["stop"] = entry
            if sum(filled) >= 0.999:
                exit_price = targets[-1]
            else:
                position["bars"] += 1
                if position["bars"] >= time_stop_bars:
                    exit_price = bar.close

        if exit_price is None:
            continue
        gross_fraction = sum(
            part * side * (target - entry) / entry
            for part, target in zip(filled, targets)
            if part
        )
        remaining = 1.0 - sum(filled)
        gross_fraction += remaining * side * (exit_price - entry) / entry
        gross_bps = gross_fraction * 10_000.0
        initial_risk_bps = position["initial_risk_bps"]
        execution_cost = costs.spread_bps + costs.slippage_bps + costs.commission_bps
        swap_cost = _position_swap_cost_bps(
            bars,
            int(position["entry_index"]),
            index,
            entry_price=entry,
            entry_timestamp=position["entry_ts"],
            side=side,
            costs=costs,
        )
        trades.append(
            SimulatedTrade(
                position["entry_ts"],
                bar.timestamp,
                side,
                initial_risk_bps,
                gross_bps,
                execution_cost,
                swap_cost,
                gross_bps - execution_cost - swap_cost,
            )
        )
        position = None

    if position is not None:
        bar = bars[-1]
        side = position["side"]
        entry = position["entry"]
        targets = position["targets"]
        filled = position["filled"]
        gross_fraction = sum(
            part * side * (target - entry) / entry
            for part, target in zip(filled, targets)
            if part
        )
        remaining = 1.0 - sum(filled)
        gross_fraction += remaining * side * (bar.close - entry) / entry
        gross_bps = gross_fraction * 10_000.0
        initial_risk_bps = position["initial_risk_bps"]
        execution_cost = costs.spread_bps + costs.slippage_bps + costs.commission_bps
        swap_cost = _position_swap_cost_bps(
            bars,
            int(position["entry_index"]),
            len(bars) - 1,
            entry_price=entry,
            entry_timestamp=position["entry_ts"],
            side=side,
            costs=costs,
        )
        trades.append(
            SimulatedTrade(
                position["entry_ts"],
                bar.timestamp,
                side,
                initial_risk_bps,
                gross_bps,
                execution_cost,
                swap_cost,
                gross_bps - execution_cost - swap_cost,
            )
        )
    return tuple(trades)
