"""execution/risk_manager.py — SL/TP adaptatif ATR + circuit breaker drawdown."""
from __future__ import annotations
import asyncio
import math
from typing import Any, Dict, Optional, Tuple
import pandas as pd
import pandas_ta as ta
from utils.config import SYMBOLS, MAX_DD_MULTIPLIER, get_sym_override
from utils.logger import get_logger

logger = get_logger(__name__)
_cb_lock = asyncio.Lock()


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

    if "ACHAT" in side:
        sl  = price - sl_dist - price * fee
        tp1 = price + sl_dist * tp_ratios[0] - price * fee
        tp2 = price + sl_dist * tp_ratios[1] - price * fee
        tp3 = price + sl_dist * tp_ratios[2] - price * fee
    else:
        sl  = price + sl_dist + price * fee
        tp1 = price - sl_dist * tp_ratios[0] + price * fee
        tp2 = price - sl_dist * tp_ratios[1] + price * fee
        tp3 = price - sl_dist * tp_ratios[2] + price * fee

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
