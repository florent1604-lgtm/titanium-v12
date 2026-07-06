"""execution/paper_trading.py — Moteur Paper Trading réaliste pour Titanium v12.

Fonctionnalités :
  - Position sizing risque-basé : risk_usdt / sl_distance = size
  - Slippage + spread + frais taker configurable par .env
  - Funding rate (futures) simulé toutes les 8h
  - Sorties partielles : TP1 (33%) → SL au BE, TP2 (33%), TP3 (34% restant)
  - Trailing stop optionnel (multiple ATR)
  - Equity curve + max drawdown continus
  - Persistance JSON (state) + CSV (journal) + JSON (journal)
  - Thread-safe via asyncio.Lock
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.config import (
    PAPER_FEE_BPS,
    PAPER_FUNDING_RATE_8H,
    PAPER_INITIAL_CAPITAL,
    PAPER_JOURNAL_CSV,
    PAPER_JOURNAL_FILE,
    PAPER_MAX_AGE_HOURS,
    PAPER_MAX_EXPOSURE_PCT,
    PAPER_MAX_POSITIONS,
    PAPER_RISK_PCT,
    PAPER_SLIPPAGE_BPS,
    PAPER_SPREAD_BPS,
    PAPER_STATE_FILE,
    PAPER_TRAILING_PCT,
    PAPER_TRAILING_STOP,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_FUNDING_INTERVAL_SEC: float = 8.0 * 3600  # funding toutes les 8 heures
_TP1_FRACTION: float = 1 / 3               # fraction de la position fermée à TP1
_TP2_FRACTION: float = 1 / 3               # idem TP2 (restant ≈ 1/3 après)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class PartialExit:
    """Sortie partielle enregistrée sur une position."""
    exit_price: float
    fraction_closed: float   # fraction de la position ORIGINALE fermée
    pnl_usdt: float          # PnL net (après frais sortie) de cette tranche
    reason: str              # "tp1" | "tp2" | "tp3" | "sl" | "manual"
    ts: str                  # ISO timestamp


@dataclass
class PaperPosition:
    """Position ouverte en paper trading."""
    symbol: str
    side: str                # "LONG" | "SHORT"
    entry_price: float       # prix d'entrée après slippage+spread
    raw_entry_price: float   # prix brut issu du signal
    size_usdt: float         # capital USDT engagé (avant frais)
    size_base: float         # quantité en base currency
    sl: float                # stop-loss courant (peut bouger au BE)
    tp1: float
    tp2: float
    tp3: float
    entry_ts: str
    correlation_id: str
    score: int
    source: str              # "internal" | "tradingview"

    # État TPs
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    remaining_pct: float = 1.0   # fraction de la position encore ouverte
    sl_at_be: bool = False        # True si SL a été déplacé au breakeven

    # Trailing stop
    trail_sl: float = 0.0        # 0 = inactif

    # Funding
    last_funding_ts: float = field(default_factory=time.monotonic)
    funding_paid: float = 0.0    # USDT payés en funding (positif = payé)

    # Frais
    fee_entry: float = 0.0

    # Contexte SMC au moment de l'entrée (journal + learning engine)
    confs: List[str] = field(default_factory=list)  # critères SMC validés
    regime: str = ""                                  # TREND | RANGE | VOLATILE
    macro_risk: float = 0.0                           # score Fundamentals 0-100
    rsi: float = 0.0
    adx: float = 0.0

    # Sorties partielles réalisées
    partial_exits: List[PartialExit] = field(default_factory=list)

    # ── Méthodes ──────────────────────────────────────────────────────────────

    def current_size_usdt(self) -> float:
        """Valeur USDT de la fraction encore ouverte."""
        return self.size_usdt * self.remaining_pct

    def unrealized_pnl(self, current_price: float) -> float:
        """PnL non réalisé USDT sur la fraction encore ouverte."""
        rem = self.current_size_usdt()
        if self.side == "LONG":
            return (current_price - self.entry_price) / self.entry_price * rem
        return (self.entry_price - current_price) / self.entry_price * rem

    def unrealized_pct(self, current_price: float) -> float:
        """PnL % par rapport au capital initial du trade."""
        if self.size_usdt == 0:
            return 0.0
        return self.unrealized_pnl(current_price) / self.size_usdt * 100

    def realized_pnl(self) -> float:
        return sum(p.pnl_usdt for p in self.partial_exits)

    def effective_sl(self) -> float:
        """SL effectif — trailing si actif, sinon normal."""
        return self.trail_sl if self.trail_sl > 0 else self.sl

    def to_dict(self, current_price: float = 0.0) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "partial_exits"}
        d["partial_exits"] = [asdict(p) for p in self.partial_exits]
        d["last_funding_ts"] = None  # non sérialisable proprement
        if current_price > 0:
            d["unrealized_pnl"] = round(self.unrealized_pnl(current_price), 4)
            d["unrealized_pct"] = round(self.unrealized_pct(current_price), 2)
            d["realized_pnl"] = round(self.realized_pnl(), 4)
            d["current_price"] = current_price
        return d


@dataclass
class ClosedTrade:
    """Trade entièrement fermé — entrée dans le journal."""
    symbol: str
    side: str
    entry_price: float
    avg_exit_price: float    # prix moyen de sortie pondéré
    size_usdt: float         # capital initial du trade
    pnl_usdt: float          # PnL total net (après tous frais)
    pnl_pct: float           # PnL % par rapport à size_usdt
    fee_total: float
    funding_paid: float
    entry_ts: str
    exit_ts: str
    duration_min: float
    score: int
    exit_reason: str         # "sl" | "tp1" | "tp2" | "tp3" | "tp_cascade" | "manual"
    correlation_id: str
    source: str = "internal"
    # Contexte SMC (copié depuis la position à la fermeture)
    confs: List[str] = field(default_factory=list)
    regime: str = ""
    macro_risk: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Moteur principal ───────────────────────────────────────────────────────────

class PaperEngine:
    """Moteur de paper trading thread-safe (asyncio.Lock)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

        # Portefeuille
        self.initial_capital: float = PAPER_INITIAL_CAPITAL
        self.cash: float = PAPER_INITIAL_CAPITAL     # liquidités disponibles
        self.realized_pnl: float = 0.0               # PnL total cumulé réalisé

        # Positions et historique
        self.positions: Dict[str, PaperPosition] = {}
        self.trades: List[ClosedTrade] = []

        # Equity curve [{ts, equity, dd_pct}, ...]
        self._equity_curve: List[Dict[str, Any]] = [
            {"ts": datetime.now(timezone.utc).isoformat(),
             "equity": PAPER_INITIAL_CAPITAL, "dd_pct": 0.0}
        ]
        self._peak_equity: float = PAPER_INITIAL_CAPITAL

        # Prix connus pour calcul unrealized PnL
        self._last_prices: Dict[str, float] = {}

        self._load_state()

    # ── Propriétés ──────────────────────────────────────────────────────────────

    @property
    def equity(self) -> float:
        """Equity = cash + PnL réalisé (sans unrealized)."""
        return self.cash + self.realized_pnl

    def equity_with_unrealized(self) -> float:
        """Equity incluant le PnL non réalisé sur les positions ouvertes."""
        eq = self.cash + self.realized_pnl
        for sym, pos in self.positions.items():
            p = self._last_prices.get(sym, 0.0)
            if p > 0:
                eq += pos.unrealized_pnl(p)
        return eq

    @property
    def total_exposure_usdt(self) -> float:
        return sum(p.current_size_usdt() for p in self.positions.values())

    # ── Utilitaires ─────────────────────────────────────────────────────────────

    def _apply_slippage(self, price: float, side: str, is_exit: bool) -> float:
        """Applique slippage + demi-spread au prix d'entrée ou de sortie."""
        slip   = PAPER_SLIPPAGE_BPS / 10_000
        spread = PAPER_SPREAD_BPS   / 10_000 / 2
        bump   = slip + spread
        if side == "LONG":
            return price * (1 + bump) if not is_exit else price * (1 - bump)
        return price * (1 - bump) if not is_exit else price * (1 + bump)

    def _fee(self, size_usdt: float) -> float:
        return size_usdt * PAPER_FEE_BPS / 10_000

    def _position_size(
        self, equity: float, entry_price: float, sl: float
    ) -> Tuple[float, float]:
        """Calcule la taille (USDT, base) selon la règle de risque.

        size = (equity × PAPER_RISK_PCT) / sl_distance_pct
        Plafonné à equity × PAPER_MAX_EXPOSURE_PCT.
        """
        risk_usdt = equity * PAPER_RISK_PCT
        sl_pct    = abs(entry_price - sl) / entry_price if entry_price > 0 else 0.0

        if sl_pct < 0.0001:
            size_usdt = equity * 0.05  # fallback 5% si SL trop proche
        else:
            size_usdt = risk_usdt / sl_pct

        size_usdt = min(size_usdt, equity * PAPER_MAX_EXPOSURE_PCT)
        size_base = size_usdt / entry_price if entry_price > 0 else 0.0
        return size_usdt, size_base

    # ── Ouverture de position ────────────────────────────────────────────────────

    async def open_position(self, signal: Dict[str, Any]) -> Optional[PaperPosition]:
        """Ouvre une position paper à partir d'un signal.

        Returns la PaperPosition si acceptée, None sinon.
        """
        async with self._lock:
            sym    = signal.get("symbol", "")
            raw_side = str(signal.get("side", "")).upper()
            side   = "LONG" if raw_side in ("ACHAT", "LONG", "BUY") else "SHORT"
            price  = float(signal.get("price", 0))
            sl     = float(signal.get("sl", 0))
            tp1    = float(signal.get("tp1", 0))
            tp2    = float(signal.get("tp2", 0))
            tp3    = float(signal.get("tp3", 0))
            score      = int(signal.get("score", 0))
            cid        = signal.get("correlation_id", f"p_{int(time.time())}")
            source     = signal.get("source", "internal")
            atr        = float(signal.get("atr", 0))
            confs      = list(signal.get("confs", []))
            regime     = str(signal.get("regime", ""))
            macro_risk = float(signal.get("macro_risk", 0.0))
            rsi_val    = float(signal.get("rsi", 0.0))
            adx_val    = float(signal.get("adx", 0.0))

            # Validations de base
            if not sym or price <= 0 or sl <= 0:
                logger.debug(
                    "[PAPER] Signal refusé — données manquantes (sym=%s price=%.4f sl=%.4f)",
                    sym, price, sl,
                )
                return None

            # Validation logique SL
            if side == "LONG" and sl >= price:
                logger.debug("[PAPER] %s LONG refusé — SL (%.4f) >= prix (%.4f)", sym, sl, price)
                return None
            if side == "SHORT" and sl <= price:
                logger.debug("[PAPER] %s SHORT refusé — SL (%.4f) <= prix (%.4f)", sym, sl, price)
                return None

            # Pas de double position sur le même symbole
            if sym in self.positions:
                logger.debug("[PAPER] %s — position déjà ouverte, ignoré", sym)
                return None

            # Max positions simultanées
            if len(self.positions) >= PAPER_MAX_POSITIONS:
                logger.info("[PAPER] Max positions (%d) atteint", PAPER_MAX_POSITIONS)
                return None

            # Max exposition
            current_eq = self.equity_with_unrealized()
            if self.total_exposure_usdt >= current_eq * PAPER_MAX_EXPOSURE_PCT:
                logger.info(
                    "[PAPER] Exposition max (%.0f%%) atteinte",
                    PAPER_MAX_EXPOSURE_PCT * 100,
                )
                return None

            # Prix d'entrée réaliste
            entry_price = self._apply_slippage(price, side, is_exit=False)

            # Taille de position
            size_usdt, size_base = self._position_size(current_eq, entry_price, sl)

            # Vérification cash suffisant (frais inclus)
            fee_entry = self._fee(size_usdt)
            total_cost = size_usdt + fee_entry
            if total_cost > self.cash * 0.999:
                size_usdt = self.cash * 0.999 * (size_usdt / total_cost)
                fee_entry = self._fee(size_usdt)
                total_cost = size_usdt + fee_entry
                size_base = size_usdt / entry_price

            if size_usdt < 1.0:
                logger.warning("[PAPER] %s taille trop petite (%.2f$), ignoré", sym, size_usdt)
                return None

            # Déduire du cash
            self.cash -= total_cost

            # Trailing stop initial
            trail_sl = 0.0
            if PAPER_TRAILING_STOP and atr > 0:
                offset = atr * PAPER_TRAILING_PCT
                trail_sl = (entry_price - offset) if side == "LONG" else (entry_price + offset)

            pos = PaperPosition(
                symbol=sym,
                side=side,
                entry_price=entry_price,
                raw_entry_price=price,
                size_usdt=size_usdt,
                size_base=size_base,
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                entry_ts=datetime.now(timezone.utc).isoformat(),
                correlation_id=cid,
                score=score,
                source=source,
                fee_entry=fee_entry,
                trail_sl=trail_sl,
                last_funding_ts=time.monotonic(),
                confs=confs,
                regime=regime,
                macro_risk=macro_risk,
                rsi=rsi_val,
                adx=adx_val,
            )

            self.positions[sym] = pos
            self._last_prices[sym] = price
            self._update_equity_curve()
            await self._save_state_unsafe()

            logger.info(
                "[PAPER] ✅ OUVERTURE %s %s | prix=%.4f size=%.1f$ sl=%.4f "
                "tp1=%.4f tp2=%.4f tp3=%.4f | score=%d cid=%s",
                sym, side, entry_price, size_usdt, sl, tp1, tp2, tp3, score, cid,
            )
            return pos

    # ── Mise à jour des prix (appelée toutes les 5s depuis scan_loop) ────────────

    async def update_price(self, sym: str, current_price: float) -> List[str]:
        """Met à jour les positions ouvertes pour ce symbole.

        Vérifie SL, TPs, applique funding, met à jour le trailing stop.
        Returns: liste de messages de fermeture (pour logging externe).
        """
        messages: List[str] = []
        if current_price <= 0:
            return messages

        self._last_prices[sym] = current_price

        async with self._lock:
            pos = self.positions.get(sym)
            if pos is None:
                return messages

            # ── Funding (toutes les 8h) ──────────────────────────────────────
            elapsed = time.monotonic() - pos.last_funding_ts
            if elapsed >= _FUNDING_INTERVAL_SEC:
                n = int(elapsed / _FUNDING_INTERVAL_SEC)
                funding_usdt = pos.current_size_usdt() * (PAPER_FUNDING_RATE_8H / 100) * n
                if pos.side == "LONG":
                    # Long paye le funding quand taux positif (convention Binance)
                    pos.funding_paid += funding_usdt
                    self.cash -= funding_usdt
                else:
                    # Short reçoit le funding
                    pos.funding_paid -= funding_usdt
                    self.cash += funding_usdt
                pos.last_funding_ts += n * _FUNDING_INTERVAL_SEC

            # ── Trailing stop ────────────────────────────────────────────────
            if PAPER_TRAILING_STOP and pos.trail_sl > 0:
                # Distance = 1% du prix d'entrée × PAPER_TRAILING_PCT
                offset = pos.entry_price * 0.01 * PAPER_TRAILING_PCT
                if pos.side == "LONG":
                    new_ts = current_price - offset
                    if new_ts > pos.trail_sl:
                        pos.trail_sl = new_ts
                else:
                    new_ts = current_price + offset
                    if new_ts < pos.trail_sl:
                        pos.trail_sl = new_ts

            # ── Time-stop ────────────────────────────────────────────────────
            # Une position qui n'a touché ni SL ni TP après N heures est un
            # trade dont la thèse est invalidée — on la ferme au prix courant
            # plutôt que de la laisser dériver (cf. position PAXG restée
            # ouverte 90 jours pour finir à -11%).
            if PAPER_MAX_AGE_HOURS > 0:
                try:
                    t_entry = datetime.fromisoformat(pos.entry_ts.replace("Z", "+00:00"))
                    age_h = (datetime.now(timezone.utc) - t_entry).total_seconds() / 3600.0
                except Exception:
                    age_h = 0.0
                if age_h >= PAPER_MAX_AGE_HOURS:
                    msg = self._close_partial_unsafe(pos, current_price, pos.remaining_pct, "time_stop")
                    messages.append(msg)
                    logger.info("[PAPER] ⏱ TIME-STOP %s après %.0fh (max=%.0fh)",
                                sym, age_h, PAPER_MAX_AGE_HOURS)
                    trade = self._finalize_position_unsafe(sym, pos)
                    self._append_csv(trade)
                    self._update_equity_curve()
                    await self._save_state_unsafe()
                    return messages

            eff_sl = pos.effective_sl()

            # ── Vérification SL ──────────────────────────────────────────────
            sl_hit = (
                (pos.side == "LONG"  and current_price <= eff_sl) or
                (pos.side == "SHORT" and current_price >= eff_sl)
            )
            if sl_hit:
                msg = self._close_partial_unsafe(pos, current_price, pos.remaining_pct, "sl")
                messages.append(msg)
                trade = self._finalize_position_unsafe(sym, pos)
                self._append_csv(trade)
                self._update_equity_curve()
                await self._save_state_unsafe()
                return messages

            # ── TP1 ──────────────────────────────────────────────────────────
            if not pos.tp1_hit and pos.tp1 > 0:
                tp1_hit = (
                    (pos.side == "LONG"  and current_price >= pos.tp1) or
                    (pos.side == "SHORT" and current_price <= pos.tp1)
                )
                if tp1_hit:
                    msg = self._close_partial_unsafe(pos, pos.tp1, _TP1_FRACTION, "tp1")
                    messages.append(msg)
                    pos.tp1_hit = True
                    # Déplacer le SL au breakeven
                    if not pos.sl_at_be:
                        pos.sl = pos.entry_price
                        pos.trail_sl = 0.0   # désactiver trailing si BE atteint
                        pos.sl_at_be = True
                        logger.info(
                            "[PAPER] %s SL → breakeven (%.4f)", sym, pos.entry_price
                        )

            # ── TP2 ──────────────────────────────────────────────────────────
            if pos.tp1_hit and not pos.tp2_hit and pos.tp2 > 0:
                tp2_hit = (
                    (pos.side == "LONG"  and current_price >= pos.tp2) or
                    (pos.side == "SHORT" and current_price <= pos.tp2)
                )
                if tp2_hit:
                    msg = self._close_partial_unsafe(pos, pos.tp2, _TP2_FRACTION, "tp2")
                    messages.append(msg)
                    pos.tp2_hit = True

            # ── TP3 — ferme tout le restant ───────────────────────────────────
            if pos.tp2_hit and not pos.tp3_hit and pos.tp3 > 0:
                tp3_hit = (
                    (pos.side == "LONG"  and current_price >= pos.tp3) or
                    (pos.side == "SHORT" and current_price <= pos.tp3)
                )
                if tp3_hit:
                    msg = self._close_partial_unsafe(pos, pos.tp3, pos.remaining_pct, "tp3")
                    messages.append(msg)
                    pos.tp3_hit = True
                    trade = self._finalize_position_unsafe(sym, pos)
                    self._append_csv(trade)
                    self._update_equity_curve()
                    await self._save_state_unsafe()
                    return messages

            # ── Cas où TP2/TP3 = 0 : fermer entièrement à TP1 ───────────────
            if pos.tp1_hit and pos.tp2 <= 0 and pos.remaining_pct > 0.001:
                msg = self._close_partial_unsafe(pos, pos.tp1, pos.remaining_pct, "tp1")
                messages.append(msg)
                trade = self._finalize_position_unsafe(sym, pos)
                self._append_csv(trade)
                self._update_equity_curve()
                await self._save_state_unsafe()
                return messages

            if messages:
                self._update_equity_curve()
                await self._save_state_unsafe()

        return messages

    # ── Fermeture partielle (non thread-safe — appelée depuis update_price) ──────

    def _close_partial_unsafe(
        self,
        pos: PaperPosition,
        exit_price_raw: float,
        fraction: float,
        reason: str,
    ) -> str:
        """Ferme une fraction de la position originale.

        fraction : fraction de la position ORIGINALE (0..1).
        L'actual_fraction est clampée à remaining_pct pour éviter le dépassement.
        """
        actual = min(fraction, pos.remaining_pct)
        if actual <= 0:
            return f"{pos.symbol} aucune fraction à fermer ({reason})"

        exit_price = self._apply_slippage(exit_price_raw, pos.side, is_exit=True)
        closed_usdt = pos.size_usdt * actual
        fee_exit    = self._fee(closed_usdt)

        if pos.side == "LONG":
            raw_pnl = (exit_price - pos.entry_price) / pos.entry_price * closed_usdt
        else:
            raw_pnl = (pos.entry_price - exit_price) / pos.entry_price * closed_usdt

        pnl_net = raw_pnl - fee_exit

        # Libérer le cash (capital + PnL net)
        self.cash        += closed_usdt + pnl_net
        self.realized_pnl += pnl_net

        pos.remaining_pct -= actual
        pos.remaining_pct  = max(0.0, pos.remaining_pct)

        pos.partial_exits.append(PartialExit(
            exit_price=round(exit_price, 6),
            fraction_closed=round(actual, 4),
            pnl_usdt=round(pnl_net, 4),
            reason=reason,
            ts=datetime.now(timezone.utc).isoformat(),
        ))

        msg = (
            f"{pos.symbol} {pos.side} {reason.upper()} "
            f"prix={exit_price:.4f} pnl={pnl_net:+.2f}$ ({pnl_net/pos.size_usdt*100:+.1f}%)"
        )
        logger.info("[PAPER] %s", msg)
        return msg

    # ── Finalisation (non thread-safe) ────────────────────────────────────────

    def _finalize_position_unsafe(self, sym: str, pos: PaperPosition) -> ClosedTrade:
        """Supprime la position des positions ouvertes et crée l'entrée journal."""
        # Si il reste une fraction (edge case : TP3 sans TP1/TP2 préalables)
        if pos.remaining_pct > 0.001 and pos.partial_exits:
            last_price = pos.partial_exits[-1].exit_price
            self._close_partial_unsafe(pos, last_price, pos.remaining_pct, "manual")

        # Prix moyen de sortie pondéré
        exits = pos.partial_exits
        total_closed = sum(e.fraction_closed for e in exits)
        if total_closed > 0:
            avg_exit = sum(e.exit_price * e.fraction_closed for e in exits) / total_closed
        else:
            avg_exit = pos.entry_price

        total_pnl = sum(e.pnl_usdt for e in exits)
        pnl_pct   = (total_pnl / pos.size_usdt * 100) if pos.size_usdt > 0 else 0.0
        fee_exits  = sum(self._fee(e.fraction_closed * pos.size_usdt) for e in exits)
        fee_total  = pos.fee_entry + fee_exits

        # Durée
        try:
            t_entry = datetime.fromisoformat(pos.entry_ts.replace("Z", "+00:00"))
            t_exit  = datetime.now(timezone.utc)
            dur_min = (t_exit - t_entry).total_seconds() / 60
        except Exception:
            dur_min = 0.0

        # Raison principale
        reasons = [e.reason for e in exits]
        if "sl" in reasons:
            main_reason = "sl"
        elif all(r in ("tp1", "tp2", "tp3") for r in reasons) and len(set(reasons)) > 1:
            main_reason = "tp_cascade"
        else:
            main_reason = reasons[-1] if reasons else "unknown"

        trade = ClosedTrade(
            symbol=pos.symbol,
            side=pos.side,
            entry_price=round(pos.entry_price, 6),
            avg_exit_price=round(avg_exit, 6),
            size_usdt=round(pos.size_usdt, 4),
            pnl_usdt=round(total_pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            fee_total=round(fee_total, 4),
            funding_paid=round(pos.funding_paid, 4),
            entry_ts=pos.entry_ts,
            exit_ts=datetime.now(timezone.utc).isoformat(),
            duration_min=round(dur_min, 1),
            score=pos.score,
            exit_reason=main_reason,
            correlation_id=pos.correlation_id,
            source=pos.source,
            confs=list(pos.confs),
            regime=pos.regime,
            macro_risk=pos.macro_risk,
        )

        self.trades.append(trade)
        self.positions.pop(sym, None)

        logger.info(
            "[PAPER] 🔒 FERMÉ %s %s | pnl=%+.2f$ (%.1f%%) | raison=%s durée=%.0fmin",
            trade.symbol, trade.side, trade.pnl_usdt, trade.pnl_pct,
            trade.exit_reason, trade.duration_min,
        )
        return trade

    # ── Fermeture manuelle (publique) ─────────────────────────────────────────

    async def close_position_manual(
        self, sym: str, current_price: float
    ) -> Optional[ClosedTrade]:
        """Ferme manuellement une position au prix donné."""
        async with self._lock:
            pos = self.positions.get(sym)
            if pos is None:
                return None
            self._close_partial_unsafe(pos, current_price, pos.remaining_pct, "manual")
            trade = self._finalize_position_unsafe(sym, pos)
            self._append_csv(trade)
            self._update_equity_curve()
            await self._save_state_unsafe()
            return trade

    # ── Statistiques ─────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Statistiques complètes du compte paper."""
        eq    = self.equity_with_unrealized()
        total = len(self.trades)

        # Drawdown courant
        if eq > self._peak_equity:
            self._peak_equity = eq
        dd_pct = max(0.0, (self._peak_equity - eq) / self._peak_equity * 100)

        max_dd = max((p["dd_pct"] for p in self._equity_curve), default=0.0)

        base = {
            "equity":              round(eq, 2),
            "initial_capital":     round(self.initial_capital, 2),
            "cash":                round(self.cash, 2),
            "realized_pnl":        round(self.realized_pnl, 2),
            "total_pnl_pct":       round((eq - self.initial_capital) / self.initial_capital * 100, 2),
            "open_positions":      len(self.positions),
            "total_trades":        total,
            "max_drawdown_pct":    round(max_dd, 2),
            "current_drawdown_pct": round(dd_pct, 2),
            "mode":                "paper",
        }

        if total == 0:
            return {**base,
                    "winrate": 0.0, "avg_win_usdt": 0.0, "avg_loss_usdt": 0.0,
                    "expectancy_usdt": 0.0, "sharpe": 0.0, "wins": 0, "losses": 0,
                    "best_trade_pct": 0.0, "worst_trade_pct": 0.0, "total_fees": 0.0}

        wins   = [t for t in self.trades if t.pnl_usdt > 0]
        losses = [t for t in self.trades if t.pnl_usdt <= 0]
        wr     = len(wins) / total

        avg_win  = sum(t.pnl_usdt for t in wins)   / len(wins)   if wins   else 0.0
        avg_loss = sum(abs(t.pnl_usdt) for t in losses) / len(losses) if losses else 0.0
        expectancy = wr * avg_win - (1 - wr) * avg_loss

        # Sharpe annualisé
        returns = [t.pnl_pct for t in self.trades]
        sharpe  = 0.0
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            var_r  = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r  = math.sqrt(var_r)
            if std_r > 0:
                tpd = max(0.1, total / max(1.0, self._days_elapsed()))
                sharpe = round(mean_r / std_r * math.sqrt(252 * tpd), 2)

        return {
            **base,
            "wins":            len(wins),
            "losses":          len(losses),
            "winrate":         round(wr * 100, 1),
            "avg_win_usdt":    round(avg_win, 2),
            "avg_loss_usdt":   round(avg_loss, 2),
            "expectancy_usdt": round(expectancy, 2),
            "sharpe":          sharpe,
            "best_trade_pct":  round(max(t.pnl_pct for t in self.trades), 2),
            "worst_trade_pct": round(min(t.pnl_pct for t in self.trades), 2),
            "total_fees":      round(sum(t.fee_total for t in self.trades), 2),
        }

    def _days_elapsed(self) -> float:
        if not self.trades:
            return 1.0
        try:
            t0 = datetime.fromisoformat(self.trades[0].entry_ts.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(self.trades[-1].exit_ts.replace("Z", "+00:00"))
            return max(1.0, (t1 - t0).total_seconds() / 86400)
        except Exception:
            return 1.0

    # ── Equity curve ─────────────────────────────────────────────────────────────

    def _update_equity_curve(self) -> None:
        eq = self.equity_with_unrealized()
        if eq > self._peak_equity:
            self._peak_equity = eq
        dd = max(0.0, (self._peak_equity - eq) / self._peak_equity * 100) if self._peak_equity else 0.0
        self._equity_curve.append({
            "ts":     datetime.now(timezone.utc).isoformat(),
            "equity": round(eq, 2),
            "dd_pct": round(dd, 2),
        })
        # Limiter à 2000 points (≈ 4.6h à 5s/point)
        if len(self._equity_curve) > 2000:
            self._equity_curve = self._equity_curve[-2000:]

    def get_equity_curve(self, last_n: int = 200) -> List[Dict[str, Any]]:
        return self._equity_curve[-last_n:]

    # ── Persistance ──────────────────────────────────────────────────────────────

    async def _save_state_unsafe(self) -> None:
        """Sauvegarde l'état (non thread-safe — appeler depuis le lock)."""
        try:
            PAPER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            PAPER_JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Sérialiser les positions (retirer last_funding_ts non sérialisable proprement)
            pos_dict = {}
            for sym, pos in self.positions.items():
                d = asdict(pos)
                d.pop("last_funding_ts", None)
                pos_dict[sym] = d

            state = {
                "cash":          self.cash,
                "initial_capital": self.initial_capital,
                "realized_pnl":  self.realized_pnl,
                "peak_equity":   self._peak_equity,
                "positions":     pos_dict,
                "trades":        [asdict(t) for t in self.trades],
                "equity_curve":  self._equity_curve,
                "saved_at":      datetime.now(timezone.utc).isoformat(),
            }
            PAPER_STATE_FILE.write_text(
                json.dumps(state, indent=2, default=str), encoding="utf-8"
            )
            PAPER_JOURNAL_FILE.write_text(
                json.dumps([asdict(t) for t in self.trades], indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[PAPER] Erreur sauvegarde: %s", e)

    def _load_state(self) -> None:
        """Charge l'état persisté au démarrage."""
        try:
            if not PAPER_STATE_FILE.exists():
                return
            state = json.loads(PAPER_STATE_FILE.read_text(encoding="utf-8"))

            self.cash             = float(state.get("cash", PAPER_INITIAL_CAPITAL))
            self.initial_capital  = float(state.get("initial_capital", PAPER_INITIAL_CAPITAL))
            self.realized_pnl     = float(state.get("realized_pnl", 0.0))
            self._peak_equity     = float(state.get("peak_equity", self.initial_capital))
            saved_curve           = state.get("equity_curve", [])
            if saved_curve:
                self._equity_curve = saved_curve

            for sym, pd_ in state.get("positions", {}).items():
                partials = [PartialExit(**p) for p in pd_.pop("partial_exits", [])]
                pd_.pop("last_funding_ts", None)
                try:
                    pos = PaperPosition(**pd_)
                    pos.partial_exits  = partials
                    pos.last_funding_ts = time.monotonic()  # réinitialiser au démarrage
                    self.positions[sym] = pos
                except Exception as exc:
                    logger.warning("[PAPER] Reconstruction position %s: %s", sym, exc)

            for td in state.get("trades", []):
                try:
                    self.trades.append(ClosedTrade(**td))
                except Exception:
                    pass

            logger.info(
                "[PAPER] État chargé — cash=%.2f$ trades=%d positions=%d",
                self.cash, len(self.trades), len(self.positions),
            )
        except Exception as e:
            logger.warning("[PAPER] Impossible de charger l'état: %s", e)

    def _append_csv(self, trade: ClosedTrade) -> None:
        try:
            PAPER_JOURNAL_CSV.parent.mkdir(parents=True, exist_ok=True)
            needs_header = not PAPER_JOURNAL_CSV.exists()
            row = trade.to_dict()
            with PAPER_JOURNAL_CSV.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                if needs_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as e:
            logger.warning("[PAPER] CSV write: %s", e)

    # ── Reset ────────────────────────────────────────────────────────────────────

    async def reset(self) -> None:
        """Remet le compte paper à zéro (irréversible)."""
        async with self._lock:
            self.cash             = PAPER_INITIAL_CAPITAL
            self.initial_capital  = PAPER_INITIAL_CAPITAL
            self.realized_pnl     = 0.0
            self._peak_equity     = PAPER_INITIAL_CAPITAL
            self.positions        = {}
            self.trades           = []
            self._equity_curve    = [{
                "ts":     datetime.now(timezone.utc).isoformat(),
                "equity": PAPER_INITIAL_CAPITAL,
                "dd_pct": 0.0,
            }]
            await self._save_state_unsafe()
            logger.info("[PAPER] Compte réinitialisé (capital=%.2f$)", PAPER_INITIAL_CAPITAL)
