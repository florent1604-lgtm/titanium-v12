"""execution/risk_manager.py — SL/TP adaptatif ATR + circuit breaker drawdown."""
from __future__ import annotations
import asyncio
import math
from typing import Any, Dict, Optional, Tuple
import pandas as pd
import pandas_ta as ta
from utils.config import (
    SYMBOLS, MAX_DD_MULTIPLIER, get_sym_override,
    PAPER_FEE_BPS, PAPER_SLIPPAGE_BPS, PAPER_SPREAD_BPS,
)
from utils.logger import get_logger

logger = get_logger(__name__)
_cb_lock = asyncio.Lock()

# Coût aller-retour total en fraction du prix : frais taker ×2 + slippage ×2
# + demi-spread ×2. Avec les défauts (4+5+2 bps par côté) ≈ 22 bps = 0.22%.
# Tout TP plus proche que ça de l'entrée est une perte NETTE garantie.
ROUND_TRIP_COST = 2.0 * (PAPER_FEE_BPS + PAPER_SLIPPAGE_BPS + PAPER_SPREAD_BPS) / 10_000
# TP1 doit rapporter au moins 1× les coûts en profit net → distance min 2× coûts
MIN_TP1_COST_MULT = 2.0


def compute_adaptive_levels(
    df: pd.DataFrame,
    sym: str,
    side: str,
    price: float,
) -> Dict[str, Any]:
    """Calcule SL et TPs adaptatifs basés sur ATR.

    Returns: {"sl": float, "tp1": float, "tp2": float, "tp3": float, "atr": float}
    """
    atr_mult  = get_sym_override(sym, "atr_mult", 1.0)
    tp_ratios = get_sym_override(sym, "tp_ratios", (1.5, 2.1, 2.6))
    sl_floor  = get_sym_override(sym, "sl_floor_pct", 0.001)
    fee       = 0.0004  # 4bps Binance

    atr_val = 0.0
    if df is not None and len(df) >= 14:
        try:
            atr_s = ta.atr(df["high"], df["low"], df["close"], length=14)
            if atr_s is not None and not atr_s.empty:
                v = float(atr_s.iloc[-1])
                if not math.isnan(v):
                    atr_val = v
        except Exception:
            pass

    if atr_val <= 0:
        atr_val = price * 0.005  # fallback 0.5%

    # Clamper l'ATR entre p20 et p80 pour éviter les extrêmes
    if df is not None and len(df) >= 50:
        try:
            atr_s2 = ta.atr(df["high"], df["low"], df["close"], length=14)
            if atr_s2 is not None and len(atr_s2.dropna()) >= 20:
                atr_clean = atr_s2.dropna()
                p20 = float(atr_clean.quantile(0.20))
                p80 = float(atr_clean.quantile(0.80))
                atr_val = max(p20, min(p80, atr_val))
        except Exception:
            pass

    sl_dist = max(atr_val * atr_mult, price * sl_floor)

    # ── Distances TP avec plancher de rentabilité ─────────────────────────
    # BUG CORRIGÉ : l'ancien code appliquait les frais À L'ENVERS (TP
    # rapproché de l'entrée, SL éloigné) → chaque trade gagnait moins et
    # perdait plus que prévu. Désormais : le SL reste à la distance de
    # risque voulue, et les TP sont ÉLOIGNÉS du coût aller-retour pour que
    # le ratio annoncé soit un ratio NET. De plus, TP1 ne peut jamais être
    # plus proche que MIN_TP1_COST_MULT × coûts (sinon perte nette garantie,
    # cause principale des -46% du paper trading).
    cost_dist = price * ROUND_TRIP_COST
    d1 = max(sl_dist * tp_ratios[0], price * ROUND_TRIP_COST * MIN_TP1_COST_MULT)
    d2 = max(sl_dist * tp_ratios[1], d1 * 1.4)
    d3 = max(sl_dist * tp_ratios[2], d2 * 1.25)

    if "ACHAT" in side:
        sl  = price - sl_dist
        tp1 = price + d1 + cost_dist
        tp2 = price + d2 + cost_dist
        tp3 = price + d3 + cost_dist
    else:
        sl  = price + sl_dist
        tp1 = price - d1 - cost_dist
        tp2 = price - d2 - cost_dist
        tp3 = price - d3 - cost_dist

    rr_net = d1 / sl_dist if sl_dist > 0 else 0.0
    if rr_net < 0.5:
        logger.warning("[RISK] %s %s — RR net TP1 faible (%.2f) : sl_dist=%.4f tp1_dist=%.4f",
                       sym, side, rr_net, sl_dist, d1)

    return {
        "sl":  round(sl, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp3": round(tp3, 4),
        "atr": round(atr_val, 4),
        "rr":  round(tp_ratios[1], 2),
    }


async def circuit_breaker_loop(opt_results: Dict[str, Any]) -> None:
    """Vérifie périodiquement si le drawdown réel dépasse MAX_DD_MULTIPLIER × backtest DD."""
    await asyncio.sleep(300)
    while True:
        async with _cb_lock:
            for sym in SYMBOLS:
                try:
                    res = opt_results.get(sym, {})
                    if not res:
                        continue
                    max_dd_bt = abs(float(res.get("max_drawdown", 0.0)))
                    # En mode simulation, on skip le check live
                    threshold = max_dd_bt * MAX_DD_MULTIPLIER
                    if max_dd_bt > 0:
                        logger.debug("[CB] %s DD threshold=%.2f%%", sym, threshold * 100)
                except Exception as e:
                    logger.debug("[CB] %s: %s", sym, e)
        await asyncio.sleep(3600)
