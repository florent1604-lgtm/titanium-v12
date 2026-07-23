"""core/swing_engine.py — Moteur SWING multi-actifs sur données MT5 (paper only).

Forward paper test des configs par actif VALIDÉES sur le tester natif MT5
(fills réels Axi, 3,5 ans — voir docs/RAPPORT_REVALIDATION.md) : USTECH,
NAS100.fs, HSI.fs en swing H4. Chaque actif utilise SA propre config, chargée
depuis data/asset_configs.json (SL×ATR, ladder TP, filtres align/RSI, timeframe,
time-stop). Aucun ordre réel : MT5 = flux de données, compte Axi live intouché.

Décisions sur BARRE CLÔTURÉE du timeframe de l'actif (iloc[-2]) ; gestion des
positions au tick toutes les SWING_SCAN_SECONDS. État : data/swing_paper_state.json.
Séparé du moteur forex V3 (core/forex_engine.py) pour ne pas le perturber.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils.config import (
    SWING_CAPITAL, SWING_LIVE_SYMBOLS, SWING_RISK_PCT, SWING_SCAN_SECONDS,
)
from utils.logger import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "swing_paper_state.json"
CONFIGS_PATH = ROOT / "data" / "asset_configs.json"
AUTO_CONFIGS_PATH = ROOT / "data" / "swing_auto_configs.json"
PARTS = (0.33, 0.33, 0.34)
BARS_PER_DAY = {"M15": 96, "H1": 24, "H4": 6, "D1": 1}

swing_state: Dict[str, Any] = {
    "enabled": True, "mode": "paper", "capital": SWING_CAPITAL,
    "equity": SWING_CAPITAL, "positions": {}, "trades": [],
    "last_scan": None, "last_signal": {}, "errors": [], "scan_count": 0,
}
_configs: Dict[str, dict] = {}


def _load_configs() -> None:
    """Charge le panier SWING_LIVE_SYMBOLS (asset_configs.json) + les actifs
    auto-découverts par le scan d'opportunités (swing_auto_configs.json)."""
    _configs.clear()
    if CONFIGS_PATH.exists():
        data = json.loads(CONFIGS_PATH.read_text(encoding="utf-8")).get("assets", {})
        for sym in SWING_LIVE_SYMBOLS:
            if sym in data:
                _configs[sym] = data[sym]
            else:
                logger.warning("[SWING] %s absent de asset_configs.json — ignoré", sym)
    else:
        logger.warning("[SWING] asset_configs.json absent — panier de base vide")
    if AUTO_CONFIGS_PATH.exists():
        try:
            auto = json.loads(AUTO_CONFIGS_PATH.read_text(encoding="utf-8")).get("assets", {})
            for sym, cfg in auto.items():
                if sym not in _configs:
                    cfg = dict(cfg); cfg["auto"] = True
                    _configs[sym] = cfg
        except Exception as e:
            logger.warning("[SWING] swing_auto_configs illisible: %s", e)
    logger.info("[SWING] Configs chargées: %s", list(_configs))


def reload_configs() -> list:
    """Recharge les configs à chaud (appelé après auto-intégration du scan)."""
    _load_configs()
    return list(_configs)


def _save() -> None:
    try:
        from utils.atomic_state import save_json_atomic
        save_json_atomic(STATE_PATH, swing_state)   # R2 : atomique + sérialisé
    except Exception as e:
        logger.warning("[SWING] Sauvegarde état échouée: %s", e)


def _load() -> None:
    if STATE_PATH.exists():
        try:
            swing_state.update(json.loads(STATE_PATH.read_text(encoding="utf-8")))
            swing_state["errors"] = []
        except Exception as e:
            logger.warning("[SWING] État illisible (%s) — repart à neuf", e)


def _signal(df, cfg: dict) -> Optional[str]:
    """'long'/'short'/None sur la dernière barre CLÔTURÉE, selon la config actif
    (align/RSI paramétrables — reflète tools/asset_optimizer.entries())."""
    from tools.strategy_lab import add_indicators
    df = add_indicators(df.copy())
    if len(df) < 210:
        return None
    cur, prev = df.iloc[-2], df.iloc[-3]
    bias_up = cur["close"] > cur["ema200"]
    x_up = cur["trix"] > cur["trix_sig"] and prev["trix"] <= prev["trix_sig"]
    x_dn = cur["trix"] < cur["trix_sig"] and prev["trix"] >= prev["trix_sig"]
    lg, sh = bias_up and x_up, (not bias_up) and x_dn
    if cfg.get("rsi_gate"):
        lg = lg and cur["rsi"] < 55
        sh = sh and cur["rsi"] > 45
    if cfg.get("align_ema50"):
        slope_up = cur["ema50"] > df["ema50"].iloc[-7]
        lg = lg and slope_up
        sh = sh and (not slope_up)
    return "long" if lg else ("short" if sh else None)


