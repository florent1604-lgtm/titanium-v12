"""core/forex_engine.py — Moteur forex/or V3 sur données MT5 (Axi), paper only.

Stratégie appliquée : la variante V3 validée par tools/strategy_lab.py le
08/07/2026 (EURUSD PF 1.80, GBPUSD PF 2.02, XAU +3.4 bps/trade, 365 j) :
  - biais EMA200-H1 + pente EMA50-H1 dans le même sens (anti contre-mouvement)
  - déclencheur : croisement TRIX(15,9) dans le sens du biais + pullback RSI
  - SL = ATR×FOREX_SL_ATR (2.0) ; TP partiels 33/33/34 à 1.5/2.5/4×ATR
  - SL ramené au break-even après TP1 ; time-stop FOREX_TIME_STOP_HOURS

Décisions sur BARRE H1 CLÔTURÉE uniquement ; gestion des positions au tick
(toutes les FOREX_SCAN_SECONDS). État persisté dans data/forex_paper_state.json.
Aucun ordre réel : MT5 sert de flux de données (compte Axi live intouché).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils.config import (
    FOREX_CAPITAL, FOREX_MONITOR_SYMBOLS, FOREX_RISK_PCT, FOREX_SCAN_SECONDS,
    FOREX_SL_ATR, FOREX_SYMBOLS, FOREX_TIME_STOP_HOURS, FOREX_TPS,
)
from utils.logger import get_logger

logger = get_logger(__name__)

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "forex_paper_state.json"
PARTS = (0.33, 0.33, 0.34)

forex_state: Dict[str, Any] = {
    "enabled": True, "mode": "paper", "capital": FOREX_CAPITAL,
    "equity": FOREX_CAPITAL, "positions": {}, "trades": [],
    "last_scan": None, "last_signal": {}, "errors": [], "scan_count": 0,
}


def _save() -> None:
    try:
        from utils.atomic_state import save_json_atomic
        save_json_atomic(STATE_PATH, forex_state)   # R2 : atomique + sérialisé
    except Exception as e:
        logger.warning("[FOREX] Sauvegarde état échouée: %s", e)


def _load() -> None:
    if STATE_PATH.exists():
        try:
            saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            forex_state.update(saved)
            forex_state["errors"] = []
        except Exception as e:
            logger.warning("[FOREX] État illisible (%s) — repart à neuf", e)


def _v3_signal(df) -> Optional[str]:
    """Retourne 'long'/'short'/None sur la DERNIÈRE BARRE CLÔTURÉE (iloc[-2])."""
    from tools.strategy_lab import add_indicators
    df = add_indicators(df.copy())
    if len(df) < 60:
        return None
    cur, prev = df.iloc[-2], df.iloc[-3]
    bias_up  = cur["close"] > cur["ema200"]
    slope_up = cur["ema50"] > df["ema50"].iloc[-7]
    x_up = cur["trix"] > cur["trix_sig"] and prev["trix"] <= prev["trix_sig"]
    x_dn = cur["trix"] < cur["trix_sig"] and prev["trix"] >= prev["trix_sig"]
    if bias_up and slope_up and x_up and cur["rsi"] < 55:
        return "long"
    if (not bias_up) and (not slope_up) and x_dn and cur["rsi"] > 45:
        return "short"
    return None


def _atr(df) -> float:
    from tools.strategy_lab import add_indicators
    return float(add_indicators(df.copy())["atr"].iloc[-2])


def _open_position(sym: str, side: str, price: float, atr: float) -> bool:
    sign = 1 if side == "long" else -1
    sl = price - sign * FOREX_SL_ATR * atr
    risk_eur = forex_state["equity"] * FOREX_RISK_PCT / 100
    notional = risk_eur / (FOREX_SL_ATR * atr / price)   # taille telle que SL = risk_eur
    def insert_position() -> None:
        forex_state["positions"][sym] = {
            "side": side, "entry": price, "sl": sl,
            "tps": [price + sign * m * atr for m in FOREX_TPS],
            "filled": [0.0, 0.0, 0.0], "notional_eur": round(notional, 2),
            "atr": atr, "pnl_eur": 0.0,
            "opened": datetime.now(timezone.utc).isoformat(),
        }

    # R3c : check + insertion sous le verrou portefeuille commun aux moteurs.
    from core.portfolio_risk import check_and_insert
    ok, reason = check_and_insert(
        "forex", sym, notional, forex_state["equity"], side, insert_position,
    )
    if not ok:
        logger.info("[FOREX] %s NON ouvert — risque portefeuille: %s", sym, reason)
        return False
    logger.info("[FOREX] %s %s @ %.5f — SL %.5f, notional %.0f EUR (paper)",
                sym, side.upper(), price, sl, notional)
    return True


def _close_part(sym: str, pos: dict, exit_price: float, part: float,
                reason: str) -> None:
    sign = 1 if pos["side"] == "long" else -1
    pnl = part * pos["notional_eur"] * sign * (exit_price - pos["entry"]) / pos["entry"]
    pos["pnl_eur"] += pnl


def _finalize(sym: str, pos: dict, reason: str) -> None:
    forex_state["equity"] = round(forex_state["equity"] + pos["pnl_eur"], 2)
    forex_state["trades"].append({
        "symbol": sym, "side": pos["side"], "entry": pos["entry"],
        "pnl_eur": round(pos["pnl_eur"], 2), "exit_reason": reason,
        "opened": pos["opened"], "closed": datetime.now(timezone.utc).isoformat(),
    })
    forex_state["trades"] = forex_state["trades"][-200:]
    del forex_state["positions"][sym]
    logger.info("[FOREX] %s fermé (%s) — PnL %.2f EUR — equity %.2f",
                sym, reason, forex_state["trades"][-1]["pnl_eur"], forex_state["equity"])


def _manage_position(sym: str, tick: dict) -> None:
    pos = forex_state["positions"].get(sym)
    if not pos:
        return
    sign = 1 if pos["side"] == "long" else -1
    px = tick["bid"] if pos["side"] == "long" else tick["ask"]

    # Time-stop
    opened = datetime.fromisoformat(pos["opened"])
    if (datetime.now(timezone.utc) - opened).total_seconds() > FOREX_TIME_STOP_HOURS * 3600:
        rest = 1.0 - sum(pos["filled"])
        _close_part(sym, pos, px, rest, "time_stop")
        _finalize(sym, pos, "time_stop")
        return
    # Stop-loss
    if (px - pos["sl"]) * sign <= 0:
        rest = 1.0 - sum(pos["filled"])
        _close_part(sym, pos, pos["sl"], rest, "sl")
        _finalize(sym, pos, "sl" if sum(pos["filled"]) == 0 else "sl_be")
        return
    # Take-profits partiels
    for k, tp in enumerate(pos["tps"]):
        if pos["filled"][k] == 0 and (px - tp) * sign >= 0:
            pos["filled"][k] = PARTS[k]
            _close_part(sym, pos, tp, PARTS[k], f"tp{k+1}")
            if k == 0:
                pos["sl"] = pos["entry"]        # break-even après TP1
    if sum(pos["filled"]) >= 0.999:
        _finalize(sym, pos, "tp_cascade")


_scan_lock = asyncio.Lock()


async def scan_once() -> Dict[str, Any]:
    # R1 (revue Codex) : sérialise les scans pour un dédoublonnage par barre atomique.
    async with _scan_lock:
        return await _scan_once_body()


async def _scan_once_body() -> Dict[str, Any]:
    """Un cycle : gestion des positions au tick + entrées sur barre H1 close."""
    from data.mt5_provider import get_rates_h1, get_tick
    report = {"signals": {}, "managed": [], "skipped": [], "monitored": {}}

    # Symboles surveillés en data seulement (ex: BTCUSD — backtest V3 non rentable
    # en CFD, on affiche le prix mais on ne trade pas).
    for sym in FOREX_MONITOR_SYMBOLS:
        try:
            tick = await asyncio.to_thread(get_tick, sym)
            if tick and not tick["stale"]:
                report["monitored"][sym] = round(tick["mid"], 2)
                forex_state.setdefault("monitored", {})[sym] = {
                    "mid": tick["mid"], "ts": tick["ts"]}
        except Exception:
            pass

    for sym in FOREX_SYMBOLS:
        try:
            tick = await asyncio.to_thread(get_tick, sym)
            if not tick or tick["stale"]:
                report["skipped"].append(f"{sym}: marché fermé/tick indisponible")
                continue
            _manage_position(sym, tick)
            report["managed"].append(sym)

            if sym not in forex_state["positions"]:
                df = await asyncio.to_thread(get_rates_h1, sym, 300)
                if df is None or len(df) < 2:
                    continue
                bar_ts = df.index[-2].isoformat()   # barre H1 de décision clôturée
                side = await asyncio.to_thread(_v3_signal, df)
                forex_state["last_signal"][sym] = {
                    "side": side, "ts": datetime.now(timezone.utc).isoformat()}
                if side:
                    # R1 anti ré-entrée : une SEULE entrée par barre clôturée.
                    if forex_state.setdefault("last_bar", {}).get(sym) == bar_ts:
                        report["skipped"].append(f"{sym}: barre {bar_ts} déjà tradée (anti ré-entrée)")
                    else:
                        atr = await asyncio.to_thread(_atr, df)
                        price = tick["ask"] if side == "long" else tick["bid"]
                        if _open_position(sym, side, price, atr):
                            forex_state["last_bar"][sym] = bar_ts
                            report["signals"][sym] = side
                            # Étape D : miroir DÉMO réel (fail-closed, non fatal)
                            from execution.demo_bridge import place_demo_async
                            await place_demo_async(sym, side, atr,
                                                   sl_atr_mult=FOREX_SL_ATR,
                                                   tp_atr_mult=FOREX_TPS[-1],
                                                   engine="forex")
                        else:
                            report["skipped"].append(f"{sym}: ouverture bloquée (risque portefeuille)")
        except Exception as e:
            forex_state["errors"] = (forex_state["errors"] + [f"{sym}: {e}"])[-5:]
            logger.warning("[FOREX] scan %s: %s", sym, e)
    forex_state["last_scan"] = datetime.now(timezone.utc).isoformat()
    forex_state["scan_count"] += 1
    _save()
    return report


async def forex_engine_loop() -> None:
    """Boucle du moteur forex — démarrée dans le lifespan si FOREX_ENABLED."""
    _load()
    logger.info("[FOREX] Moteur V3 démarré — %s, scan %ds, SL ATR×%.1f, paper only",
                FOREX_SYMBOLS, FOREX_SCAN_SECONDS, FOREX_SL_ATR)
    while True:
        try:
            await scan_once()
        except asyncio.CancelledError:
            _save()
            raise
        except Exception as e:
            logger.warning("[FOREX] boucle: %s", e)
        await asyncio.sleep(FOREX_SCAN_SECONDS)


def get_stats() -> Dict[str, Any]:
    tr = forex_state["trades"]
    wins = [t for t in tr if t["pnl_eur"] > 0]
    return {
        "mode": "paper", "capital": FOREX_CAPITAL,
        "equity": forex_state["equity"],
        "total_pnl_eur": round(forex_state["equity"] - FOREX_CAPITAL, 2),
        "trades": len(tr), "wins": len(wins),
        "winrate_pct": round(100 * len(wins) / len(tr), 1) if tr else None,
        "open_positions": len(forex_state["positions"]),
        "last_scan": forex_state["last_scan"], "scan_count": forex_state["scan_count"],
        "symbols": FOREX_SYMBOLS, "errors": forex_state["errors"],
    }
