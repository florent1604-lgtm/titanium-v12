"""assistant/plugins/trading_plugin.py — Réponses directes aux requêtes trading.

Gère les intentions : signal, position, risk, optim.
Interroge l'API Titanium interne et formate une réponse lisible.
Temps de réponse cible : < 100ms (pas de LLM).
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List, Tuple

import aiohttp

from assistant.config import TITAN_API_BASE
from assistant.plugins.base import TitanPlugin

logger = logging.getLogger(__name__)

# Mapping symbole → variantes textuelles
_SYM_ALIASES: List[Tuple[str, str]] = [
    ("btc",      "BTC/USDT"),
    ("bitcoin",  "BTC/USDT"),
    ("eth",      "ETH/USDT"),
    ("ethereum", "ETH/USDT"),
    ("ether",    "ETH/USDT"),
    ("sol",      "SOL/USDT"),
    ("solana",   "SOL/USDT"),
    ("paxg",     "PAXG/USDT"),
    ("gold",     "PAXG/USDT"),
    ("or",       "PAXG/USDT"),
    ("xau",      "PAXG/USDT"),
]

_TIMEOUT = aiohttp.ClientTimeout(total=3)


class TradingPlugin(TitanPlugin):
    """Répond directement aux questions trading depuis les données API."""

    name = "trading"
    intents = ["signal", "position", "risk", "optim"]
    min_confidence = 0.55

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        t = text.lower()
        if intent == "signal":
            return await self._signal(t)
        if intent == "position":
            return await self._position(t)
        if intent == "risk":
            return await self._risk(t)
        if intent == "optim":
            return await self._optim(t)
        return None

    # ── Helpers HTTP ──────────────────────────────────────────────────────────

    async def _get(self, path: str) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{TITAN_API_BASE}{path}", timeout=_TIMEOUT) as r:
                    if r.status == 200:
                        return await r.json()
        except Exception as e:
            logger.debug("[TRADING_PLUGIN] GET %s: %s", path, e)
        return None

    # ── Signal ────────────────────────────────────────────────────────────────

    async def _signal(self, text: str) -> Optional[str]:
        state = await self._get("/api/state")
        if not state:
            return "Impossible d'accéder aux signaux pour le moment."

        signals = state.get("signals", {})

        # Chercher un symbole spécifique dans le texte
        target = None
        for alias, sym in _SYM_ALIASES:
            if alias in text:
                target = sym
                break

        if target:
            sig = signals.get(target, {})
            if not sig:
                return f"Pas encore de données pour {target}."
            side   = sig.get("side", "NEUTRE")
            score  = sig.get("score", 0)
            price  = sig.get("price", 0)
            regime = sig.get("regime", "?")
            active = sig.get("active", False)
            base   = target.split("/")[0]
            status = "actif" if active else "en veille"
            return (
                f"{base} — {side} | score {score}/11 | "
                f"{price:.4f}$ | régime {regime} ({status})"
            )

        # Tous les signaux
        active = [
            (s, d) for s, d in signals.items()
            if d.get("active") and d.get("side") not in ("NEUTRE", None, "")
        ]
        if not active:
            return "Aucun signal actif en ce moment sur les 4 actifs surveillés."

        parts = [
            f"{s.split('/')[0]} {d.get('side')} {d.get('score', 0)}/11"
            for s, d in active
        ]
        return "Signaux actifs : " + " | ".join(parts)

    # ── Position / PnL ────────────────────────────────────────────────────────

    async def _position(self, text: str) -> Optional[str]:
        state = await self._get("/api/state")
        stats = await self._get("/paper/stats")
        parts: List[str] = []

        if state:
            paper = state.get("paper", {})
            equity = paper.get("equity", 0)
            cash   = paper.get("cash", 0)
            pnl    = paper.get("total_pnl", 0)

            positions = paper.get("positions", [])
            if positions:
                parts.append(f"{len(positions)} position(s) ouverte(s) :")
                for p in positions[:4]:
                    sym  = p.get("symbol", "?").split("/")[0]
                    side = p.get("side", "?")
                    upnl = p.get("unrealized_pnl", 0)
                    parts.append(f"  {sym} {side} → PnL {upnl:+.2f}$")
            else:
                parts.append("Aucune position ouverte.")

            parts.append(
                f"Equity: {equity:.2f}$ | Cash: {cash:.2f}$ | PnL total: {pnl:+.2f}$"
            )

        if stats:
            n  = stats.get("total_trades", 0)
            wr = stats.get("winrate_pct", 0)
            if n > 0:
                parts.append(f"Historique: {n} trades | winrate {wr:.1f}%")

        return "\n".join(parts) if parts else None

    # ── Risque macro ──────────────────────────────────────────────────────────

    async def _risk(self, text: str) -> Optional[str]:
        # Essayer le module fundamentals
        data = await self._get("/fundamentals/state")
        if data:
            risk    = data.get("risk_score", 0)
            mode    = data.get("mode", "?")
            factors = data.get("risk_factors", [])
            parts   = [f"Risque macro: {risk}/10 — Mode: {mode}"]
            if factors:
                parts.append("Facteurs: " + ", ".join(str(f) for f in factors[:3]))
            return "\n".join(parts)

        # Fallback drawdown via paper
        state = await self._get("/api/state")
        if state:
            paper = state.get("paper", {})
            dd    = paper.get("max_drawdown_pct", 0)
            return f"Drawdown max: {dd:.1f}% — Module macro non disponible."

        return None

    # ── Optimisation ──────────────────────────────────────────────────────────

    async def _optim(self, text: str) -> Optional[str]:
        data = await self._get("/api/optim/results")
        if not data:
            return None

        parts: List[str] = []
        for sym, cfg in data.items():
            if isinstance(cfg, dict):
                wr = cfg.get("winrate", 0)
                sh = cfg.get("sharpe", 0)
                base = sym.split("/")[0]
                parts.append(f"{base}: winrate {wr:.0%} sharpe {sh:.2f}")

        if parts:
            return "Optimisation — " + " | ".join(parts)
        return None
