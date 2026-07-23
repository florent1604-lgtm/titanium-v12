"""Endpoint lecture seule TitaniumSnapshot v1 pour JARVIS/Hermes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from domain.titanium_snapshot import StrategyInput, build_titanium_snapshot


router = APIRouter(prefix="/api/snapshot", tags=["snapshot"])
canonical_router = APIRouter(tags=["snapshot"])
ROOT = Path(__file__).resolve().parent.parent
VALIDATION_REGISTRY = ROOT / "validation" / "strategy_status.json"
PAPER_STATE = ROOT / "data" / "paper_state.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _validation_registry() -> dict[str, dict[str, Any]]:
    value = _load_json(VALIDATION_REGISTRY).get("strategies", {})
    return value if isinstance(value, dict) else {}


def _best_crypto_signal(signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates = [item for item in signals.values() if isinstance(item, dict)]
    if not candidates:
        return {}
    return max(candidates, key=lambda item: float(item.get("score", 0) or 0))


def build_current_snapshot() -> dict[str, Any]:
    registry = _validation_registry()
    from execution.executor import executor
    from execution.signal_manager import get_all_signals
    from core.forex_engine import forex_state, get_stats as forex_stats
    from core.swing_engine import swing_state, get_stats as swing_stats

    crypto_state = executor.get_state()
    crypto_stats = crypto_state.get("stats", {}) if isinstance(crypto_state, dict) else {}
    crypto_file = _load_json(PAPER_STATE)
    signal = _best_crypto_signal(get_all_signals())
    swing = swing_stats()
    forex = forex_stats()

    inputs = [
        StrategyInput(
            strategy_id="crypto",
            source="execution.paper_trading.PaperEngine.get_stats",
            source_ts=crypto_file.get("saved_at"),
            stale_after_seconds=60,
            realized_pnl=crypto_stats.get("realized_pnl"),
            realized_pnl_unit="USDT",
            winrate_pct=crypto_stats.get("winrate"),
            trades=crypto_stats.get("total_trades"),
            equity=crypto_stats.get("equity"),
            equity_unit="USDT",
            score=signal.get("score"),
            score_max=signal.get("score_max"),
            score_source="execution.signal_manager.get_all_signals",
            score_source_ts=signal.get("ts"),
            validation=registry.get("crypto", {}),
        ),
        StrategyInput(
            strategy_id="forex",
            source="core.forex_engine.get_stats",
            source_ts=forex.get("last_scan"),
            stale_after_seconds=180,
            realized_pnl=sum(float(t.get("pnl_eur", 0)) for t in forex_state.get("trades", [])),
            realized_pnl_unit="EUR",
            winrate_pct=forex.get("winrate_pct"),
            trades=forex.get("trades"),
            equity=forex.get("equity"),
            equity_unit="EUR",
            score=None,
            score_max=None,
            validation=registry.get("forex", {}),
        ),
        StrategyInput(
            strategy_id="swing",
            source="core.swing_engine.get_stats",
            source_ts=swing.get("last_scan"),
            stale_after_seconds=300,
            realized_pnl=sum(float(t.get("pnl_eur", 0)) for t in swing_state.get("trades", [])),
            realized_pnl_unit="EUR",
            winrate_pct=swing.get("winrate_pct"),
            trades=swing.get("trades"),
            equity=swing.get("equity"),
            equity_unit="EUR",
            score=None,
            score_max=None,
            validation=registry.get("swing", {}),
        ),
    ]
    return build_titanium_snapshot(inputs)


@router.get("/v1")
@canonical_router.get("/api/v1/snapshot")
async def titanium_snapshot_v1() -> JSONResponse:
    """Contrat versionné, fail-visible et strictement paper-only."""
    return JSONResponse(build_current_snapshot())