def _atr(df) -> float:
    from tools.strategy_lab import add_indicators
    return float(add_indicators(df.copy())["atr"].iloc[-2])


def _open_position(sym: str, side: str, price: float, atr: float, cfg: dict) -> bool:
    sign = 1 if side == "long" else -1
    sl_mult = float(cfg["sl_atr"])
    sl = price - sign * sl_mult * atr
    risk_eur = swing_state["equity"] * SWING_RISK_PCT / 100
    notional = risk_eur / (sl_mult * atr / price)
    def insert_position() -> None:
        swing_state["positions"][sym] = {
            "side": side, "entry": price, "sl": sl, "style": cfg.get("style", "swing"),
            "tf": cfg.get("tf", "H4"),
            "tps": [price + sign * m * atr for m in cfg["tp_ladder"]],
            "filled": [0.0, 0.0, 0.0], "notional_eur": round(notional, 2),
            "atr": atr, "pnl_eur": 0.0,
            "time_stop_bars": int(cfg.get("time_stop_bars", 60)),
            "opened": datetime.now(timezone.utc).isoformat(),
        }

    # R3c : check + insertion sous le verrou portefeuille commun aux moteurs.
    from core.portfolio_risk import check_and_insert
    ok, reason = check_and_insert(
        "swing", sym, notional, swing_state["equity"], side, insert_position,
    )
    if not ok:
        logger.info("[SWING] %s NON ouvert — risque portefeuille: %s", sym, reason)
        return False
    logger.info("[SWING] %s %s @ %.2f — SL %.2f, notional %.0f EUR (paper)",
                sym, side.upper(), price, sl, notional)
    return True


def _close_part(pos: dict, exit_price: float, part: float) -> None:
    sign = 1 if pos["side"] == "long" else -1
    pos["pnl_eur"] += part * pos["notional_eur"] * sign * (exit_price - pos["entry"]) / pos["entry"]


def _finalize(sym: str, pos: dict, reason: str) -> None:
    swing_state["equity"] = round(swing_state["equity"] + pos["pnl_eur"], 2)
    swing_state["trades"].append({
        "symbol": sym, "side": pos["side"], "entry": pos["entry"],
        "pnl_eur": round(pos["pnl_eur"], 2), "exit_reason": reason,
        "opened": pos["opened"], "closed": datetime.now(timezone.utc).isoformat(),
    })
    swing_state["trades"] = swing_state["trades"][-200:]
    del swing_state["positions"][sym]
    logger.info("[SWING] %s fermé (%s) — PnL %.2f EUR — equity %.2f",
                sym, reason, swing_state["trades"][-1]["pnl_eur"], swing_state["equity"])


def _manage_position(sym: str, tick: dict) -> None:
    pos = swing_state["positions"].get(sym)
    if not pos:
        return
    sign = 1 if pos["side"] == "long" else -1
    px = tick["bid"] if pos["side"] == "long" else tick["ask"]
    # Time-stop (barres → heures selon le TF de l'actif)
    hours = pos["time_stop_bars"] * (24.0 / BARS_PER_DAY.get(pos.get("tf", "H4"), 6))
    opened = datetime.fromisoformat(pos["opened"])
    if (datetime.now(timezone.utc) - opened).total_seconds() > hours * 3600:
        _close_part(pos, px, 1.0 - sum(pos["filled"]))
        _finalize(sym, pos, "time_stop")
        return
    # Stop-loss
    if (px - pos["sl"]) * sign <= 0:
        _close_part(pos, pos["sl"], 1.0 - sum(pos["filled"]))
        _finalize(sym, pos, "sl" if sum(pos["filled"]) == 0 else "sl_be")
        return
    # Take-profits partiels + break-even après TP1
    for k, tp in enumerate(pos["tps"]):
        if pos["filled"][k] == 0 and (px - tp) * sign >= 0:
            pos["filled"][k] = PARTS[k]
            _close_part(pos, tp, PARTS[k])
            if k == 0:
                pos["sl"] = pos["entry"]
    if sum(pos["filled"]) >= 0.999:
        _finalize(sym, pos, "tp_cascade")


