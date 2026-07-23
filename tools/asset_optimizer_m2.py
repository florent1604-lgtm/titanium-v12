"""Leakage-resistant M2 calibration for the Axi MT5 demo universe.

This supersedes the contaminated pass1/pass2 *research path* without changing
the legacy functions imported by ``core.opportunity_scan``.  It is data-only:
there is no order function in this module and every MT5 read rechecks demo
login 50061786.

Protocol (pre-registered in code):
  * common wall-clock window for M15, H1 and H4 per asset;
  * 50% dev + 20% selection (70% IS), then 30% locked final;
  * 36 fixed candidates per style, no adaptive refinement;
  * one final evaluation for the selection winner of each style;
  * family multiplicity = 108 candidates per asset;
  * proposal rule = fastest style that reaches VALIDATED_FOR_FORWARD_PAPER.

Outputs are proposals under ``data/calibration_2026-07-15``.  This script never
writes ``data/asset_configs.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.mt5_provider import mt5_lock  # noqa: E402
from tools.asset_optimizer import ENTRY_VARIANTS, GRIDS, KEEP_CATS, entries  # noqa: E402
from tools.strategy_lab import add_indicators  # noqa: E402
from validation.asset_simulation import (  # noqa: E402
    Bar,
    CostModel,
    aggregate_daily_returns,
    candidate_id,
    chunked_time_ranges,
    derive_rollover_multipliers,
    fastest_validated_style,
    normalize_mt5_category,
    simulate,
    split_calibration_window,
    summarize_trade_economics,
    swap_bps_per_rollover,
)
from validation.harness import (  # noqa: E402
    Segment,
    ValidationGate,
    ValidationPlan,
    run_validation,
)


DEMO_LOGIN = 50061786
PROTOCOL_VERSION = "asset-calibration-m2/2026-07-15-v6"
DEFAULT_OUTPUT = ROOT / "data" / "calibration_2026-07-15"
TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240}
STYLE_PROTOCOL = {
    "scalp": {"tf": "M15", "time_stop": 32},
    "intraday": {"tf": "H1", "time_stop": 48},
    "swing": {"tf": "H4", "time_stop": 60},
}
FAMILY_TRIALS = sum(len(GRIDS[style]) * len(ENTRY_VARIANTS) for style in STYLE_PROTOCOL)
QUOTE_ATTEMPTS = 5
QUOTE_RETRY_SECONDS = 0.2


class DataSpecInvalidError(RuntimeError):
    """The broker symbol specification cannot support a cost snapshot."""


@dataclass(frozen=True)
class Candidate:
    name: str
    style: str
    align_ema50: bool
    rsi_gate: bool
    sl_atr: float
    tp_ladder: tuple[float, float, float]


def _atomic_json_write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                _json_safe(value),
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _safe_symbol(symbol: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in symbol)


def _assert_demo(mt5: Any) -> Any:
    account = mt5.account_info()
    if account is None or int(getattr(account, "login", 0)) != DEMO_LOGIN:
        actual = None if account is None else int(getattr(account, "login", 0))
        raise RuntimeError(f"calibration requires MT5 demo login {DEMO_LOGIN}; got {actual}")
    return account


def _connect_demo() -> Any:
    import MetaTrader5 as mt5

    with mt5_lock:
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        _assert_demo(mt5)
    return mt5


def _tf_constant(mt5: Any, timeframe: str) -> int:
    return {
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
    }[timeframe]


def _swap_mode_name(mt5: Any, value: int) -> str:
    names = (
        "DISABLED",
        "POINTS",
        "CURRENCY_SYMBOL",
        "CURRENCY_MARGIN",
        "CURRENCY_DEPOSIT",
        "INTEREST_CURRENT",
        "INTEREST_OPEN",
        "REOPEN_CURRENT",
        "REOPEN_BID",
    )
    for name in names:
        constant = getattr(mt5, f"SYMBOL_SWAP_MODE_{name}", None)
        if constant is not None and value == constant:
            return name
    return f"UNKNOWN_{value}"


def _positive_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0.0 else 0.0


def _resolve_point(info: Any, symbol: str) -> tuple[float, str]:
    point = _positive_float(getattr(info, "point", 0.0))
    if point:
        return point, "point"
    tick_size = _positive_float(getattr(info, "trade_tick_size", 0.0))
    if tick_size:
        return tick_size, "trade_tick_size"
    try:
        digits = int(getattr(info, "digits", -1))
    except (TypeError, ValueError):
        digits = -1
    if 0 <= digits <= 12:
        return 10.0 ** -digits, "digits"
    raise DataSpecInvalidError(
        f"invalid point for {symbol}: point={getattr(info, 'point', None)!r}, "
        f"trade_tick_size={getattr(info, 'trade_tick_size', None)!r}, "
        f"digits={getattr(info, 'digits', None)!r}"
    )


def _cost_snapshot(
    mt5: Any,
    symbol: str,
    spread_multiplier: float,
    commission_bps: float,
) -> dict[str, object]:
    with mt5_lock:
        account = _assert_demo(mt5)
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"cannot select symbol {symbol}")
    info = None
    tick = None
    point = 0.0
    point_source = ""
    bid = ask = mid = 0.0
    quote_attempts = 0
    for quote_attempts in range(1, QUOTE_ATTEMPTS + 1):
        with mt5_lock:
            _assert_demo(mt5)
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
        if info is None:
            raise DataSpecInvalidError(f"symbol_info unavailable for {symbol}")
        point, point_source = _resolve_point(info, symbol)
        bid = _positive_float(getattr(tick, "bid", 0.0)) or _positive_float(
            getattr(info, "bid", 0.0)
        )
        ask = _positive_float(getattr(tick, "ask", 0.0)) or _positive_float(
            getattr(info, "ask", 0.0)
        )
        mid = (bid + ask) / 2.0 if bid and ask else max(bid, ask)
        if mid:
            break
        if quote_attempts < QUOTE_ATTEMPTS:
            time.sleep(QUOTE_RETRY_SECONDS)
    if not mid:
        raise DataSpecInvalidError(
            f"invalid price for {symbol} after {quote_attempts} attempts: "
            f"bid={bid!r}, ask={ask!r}"
        )
    spread_points = max(
        _positive_float(getattr(info, "spread", 0.0)),
        (ask - bid) / point if bid and ask and ask >= bid else 0.0,
    )
    spread_bps = spread_points * point / mid * 10_000.0
    category = normalize_mt5_category(str(info.path))
    swap_mode = int(getattr(info, "swap_mode", -1))
    swap_mode_name = _swap_mode_name(mt5, swap_mode)
    swap_long_raw = float(info.swap_long)
    swap_short_raw = float(info.swap_short)
    trade_contract_size = _positive_float(
        getattr(info, "trade_contract_size", 0.0)
    )
    currency_base = str(getattr(info, "currency_base", "") or "").strip()
    currency_profit = str(getattr(info, "currency_profit", "") or "").strip()
    try:
        swap_long_bps = swap_bps_per_rollover(
            swap_mode_name,
            swap_long_raw,
            point=point,
            price=mid,
            current_price=mid,
            contract_size=trade_contract_size or None,
            currency_base=currency_base,
            currency_profit=currency_profit,
        )
        swap_short_bps = swap_bps_per_rollover(
            swap_mode_name,
            swap_short_raw,
            point=point,
            price=mid,
            current_price=mid,
            contract_size=trade_contract_size or None,
            currency_base=currency_base,
            currency_profit=currency_profit,
        )
        supported = True
        unsupported_reason = None
    except ValueError as exc:
        swap_long_bps = swap_short_bps = 0.0
        supported = False
        unsupported_reason = str(exc)
    mt5_weekday = int(getattr(info, "swap_rollover3days", -1))
    try:
        rollover_multipliers = derive_rollover_multipliers(
            mt5_weekday, weekend_open=category == "CRYPTO"
        )
    except ValueError as exc:
        rollover_multipliers = ()
        supported = False
        unsupported_reason = str(exc)
    python_weekday = (mt5_weekday + 6) % 7 if mt5_weekday in range(7) else -1
    return {
        "symbol": symbol,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "account_login": DEMO_LOGIN,
        "account_balance": float(account.balance),
        "account_currency": str(account.currency),
        "category": category,
        "spread_points": spread_points,
        "spread_bps": spread_bps,
        "spread_multiplier": spread_multiplier,
        "slippage_bps": spread_bps * (spread_multiplier - 1.0),
        "commission_bps": commission_bps,
        "commission_source": "explicit CLI input; zero means no separate commission modeled",
        "swap_mode": swap_mode_name,
        "swap_supported": supported,
        "swap_unsupported_reason": unsupported_reason,
        "swap_long_raw": swap_long_raw,
        "swap_short_raw": swap_short_raw,
        "trade_contract_size": trade_contract_size,
        "currency_base": currency_base,
        "currency_profit": currency_profit,
        "swap_long_bps_per_rollover": swap_long_bps,
        "swap_short_bps_per_rollover": swap_short_bps,
        "rollover_multipliers": rollover_multipliers,
        "rollover_source": (
            "derived from MT5 swap_rollover3days; weekdays=1, triple=3, "
            + ("weekends=1 (CRYPTO)" if category == "CRYPTO" else "weekends=0")
        ),
        "point": point,
        "point_source": point_source,
        "mid_price": mid,
        "quote_attempts": quote_attempts,
        "triple_swap_weekday": python_weekday,
        "spread_guard_80_points_exceeded": spread_points > 80.0,
    }


def _cost_model(snapshot: Mapping[str, object]) -> CostModel:
    if snapshot.get("swap_supported") is not True:
        raise RuntimeError(f"unsupported swap mode {snapshot.get('swap_mode')}")
    return CostModel(
        spread_bps=float(snapshot["spread_bps"]),
        slippage_bps=float(snapshot["slippage_bps"]),
        swap_long_bps_per_rollover=float(snapshot["swap_long_bps_per_rollover"]),
        swap_short_bps_per_rollover=float(snapshot["swap_short_bps_per_rollover"]),
        triple_swap_weekday=int(snapshot["triple_swap_weekday"]),
        commission_bps=float(snapshot["commission_bps"]),
        rollover_multipliers=tuple(
            float(value) for value in snapshot["rollover_multipliers"]
        ),
        swap_mode=str(snapshot["swap_mode"]),
        swap_long_raw=float(snapshot["swap_long_raw"]),
        swap_short_raw=float(snapshot["swap_short_raw"]),
        point=float(snapshot["point"]),
        contract_size=(
            float(snapshot["trade_contract_size"])
            if float(snapshot.get("trade_contract_size", 0.0)) > 0
            else None
        ),
        currency_base=str(snapshot.get("currency_base", "")) or None,
        currency_profit=str(snapshot.get("currency_profit", "")) or None,
    )


def _list_universe(mt5: Any) -> list[str]:
    with mt5_lock:
        _assert_demo(mt5)
        symbols = mt5.symbols_get()
    if symbols is None:
        raise RuntimeError("MT5 symbols_get returned no evidence")
    return sorted(
        symbol.name
        for symbol in symbols
        if normalize_mt5_category(str(symbol.path)) in KEEP_CATS
    )


def _load_rates(
    mt5: Any,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    cache_root: Path,
) -> pd.DataFrame:
    cache_payload = f"{DEMO_LOGIN}|{symbol}|{timeframe}|{start.isoformat()}|{end.isoformat()}"
    cache_key = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()[:16]
    cache_path = cache_root / f"{_safe_symbol(symbol)}_{timeframe}_{cache_key}.pkl"
    if cache_path.is_file():
        frame = pd.read_pickle(cache_path)
    else:
        parts: list[pd.DataFrame] = []
        errors: list[str] = []
        terminal_max_bars = 100_000
        for chunk_start, chunk_end in chunked_time_ranges(start, end, chunk_days=240):
            with mt5_lock:
                _assert_demo(mt5)
                if not mt5.symbol_select(symbol, True):
                    raise RuntimeError(f"cannot select symbol {symbol}")
                terminal = mt5.terminal_info()
                terminal_max_bars = int(
                    getattr(terminal, "maxbars", terminal_max_bars) or terminal_max_bars
                )
                rates = mt5.copy_rates_range(
                    symbol,
                    _tf_constant(mt5, timeframe),
                    chunk_start,
                    chunk_end,
                )
                last_error = mt5.last_error()
            if rates is None:
                errors.append(
                    f"{chunk_start.isoformat()}..{chunk_end.isoformat()}={last_error!r}"
                )
            elif len(rates) > 0:
                parts.append(pd.DataFrame(rates))
        if errors:
            raise RuntimeError(
                f"RATES_ERROR {timeframe} {symbol}: " + "; ".join(errors)
            )
        if not parts:
            raise RuntimeError(f"RATES_EMPTY {timeframe} {symbol}")
        frame = pd.concat(parts, ignore_index=True)
        frame.index = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame[["open", "high", "low", "close"]].astype(float)
        frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        if len(frame) > terminal_max_bars:
            frame = frame.iloc[-terminal_max_bars:].copy()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_pickle(cache_path)
    now = pd.Timestamp.now("UTC")
    close_delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
    frame = frame.loc[(frame.index + close_delta) <= now].copy()
    if len(frame) < 600:
        raise RuntimeError(f"insufficient closed {timeframe} bars for {symbol}: {len(frame)}")
    return add_indicators(frame.copy())


def _candidate_set(style: str) -> dict[str, Candidate]:
    candidates = {}
    for (align, rsi_gate), (sl_atr, ladder) in itertools.product(
        ENTRY_VARIANTS, GRIDS[style]
    ):
        name = candidate_id(style, align, rsi_gate, sl_atr, ladder)
        candidates[name] = Candidate(
            name=name,
            style=style,
            align_ema50=align,
            rsi_gate=rsi_gate,
            sl_atr=float(sl_atr),
            tp_ladder=tuple(float(item) for item in ladder),
        )
    return candidates


def _segment_bounds(window: Any, name: str) -> tuple[datetime, datetime]:
    if name == "dev":
        return window.start, window.dev_end
    if name == "selection":
        return window.dev_end, window.selection_end
    if name == "final":
        return window.selection_end, window.end
    raise KeyError(name)


def _seed(symbol: str, style: str) -> int:
    digest = hashlib.sha256(f"{symbol}|{style}|{PROTOCOL_VERSION}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _calibrate_style(
    symbol: str,
    style: str,
    frame: pd.DataFrame,
    window: Any,
    costs: CostModel,
    cost_snapshot: Mapping[str, object],
    bootstrap_replications: int,
    risk_fraction: float,
) -> dict[str, object]:
    candidates = _candidate_set(style)
    signal_cache: dict[tuple[bool, bool], dict[Any, int]] = {}
    bars_cache: dict[tuple[bool, bool, str], tuple[Bar, ...]] = {}
    evaluation_cache: dict[tuple[str, str], dict[str, object]] = {}

    def bars_for(candidate: Candidate, segment_name: str) -> tuple[Bar, ...]:
        key = (candidate.align_ema50, candidate.rsi_gate, segment_name)
        cached = bars_cache.get(key)
        if cached is not None:
            return cached
        signal_key = (candidate.align_ema50, candidate.rsi_gate)
        signal_map = signal_cache.get(signal_key)
        if signal_map is None:
            signal_frame = entries(frame, *signal_key)
            signal_map = {
                timestamp: int(side)
                for timestamp, side in zip(signal_frame.index, signal_frame["side"])
            }
            signal_cache[signal_key] = signal_map
        start, end = _segment_bounds(window, segment_name)
        segment_frame = frame.loc[(frame.index >= start) & (frame.index < end)]
        bars = tuple(
            Bar(
                timestamp.to_pydatetime(),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.atr),
                signal_map.get(timestamp, 0),
            )
            for timestamp, row in segment_frame.iterrows()
        )
        bars_cache[key] = bars
        return bars

    def evaluator(candidate: Candidate, segment: Segment) -> Mapping[str, object]:
        cache_key = (candidate.name, segment.name)
        cached = evaluation_cache.get(cache_key)
        if cached is not None:
            return cached
        bars = bars_for(candidate, segment.name)
        trades = simulate(
            bars,
            sl_atr=candidate.sl_atr,
            tp_ladder=candidate.tp_ladder,
            time_stop_bars=int(STYLE_PROTOCOL[style]["time_stop"]),
            costs=costs,
        )
        trading_days = sorted({bar.timestamp.date() for bar in bars})
        segment_years = max(
            (segment.end - segment.start).total_seconds() / (365.25 * 86_400.0),
            1e-9,
        )
        payload = {
            "returns": aggregate_daily_returns(
                trades, trading_days, risk_fraction=risk_fraction
            ),
            "trade_returns": tuple(
                trade.net_bps / trade.initial_risk_bps * risk_fraction for trade in trades
            ),
            "trade_count": len(trades),
            "periods_per_year": len(trading_days) / segment_years,
            "trade_net_bps": tuple(trade.net_bps for trade in trades),
            "trades_detail": trades,
            "trading_day_count": len(trading_days),
        }
        evaluation_cache[cache_key] = payload
        return payload

    plan = ValidationPlan(
        dev=Segment("dev", window.start, window.dev_end),
        selection=Segment("selection", window.dev_end, window.selection_end),
        final=Segment("final", window.selection_end, window.end),
        experiment={
            "protocol": PROTOCOL_VERSION,
            "symbol": symbol,
            "style": style,
            "selection_rule": "max_trade_expectancy_on_selection",
            "multiplicity_trials": FAMILY_TRIALS,
            "risk_fraction": risk_fraction,
            "candidate_gate": {
                "min_dev_trades": 30,
                "min_selection_trades": 15,
                "min_dev_expectancy": 0.0,
                "min_selection_expectancy": 0.0,
                "min_dev_profit_factor": 1.0,
                "min_selection_profit_factor": 1.0,
            },
            "cost_snapshot": dict(cost_snapshot),
        },
        block_length=5,
        bootstrap_replications=bootstrap_replications,
        bootstrap_seed=_seed(symbol, style),
    )
    report = run_validation(
        candidates,
        plan,
        evaluator,
        ValidationGate(
            min_trades=30,
            min_profit_factor=1.20,
            min_expectancy=0.0,
            max_drawdown=0.20,
            min_deflated_sharpe=0.50,
            max_pbo=0.50,
        ),
    )
    result = report.to_dict()
    selected = candidates.get(report.selected_candidate) if report.selected_candidate else None
    result["selected_config"] = asdict(selected) if selected else None
    result["timeframe"] = STYLE_PROTOCOL[style]["tf"]
    result["family_trials"] = FAMILY_TRIALS
    if report.selected_candidate:
        final_payload = evaluation_cache.get((report.selected_candidate, "final"), {})
        final_trades = int(final_payload.get("trade_count", 0))
        final_years = max((window.end - window.selection_end).days / 365.25, 1e-9)
        result["final_trades_per_year"] = final_trades / final_years
        result["final_trade_metrics_bps"] = _bps_metrics(
            final_payload.get("trade_net_bps", ())
        )
        result["final_economics"] = summarize_trade_economics(
            final_payload.get("trades_detail", ()),
            trading_day_count=max(int(final_payload.get("trading_day_count", 0)), 1),
            risk_fraction=risk_fraction,
            account_balance=float(cost_snapshot["account_balance"]),
            observed_spread_bps=float(cost_snapshot["spread_bps"]),
            spread_multiplier=float(cost_snapshot["spread_multiplier"]),
            commission_bps=float(cost_snapshot["commission_bps"]),
        )
        result["final_economics"]["currency"] = str(cost_snapshot["account_currency"])
    return result


def _bps_metrics(values: Sequence[float]) -> dict[str, object]:
    source = tuple(float(item) for item in values)
    if not source:
        return {"trades": 0}
    wins = tuple(item for item in source if item > 0)
    losses = tuple(item for item in source if item <= 0)
    mean = sum(source) / len(source)
    variance = sum((item - mean) ** 2 for item in source) / len(source)
    loss_sum = sum(losses)
    return {
        "trades": len(source),
        "expectancy_bps": mean,
        "profit_factor": sum(wins) / abs(loss_sum) if loss_sum < 0 else math.inf,
        "winrate": len(wins) / len(source),
        "sharpe_trade": mean / math.sqrt(variance) if variance > 0 else 0.0,
    }


def calibrate_asset(
    mt5: Any,
    symbol: str,
    requested_start: datetime,
    requested_end: datetime,
    cache_root: Path,
    spread_multiplier: float,
    commission_bps: float,
    bootstrap_replications: int,
    risk_pct: float,
) -> dict[str, object]:
    try:
        snapshot = _cost_snapshot(mt5, symbol, spread_multiplier, commission_bps)
    except DataSpecInvalidError as exc:
        return {
            "symbol": symbol,
            "status": "DATA_SPEC_INVALID",
            "reason": str(exc),
        }
    if snapshot["swap_supported"] is not True:
        return {
            "symbol": symbol,
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": str(
                snapshot.get("swap_unsupported_reason")
                or f"unsupported swap mode {snapshot['swap_mode']}"
            ),
            "cost_snapshot": snapshot,
        }
    frames = {
        style: _load_rates(
            mt5,
            symbol,
            str(spec["tf"]),
            requested_start,
            requested_end,
            cache_root,
        )
        for style, spec in STYLE_PROTOCOL.items()
    }
    common_start = max(frame.index[0].to_pydatetime() for frame in frames.values())
    common_end = min(
        (frame.index[-1] + pd.Timedelta(minutes=TF_MINUTES[STYLE_PROTOCOL[style]["tf"]])).to_pydatetime()
        for style, frame in frames.items()
    )
    common_start = max(common_start, requested_start)
    common_end = min(common_end, requested_end)
    if common_end - common_start < timedelta(days=730):
        return {
            "symbol": symbol,
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "common M15/H1/H4 history is shorter than 730 days",
            "common_start": common_start.isoformat(),
            "common_end": common_end.isoformat(),
            "bars": {style: len(frame) for style, frame in frames.items()},
            "cost_snapshot": snapshot,
        }
    window = split_calibration_window(common_start, common_end)
    costs = _cost_model(snapshot)
    reports = {
        style: _calibrate_style(
            symbol,
            style,
            frame,
            window,
            costs,
            snapshot,
            bootstrap_replications,
            risk_pct / 100.0,
        )
        for style, frame in frames.items()
    }
    proposed_style = fastest_validated_style(reports)
    proposed = None
    if proposed_style:
        selected = reports[proposed_style].get("selected_config")
        selected_name = None if selected is None else selected.get("name")
        selected_metrics = next(
            (
                item.get("final", {})
                for item in reports[proposed_style].get("candidates", [])
                if item.get("name") == selected_name
            ),
            {},
        )
        proposed = {
            "style": proposed_style,
            "tf": STYLE_PROTOCOL[proposed_style]["tf"],
            "config": selected,
            "m2_status": reports[proposed_style]["status"],
            "risk_pct_per_trade": risk_pct,
            "final_metrics_account": selected_metrics,
            "final_trade_metrics_bps": reports[proposed_style].get(
                "final_trade_metrics_bps", {}
            ),
            "pbo": reports[proposed_style].get("pbo"),
            "deflated_sharpe": reports[proposed_style].get("deflated_sharpe"),
            "final_intervals": reports[proposed_style].get("final_intervals", {}),
            "final_trades_per_year": reports[proposed_style].get("final_trades_per_year"),
            "selection_rule": "fastest_style_passing_preregistered_M2_gates",
        }
    return {
        "symbol": symbol,
        "status": "CALIBRATED",
        "protocol": PROTOCOL_VERSION,
        "common_start": common_start.isoformat(),
        "common_end": common_end.isoformat(),
        "segments": {
            "dev": [window.start.isoformat(), window.dev_end.isoformat()],
            "selection": [window.dev_end.isoformat(), window.selection_end.isoformat()],
            "final": [window.selection_end.isoformat(), window.end.isoformat()],
        },
        "bars": {style: len(frame) for style, frame in frames.items()},
        "cost_snapshot": snapshot,
        "risk_pct_per_trade": risk_pct,
        "styles": reports,
        "proposed": proposed,
    }


def _proposal_from_results(results: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    assets = {}
    for symbol, result in results.items():
        proposal = result.get("proposed")
        if proposal:
            assets[symbol] = proposal
    return {
        "status": "PROPOSAL_ONLY_REQUIRES_CLAUDE_AND_FLORENT_VALIDATION",
        "protocol": PROTOCOL_VERSION,
        "generated": datetime.now(timezone.utc).isoformat(),
        "demo_login": DEMO_LOGIN,
        "assets": assets,
    }


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="", help="comma-separated explicit symbols")
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument("--bootstrap-replications", type=int, default=2_000)
    parser.add_argument("--spread-multiplier", type=float, default=1.25)
    parser.add_argument("--commission-bps", type=float, default=0.0)
    parser.add_argument("--risk-pct", type=float, default=7.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-assets", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli().parse_args(argv)
    if not math.isfinite(args.years) or args.years < 2.0:
        raise ValueError("--years must be finite and at least 2")
    if args.bootstrap_replications < 100:
        raise ValueError("--bootstrap-replications must be at least 100")
    if not math.isfinite(args.spread_multiplier) or args.spread_multiplier < 1.0:
        raise ValueError("--spread-multiplier must be finite and at least 1")
    if not math.isfinite(args.commission_bps) or args.commission_bps < 0:
        raise ValueError("--commission-bps must be finite and non-negative")
    if not math.isfinite(args.risk_pct) or args.risk_pct <= 0 or args.risk_pct > 100:
        raise ValueError("--risk-pct must be in (0, 100]")
    output_dir = args.output_dir.resolve()
    assets_dir = output_dir / "assets"
    cache_root = output_dir / "cache"
    mt5 = _connect_demo()
    requested_end = datetime.now(timezone.utc)
    requested_start = requested_end - timedelta(days=365.25 * args.years)
    universe = (
        [item.strip() for item in args.symbols.split(",") if item.strip()]
        if args.symbols
        else _list_universe(mt5)
    )
    if args.max_assets > 0:
        universe = universe[: args.max_assets]
    results: dict[str, Mapping[str, object]] = {}
    for index, symbol in enumerate(universe, 1):
        asset_path = assets_dir / f"{_safe_symbol(symbol)}.json"
        if args.resume and asset_path.is_file():
            result = json.loads(asset_path.read_text(encoding="utf-8"))
        else:
            started = time.perf_counter()
            try:
                result = calibrate_asset(
                    mt5,
                    symbol,
                    requested_start,
                    requested_end,
                    cache_root,
                    args.spread_multiplier,
                    args.commission_bps,
                    args.bootstrap_replications,
                    args.risk_pct,
                )
            except Exception as exc:
                result = {
                    "symbol": symbol,
                    "status": "INSUFFICIENT_EVIDENCE",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            result["elapsed_seconds"] = time.perf_counter() - started
            _atomic_json_write(asset_path, result)
        results[symbol] = result
        summary = {
            "protocol": PROTOCOL_VERSION,
            "generated": datetime.now(timezone.utc).isoformat(),
            "requested_start": requested_start.isoformat(),
            "requested_end": requested_end.isoformat(),
            "demo_login": DEMO_LOGIN,
            "universe_size": len(universe),
            "completed": len(results),
            "results": results,
        }
        _atomic_json_write(output_dir / "summary.json", summary)
        _atomic_json_write(output_dir / "asset_configs.proposal.json", _proposal_from_results(results))
        print(
            json.dumps(
                {
                    "progress": f"{index}/{len(universe)}",
                    "symbol": symbol,
                    "status": result.get("status"),
                    "proposed": result.get("proposed"),
                    "reason": result.get("reason"),
                },
                ensure_ascii=False,
                allow_nan=False,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
