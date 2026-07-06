"""execution/executor.py — Couche d'exécution unifiée (paper / live / disabled).

Pattern Strategy : BaseExecutor → PaperExecutor | DisabledExecutor
Le mode est contrôlé par TRADING_MODE dans .env.

Usage (singleton) :
    from execution.executor import executor
    await executor.execute(signal)
    await executor.update_price(sym, price)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from utils.config import TRADING_MODE
from utils.logger import get_logger

logger = get_logger(__name__)


# ── Interfaces ────────────────────────────────────────────────────────────────

class BaseExecutor(ABC):

    @abstractmethod
    async def execute(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Traite un signal : ouvre une position ou retourne None si refusé."""
        ...

    @abstractmethod
    async def update_price(self, symbol: str, price: float) -> List[str]:
        """Met à jour le prix courant — vérifie SL/TP, funding, trailing."""
        ...

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """État courant de l'exécuteur (positions, stats)."""
        ...


# ── Paper Executor ────────────────────────────────────────────────────────────

class PaperExecutor(BaseExecutor):
    """Exécution en mode simulation réaliste."""

    def __init__(self) -> None:
        from execution.paper_trading import PaperEngine
        self.engine = PaperEngine()
        logger.info(
            "[EXECUTOR] Mode PAPER activé — capital=%.2f$ slippage=%.1fbps fees=%.1fbps",
            self.engine.initial_capital,
            __import__("utils.config", fromlist=["PAPER_SLIPPAGE_BPS"]).PAPER_SLIPPAGE_BPS,
            __import__("utils.config", fromlist=["PAPER_FEE_BPS"]).PAPER_FEE_BPS,
        )

    async def execute(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from execution.guards import run_guards
        from execution.trade_journal import stage, commit, reject
        from utils.config import JOURNAL_STAGING_ENABLED, JOURNAL_AUTO_APPROVE

        sym = signal.get("symbol", "")
        open_positions = {
            s: p.current_size_usdt() for s, p in self.engine.positions.items()
        }
        capital = self.engine.equity_with_unrealized()

        spectral_info = {k: v for k, v in signal.items() if k.startswith("spectral_")}
        trade_hash = stage(signal, spectral_info or None)

        guard_result = run_guards(signal, sym, open_positions, capital)
        if not guard_result.passed:
            logger.warning(
                "[EXECUTOR] %s ordre refusé par guard %s — %s",
                sym, guard_result.guard, guard_result.reason,
            )
            reject(trade_hash, f"{guard_result.guard}: {guard_result.reason}")
            return None

        if JOURNAL_STAGING_ENABLED and not JOURNAL_AUTO_APPROVE:
            # Reste "staged" — attend une approbation manuelle (POST /journal/{hash}/approve).
            # stage() a déjà enregistré le signal en attente (JOURNAL_STAGING_ENABLED=1).
            return None

        pos = await self.engine.open_position(signal)
        if pos is not None:
            commit(trade_hash, pos.to_dict())
            self._emit_trade_opened(sym, pos)
            return pos.to_dict()
        reject(trade_hash, "engine_rejected")
        return None

    async def execute_approved(self, trade_hash: str) -> Optional[Dict[str, Any]]:
        """Approuve manuellement un trade resté "staged" (JOURNAL_STAGING_ENABLED=1)."""
        from execution.trade_journal import pop_pending, mark_approved, commit, reject

        signal = pop_pending(trade_hash)
        if signal is None:
            return None
        mark_approved(trade_hash)
        pos = await self.engine.open_position(signal)
        if pos is not None:
            commit(trade_hash, pos.to_dict())
            self._emit_trade_opened(signal.get("symbol", ""), pos)
            return pos.to_dict()
        reject(trade_hash, "engine_rejected")
        return None

    @staticmethod
    def _emit_trade_opened(sym: str, pos: Any) -> None:
        from utils.event_bus import emit as _emit_event
        _emit_event("TRADE", {
            "phase": "opened", "symbol": sym, "side": pos.side,
            "score": pos.score, "size_usdt": round(pos.size_usdt, 2),
        })

    async def update_price(self, symbol: str, price: float) -> List[str]:
        return await self.engine.update_price(symbol, price)

    def get_state(self) -> Dict[str, Any]:
        prices = self.engine._last_prices
        return {
            "mode":         "paper",
            "stats":        self.engine.get_stats(),
            "positions":    {
                s: p.to_dict(prices.get(s, 0.0))
                for s, p in self.engine.positions.items()
            },
            "recent_trades": [t.to_dict() for t in self.engine.trades[-50:]],
        }

    def get_equity_curve(self, n: int = 200) -> list:
        return self.engine.get_equity_curve(n)

    async def close_position_manual(self, symbol: str, price: float):
        return await self.engine.close_position_manual(symbol, price)

    async def reset(self) -> None:
        await self.engine.reset()


# ── Disabled Executor ─────────────────────────────────────────────────────────

class DisabledExecutor(BaseExecutor):
    """Aucune position n'est ouverte — mode signaux purs."""

    def __init__(self) -> None:
        logger.info("[EXECUTOR] Mode DISABLED — aucune position ne sera ouverte")

    async def execute(self, signal: Dict[str, Any]) -> None:
        return None

    async def update_price(self, symbol: str, price: float) -> List[str]:
        return []

    def get_state(self) -> Dict[str, Any]:
        return {"mode": "disabled", "stats": {}, "positions": {}, "recent_trades": []}


# ── Factory + Singleton ──────────────────────────────────────────────────────

def _create_executor() -> BaseExecutor:
    mode = TRADING_MODE.lower()
    if mode == "paper":
        return PaperExecutor()
    elif mode == "live":
        raise RuntimeError(
            "[EXECUTOR] Mode LIVE non implémenté. "
            "Utilisez TRADING_MODE=paper pour la simulation ou TRADING_MODE=disabled pour les signaux seuls. "
            "Le mode live nécessite l'intégration de l'API Binance (non disponible dans cette version)."
        )
    else:
        return DisabledExecutor()


executor: BaseExecutor = _create_executor()