_scan_lock = asyncio.Lock()


async def scan_once() -> Dict[str, Any]:
    # R1 (revue Codex) : sérialise les scans (boucle + POST /scan) pour que le
    # dédoublonnage par barre soit ATOMIQUE — sinon deux scans concurrents peuvent
    # tous deux passer le check last_bar sur la même barre avant l'ouverture.
    async with _scan_lock:
        return await _scan_once_body()


async def _scan_once_body() -> Dict[str, Any]:
    from data.mt5_provider import get_rates, get_tick
    report = {"signals": {}, "managed": [], "skipped": []}
    for sym, cfg in _configs.items():
        try:
            tick = await asyncio.to_thread(get_tick, sym)
            if not tick or tick["stale"]:
                report["skipped"].append(f"{sym}: marché fermé/tick indisponible")
                continue
            _manage_position(sym, tick)
            report["managed"].append(sym)
            if sym not in swing_state["positions"]:
                df = await asyncio.to_thread(get_rates, sym, cfg.get("tf", "H4"), 320)
                if df is None or len(df) < 2:
                    continue
                bar_ts = df.index[-2].isoformat()   # barre de décision clôturée
                side = await asyncio.to_thread(_signal, df, cfg)
                swing_state["last_signal"][sym] = {
                    "side": side, "ts": datetime.now(timezone.utc).isoformat()}
                if side:
                    # R1 anti ré-entrée : une SEULE entrée par barre clôturée.
                    # (sinon, après une fermeture, le même signal de la barre encore
                    #  courante rouvrirait la position au scan suivant.)
                    if swing_state.setdefault("last_bar", {}).get(sym) == bar_ts:
                        report["skipped"].append(f"{sym}: barre {bar_ts} déjà tradée (anti ré-entrée)")
                    else:
                        atr = await asyncio.to_thread(_atr, df)
                        price = tick["ask"] if side == "long" else tick["bid"]
                        if _open_position(sym, side, price, atr, cfg):
                            swing_state["last_bar"][sym] = bar_ts
                            report["signals"][sym] = side
                            # Étape D : miroir DÉMO réel (fail-closed, non fatal)
                            from execution.demo_bridge import place_demo_async
                            await place_demo_async(sym, side, atr,
                                                   sl_atr_mult=float(cfg["sl_atr"]),
                                                   tp_atr_mult=float(cfg["tp_ladder"][-1]),
                                                   engine="swing")
                        else:
                            report["skipped"].append(f"{sym}: ouverture bloquée (risque portefeuille)")
        except Exception as e:
            swing_state["errors"] = (swing_state["errors"] + [f"{sym}: {e}"])[-5:]
            logger.warning("[SWING] scan %s: %s", sym, e)
    swing_state["last_scan"] = datetime.now(timezone.utc).isoformat()
    swing_state["scan_count"] += 1
    _save()
    return report


async def swing_engine_loop() -> None:
    """Boucle du moteur swing — démarrée dans le lifespan si SWING_ENABLED."""
    _load_configs()
    _load()
    logger.info("[SWING] Moteur démarré — panier %s, scan %ds, paper only",
                list(_configs), SWING_SCAN_SECONDS)
    while True:
        try:
            await scan_once()
        except asyncio.CancelledError:
            _save()
            raise
        except Exception as e:
            logger.warning("[SWING] boucle: %s", e)
        await asyncio.sleep(SWING_SCAN_SECONDS)


def get_stats() -> Dict[str, Any]:
    tr = swing_state["trades"]
    wins = [t for t in tr if t["pnl_eur"] > 0]
    return {
        "mode": "paper", "capital": SWING_CAPITAL, "equity": swing_state["equity"],
        "total_pnl_eur": round(swing_state["equity"] - SWING_CAPITAL, 2),
        "trades": len(tr), "wins": len(wins),
        "winrate_pct": round(100 * len(wins) / len(tr), 1) if tr else None,
        "open_positions": len(swing_state["positions"]),
        "last_scan": swing_state["last_scan"], "scan_count": swing_state["scan_count"],
        "symbols": list(_configs) or SWING_LIVE_SYMBOLS,
        "errors": swing_state["errors"],
    }


def get_configs() -> Dict[str, dict]:
    return _configs or {}
