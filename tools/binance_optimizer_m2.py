"""Leakage-resistant, data-only M2 calibration for Binance Spot.

This driver never places orders and never reads private Binance account data.
It reuses Titanium's validation harness while keeping its outputs isolated from
the runtime asset configuration.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.asset_optimizer_m2 import (
    STYLE_PROTOCOL,
    TF_MINUTES,
    _atomic_json_write,
    _calibrate_style,
    _safe_symbol,
)
from tools.binance_history import binance_cost_model, get_klines
from tools.strategy_lab import add_indicators
from validation.asset_simulation import (
    CostModel,
    fastest_validated_style,
    split_calibration_window,
)


BINANCE_PROTOCOL_VERSION = "binance-spot-calibration-m2/2026-07-16-v1"
EXECUTION_MODES = ("taker", "maker")
DEFAULT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "BNBUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "LTCUSDT",
)
DEFAULT_OUTPUT = ROOT / "data" / "calibration_binance_2026-07-16"
KlineFetcher = Callable[[str, str, float], pd.DataFrame | None]


def build_cost_context(
    mode: str,
    *,
    spread_multiplier: float,
    reference_balance: float,
) -> tuple[CostModel, dict[str, Any]]:
    """Build total round-trip Binance Spot costs and their audit snapshot."""
    normalized = str(mode).strip().lower()
    if normalized not in EXECUTION_MODES:
        raise ValueError(f"unsupported Binance execution mode: {mode}")
    numeric = (spread_multiplier, reference_balance)
    if any(not math.isfinite(float(value)) for value in numeric):
        raise ValueError("cost context inputs must be finite")
    if spread_multiplier < 1.0:
        raise ValueError("spread_multiplier must be at least 1")
    if reference_balance <= 0:
        raise ValueError("reference_balance must be positive")

    raw = binance_cost_model(normalized)
    observed_spread = float(raw["spread_bps"])
    slippage = float(raw["slippage_bps"])
    commission_per_side = float(raw["commission_bps"])
    round_trip_commission = commission_per_side * 2.0
    values = (observed_spread, slippage, commission_per_side)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Binance cost model returned an invalid cost")

    costs = CostModel(
        spread_bps=observed_spread * spread_multiplier,
        slippage_bps=slippage,
        swap_long_bps_per_rollover=0.0,
        swap_short_bps_per_rollover=0.0,
        triple_swap_weekday=0,
        commission_bps=round_trip_commission,
        rollover_multipliers=(0.0,) * 7,
    )
    snapshot: dict[str, Any] = {
        "protocol": BINANCE_PROTOCOL_VERSION,
        "source": "binance_spot_public_klines",
        "venue": "BINANCE_SPOT",
        "execution_mode": normalized.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "account_balance": float(reference_balance),
        "account_balance_source": "standardized_reference_not_live_account",
        "account_currency": "USDT",
        "spread_bps": observed_spread,
        "spread_multiplier": float(spread_multiplier),
        "spread_bps_stressed": costs.spread_bps,
        "slippage_bps": slippage,
        "commission_bps_per_side": commission_per_side,
        "commission_bps": round_trip_commission,
        "commission_scope": "round_trip_total",
        "funding_bps": 0.0,
        "funding_assumption": "binance_spot_no_funding",
        "swap_supported": True,
        "swap_mode": "DISABLED_SPOT",
        "swap_long_bps_per_rollover": 0.0,
        "swap_short_bps_per_rollover": 0.0,
        "rollover_multipliers": [0.0] * 7,
        "cost_note": str(raw.get("note", "")),
    }
    return costs, snapshot


def load_binance_frames(
    symbol: str,
    years: float,
    cache_root: Path,
    *,
    fetcher: KlineFetcher = get_klines,
    now: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """Load closed Binance bars for every M2 style, using an isolated cache."""
    if not math.isfinite(float(years)) or years < 2.0:
        raise ValueError("years must be finite and at least 2")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    current_ts = pd.Timestamp(current).tz_convert("UTC")
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}

    for style, spec in STYLE_PROTOCOL.items():
        timeframe = str(spec["tf"])
        cache_path = cache_root / (
            f"{_safe_symbol(symbol)}.{timeframe}.{format(float(years), '.4g')}.raw.pkl"
        )
        if cache_path.is_file():
            raw = pd.read_pickle(cache_path)
        else:
            raw = fetcher(symbol, timeframe, float(years))
            if raw is None or raw.empty:
                raise RuntimeError(f"RATES_EMPTY: no {timeframe} bars for {symbol}")
            raw = raw.copy()
            raw.to_pickle(cache_path)

        required = {"open", "high", "low", "close"}
        if not isinstance(raw.index, pd.DatetimeIndex) or not required.issubset(raw.columns):
            raise RuntimeError(f"RATES_INVALID: malformed {timeframe} bars for {symbol}")
        frame = raw.copy().sort_index()
        frame = frame.loc[~frame.index.duplicated(keep="first")]
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize("UTC")
        else:
            frame.index = frame.index.tz_convert("UTC")
        close_delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
        frame = frame.loc[(frame.index + close_delta) <= current_ts].copy()
        if len(frame) < 600:
            raise RuntimeError(
                f"insufficient closed {timeframe} bars for {symbol}: {len(frame)}"
            )
        frame = add_indicators(frame)
        if len(frame) < 600:
            raise RuntimeError(
                f"insufficient indicator-ready {timeframe} bars for {symbol}: {len(frame)}"
            )
        frames[style] = frame
    return frames


def calibrate_binance_asset(
    symbol: str,
    scenario: str,
    frames: dict[str, pd.DataFrame],
    requested_start: datetime,
    requested_end: datetime,
    *,
    spread_multiplier: float,
    bootstrap_replications: int,
    risk_pct: float,
    reference_balance: float,
) -> dict[str, Any]:
    """Calibrate one Binance symbol/scenario with Titanium's unchanged M2 gates."""
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested timestamps must include a timezone")
    if requested_start >= requested_end:
        raise ValueError("requested_start must precede requested_end")
    if bootstrap_replications < 100:
        raise ValueError("bootstrap_replications must be at least 100")
    if not math.isfinite(float(risk_pct)) or risk_pct <= 0 or risk_pct > 100:
        raise ValueError("risk_pct must be in (0, 100]")
    if set(frames) != set(STYLE_PROTOCOL):
        raise ValueError("frames must contain scalp, intraday, and swing")

    costs, snapshot = build_cost_context(
        scenario,
        spread_multiplier=spread_multiplier,
        reference_balance=reference_balance,
    )
    snapshot["symbol"] = symbol
    starts = []
    ends = []
    for style, frame in frames.items():
        if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError(f"{style} frame must have a non-empty DatetimeIndex")
        timeframe = str(STYLE_PROTOCOL[style]["tf"])
        starts.append(frame.index[0].to_pydatetime())
        ends.append(
            (
                frame.index[-1]
                + pd.Timedelta(minutes=TF_MINUTES[timeframe])
            ).to_pydatetime()
        )
    common_start = max(max(starts), requested_start)
    common_end = min(min(ends), requested_end)
    if common_end - common_start < timedelta(days=730):
        return {
            "symbol": symbol,
            "source": "BINANCE_SPOT",
            "scenario": str(scenario).upper(),
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "common M15/H1/H4 history is shorter than 730 days",
            "common_start": common_start.isoformat(),
            "common_end": common_end.isoformat(),
            "bars": {style: len(frame) for style, frame in frames.items()},
            "cost_snapshot": snapshot,
        }

    window = split_calibration_window(common_start, common_end)
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
        report = reports[proposed_style]
        proposed = {
            "style": proposed_style,
            "tf": STYLE_PROTOCOL[proposed_style]["tf"],
            "config": report.get("selected_config"),
            "m2_status": report["status"],
            "risk_pct_per_trade": risk_pct,
            "pbo": report.get("pbo"),
            "deflated_sharpe": report.get("deflated_sharpe"),
            "final_intervals": report.get("final_intervals", {}),
            "final_trades_per_year": report.get("final_trades_per_year"),
            "final_trade_metrics_bps": report.get("final_trade_metrics_bps", {}),
            "selection_rule": "fastest_style_passing_preregistered_M2_gates",
        }

    return {
        "symbol": symbol,
        "source": "BINANCE_SPOT",
        "scenario": str(scenario).upper(),
        "status": "CALIBRATED",
        "protocol": BINANCE_PROTOCOL_VERSION,
        "engine_protocol": "asset-calibration-m2/2026-07-15-v6",
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


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--scenarios", default=",".join(EXECUTION_MODES))
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument("--bootstrap-replications", type=int, default=2_000)
    parser.add_argument("--spread-multiplier", type=float, default=1.25)
    parser.add_argument("--risk-pct", type=float, default=7.0)
    parser.add_argument("--reference-balance", type=float, default=10_000.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-assets", type=int, default=0)
    return parser


def _proposal_from_results(
    results: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    assets = {}
    for symbol, scenarios in results.items():
        for scenario, result in scenarios.items():
            proposal = result.get("proposed")
            if proposal:
                assets[f"{symbol}:{scenario.upper()}"] = proposal
    return {
        "status": "PROPOSAL_ONLY_REQUIRES_CLAUDE_AND_FLORENT_VALIDATION",
        "protocol": BINANCE_PROTOCOL_VERSION,
        "source": "BINANCE_SPOT",
        "generated": datetime.now(timezone.utc).isoformat(),
        "assets": assets,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli().parse_args(argv)
    numeric = (
        args.years,
        args.spread_multiplier,
        args.risk_pct,
        args.reference_balance,
    )
    if any(not math.isfinite(float(value)) for value in numeric):
        raise ValueError("numeric arguments must be finite")
    if args.years < 2.0:
        raise ValueError("--years must be at least 2")
    if args.bootstrap_replications < 100:
        raise ValueError("--bootstrap-replications must be at least 100")
    if args.spread_multiplier < 1.0:
        raise ValueError("--spread-multiplier must be at least 1")
    if args.risk_pct <= 0 or args.risk_pct > 100:
        raise ValueError("--risk-pct must be in (0, 100]")
    if args.reference_balance <= 0:
        raise ValueError("--reference-balance must be positive")

    universe = tuple(
        dict.fromkeys(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    )
    if not universe:
        raise ValueError("--symbols must contain at least one symbol")
    if args.max_assets < 0:
        raise ValueError("--max-assets must be non-negative")
    if args.max_assets:
        universe = universe[: args.max_assets]
    scenarios = tuple(
        dict.fromkeys(item.strip().lower() for item in args.scenarios.split(",") if item.strip())
    )
    if not scenarios:
        raise ValueError("--scenarios must contain at least one execution mode")
    for scenario in scenarios:
        if scenario not in EXECUTION_MODES:
            raise ValueError(f"unsupported Binance execution mode: {scenario}")

    output_dir = args.output_dir.resolve()
    assets_dir = output_dir / "assets"
    cache_root = output_dir / "cache"
    requested_end = datetime.now(timezone.utc)
    requested_start = requested_end - timedelta(days=365.25 * args.years)
    results: dict[str, dict[str, Mapping[str, Any]]] = {}
    completed = 0
    total = len(universe) * len(scenarios)

    for symbol in universe:
        pending = [
            scenario
            for scenario in scenarios
            if not (
                args.resume
                and (assets_dir / f"{_safe_symbol(symbol)}.{scenario}.json").is_file()
            )
        ]
        frames = None
        frame_error = None
        if pending:
            try:
                frames = load_binance_frames(
                    symbol,
                    args.years,
                    cache_root,
                    now=requested_end,
                )
            except Exception as exc:
                frame_error = f"{type(exc).__name__}: {exc}"

        symbol_results: dict[str, Mapping[str, Any]] = {}
        for scenario in scenarios:
            asset_path = assets_dir / f"{_safe_symbol(symbol)}.{scenario}.json"
            if args.resume and asset_path.is_file():
                result = json.loads(asset_path.read_text(encoding="utf-8"))
            else:
                started = time.perf_counter()
                if frame_error is not None or frames is None:
                    result = {
                        "symbol": symbol,
                        "source": "BINANCE_SPOT",
                        "scenario": scenario.upper(),
                        "status": "INSUFFICIENT_EVIDENCE",
                        "reason": frame_error or "Binance frames unavailable",
                        "proposed": None,
                    }
                else:
                    try:
                        result = calibrate_binance_asset(
                            symbol,
                            scenario,
                            frames,
                            requested_start,
                            requested_end,
                            spread_multiplier=args.spread_multiplier,
                            bootstrap_replications=args.bootstrap_replications,
                            risk_pct=args.risk_pct,
                            reference_balance=args.reference_balance,
                        )
                    except Exception as exc:
                        result = {
                            "symbol": symbol,
                            "source": "BINANCE_SPOT",
                            "scenario": scenario.upper(),
                            "status": "INSUFFICIENT_EVIDENCE",
                            "reason": f"{type(exc).__name__}: {exc}",
                            "proposed": None,
                        }
                result["elapsed_seconds"] = time.perf_counter() - started
                _atomic_json_write(asset_path, result)
            symbol_results[scenario] = result
            completed += 1
            results[symbol] = symbol_results
            summary = {
                "protocol": BINANCE_PROTOCOL_VERSION,
                "source": "BINANCE_SPOT",
                "generated": datetime.now(timezone.utc).isoformat(),
                "requested_start": requested_start.isoformat(),
                "requested_end": requested_end.isoformat(),
                "universe_size": len(universe),
                "scenario_count": len(scenarios),
                "total_evaluations": total,
                "completed": completed,
                "results": results,
            }
            _atomic_json_write(output_dir / "summary.json", summary)
            _atomic_json_write(
                output_dir / "asset_configs.proposal.json",
                _proposal_from_results(results),
            )
            print(
                json.dumps(
                    {
                        "progress": f"{completed}/{total}",
                        "symbol": symbol,
                        "scenario": scenario.upper(),
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
