"""engine/strict_engine.py — STRICT TRIX walk-forward recalibration.

Fixes appliqués :
  - Sharpe annualisé par trades/jour (pas sqrt(252) flat sur returns par trade)
  - Filtre EMA200 sur les entrées TRIX → réduit les faux signaux en range
  - STRICT_MIN_TRADES relevé (config) pour éviter les Sharpe non significatifs
  - Sanity check sur les paramètres générés
"""
from __future__ import annotations
import asyncio
import math
import random
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
from utils.config import (
    SYMBOLS, STRICT_TF, STRICT_RECALIB_DAYS, STRICT_IN_SAMPLE_DAYS,
    STRICT_SUBPERIOD_DAYS, STRICT_ROBUST_MIN, STRICT_SHARPE_FLOOR,
    STRICT_MIN_TRADES, STRICT_RANDOM_ITERS, STRICT_FEE_BPS,
    STRICT_TOPK_ZONES, STRICT_ZONE_MIN_DIST,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_strict_params: Dict[str, Dict[str, Any]] = {s: {} for s in SYMBOLS}
_strict_lock = asyncio.Lock()

_CANDLES_PER_DAY_5M = 288   # 5m candles par jour


def _ema_recursive(arr: np.ndarray, span: int) -> np.ndarray:
    """EMA récursive calculée en C.

    Exactement la même récurrence que la boucle Python qu'elle remplace —
    y[0] = x[0], y[i] = α·x[i] + (1−α)·y[i−1] avec α = 2/(span+1) — mais sans
    repasser par l'interpréteur à chaque barre : `adjust=False` EST cette forme.
    La calibration STRICT balaye des centaines de combinaisons, la boucle Python
    y pesait à elle seule un tiers du CPU du worker.
    """
    if len(arr) == 0:
        return np.asarray(arr, dtype=float)
    alpha = 2.0 / (span + 1)
    serie = pd.Series(arr, copy=False).ewm(alpha=alpha, adjust=False).mean()
    return serie.to_numpy(dtype=float)


def _trix_series(close: np.ndarray, length: int) -> np.ndarray:
    """TRIX (triple EMA)."""
    ema1 = _ema_recursive(close, length)
    ema2 = _ema_recursive(ema1, length)
    ema3 = _ema_recursive(ema2, length)
    trix = np.zeros(len(ema3))
    trix[1:] = (ema3[1:] - ema3[:-1]) / np.where(ema3[:-1] != 0, ema3[:-1], 1e-9) * 100
    return trix


def _ema_series(close: np.ndarray, span: int) -> np.ndarray:
    """EMA simple — même récurrence, calculée en C."""
    return _ema_recursive(close, span)


def _sharpe_trix(df: pd.DataFrame, trix_len: int, signal_len: int, fee_bps: float) -> float:
    """Calcule le Sharpe annualisé d'une stratégie TRIX cross avec filtre EMA200.

    Fix : annualisation par trades/jour (correct pour returns per-trade).
    Fix : filtre EMA200 → entrées LONG uniquement au-dessus, SHORT en-dessous.
    """
    min_bars = trix_len * 3 + signal_len + 200 + 5
    if len(df) < min_bars:
        return -1e9
    try:
        close  = df["close"].values.astype(float)
        trix   = _trix_series(close, trix_len)
        signal_arr = pd.Series(trix).ewm(span=signal_len, adjust=False).mean().values

        # Filtre de tendance EMA200 — réduit les faux signaux en range
        ema200 = _ema_series(close, 200)

        fee     = fee_bps / 10000.0
        returns = []

        for i in range(200, len(trix) - 1):
            cross_up   = trix[i - 1] < signal_arr[i - 1] and trix[i] > signal_arr[i]
            cross_down = trix[i - 1] > signal_arr[i - 1] and trix[i] < signal_arr[i]

            next_close = close[min(i + 1, len(close) - 1)]

            # LONG uniquement quand prix > EMA200
            if cross_up and close[i] > ema200[i]:
                ret = (next_close - close[i]) / close[i] - fee
                returns.append(ret)
            # SHORT uniquement quand prix < EMA200
            elif cross_down and close[i] < ema200[i]:
                ret = (close[i] - next_close) / close[i] - fee
                returns.append(ret)

        if len(returns) < STRICT_MIN_TRADES:
            return -1e9

        arr  = np.array(returns)
        mean = float(np.mean(arr))
        std  = float(np.std(arr))
        if std < 1e-9:
            return -1e9

        # Annualisation correcte pour returns per-trade
        n_days        = max(len(df) / _CANDLES_PER_DAY_5M, 1.0)
        trades_per_day = len(returns) / n_days
        annual_factor  = math.sqrt(252.0 * max(trades_per_day, 0.05))

        return float(np.clip(mean / std * annual_factor, -20.0, 20.0))

    except Exception:
        return -1e9


def _sanity_check_params(trix_len: int, signal_len: int) -> bool:
    """Vérifie que les paramètres sont dans des plages raisonnables."""
    return (
        5 <= trix_len <= 20
        and 10 <= signal_len <= 40
        and signal_len > trix_len  # signal doit être plus lent que TRIX
    )


def optimize_trix_strict(df: pd.DataFrame) -> Dict[str, Any]:
    """Optimise TRIX par random search avec filtre EMA200."""
    best_sharpe = -1e9
    best_params = {"trix_length": 9, "trix_signal": 21}

    for _ in range(STRICT_RANDOM_ITERS):
        tl = random.randint(5, 20)
        sl = random.randint(tl + 2, 40)   # signal toujours > trix
        if not _sanity_check_params(tl, sl):
            continue
        sharpe = _sharpe_trix(df, tl, sl, STRICT_FEE_BPS)
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_params = {"trix_length": tl, "trix_signal": sl}

    if best_sharpe < STRICT_SHARPE_FLOOR:
        logger.info(
            "[STRICT] Sharpe %.2f < floor %.2f — paramètres défaut conservés",
            best_sharpe, STRICT_SHARPE_FLOOR,
        )
        return {"trix_length": 9, "trix_signal": 21, "sharpe": round(best_sharpe, 4), "valid": False}

    return {**best_params, "sharpe": round(best_sharpe, 4), "valid": True}


async def strict_recalib_loop(session: Any) -> None:
    """Recalibration STRICT TRIX toutes les N jours."""
    from data.binance_rest import fetch_klines_history
    await asyncio.sleep(60)
    while True:
        async with _strict_lock:
            logger.info("[STRICT] Démarrage recalibration TRIX")
            for sym in SYMBOLS:
                try:
                    df = await fetch_klines_history(session, sym, STRICT_TF, STRICT_IN_SAMPLE_DAYS)
                    if df is not None and len(df) >= 200:
                        params = optimize_trix_strict(df)
                        _strict_params[sym] = params
                        logger.info(
                            "[STRICT] %s → length=%d signal=%d sharpe=%.2f valid=%s",
                            sym, params["trix_length"], params["trix_signal"],
                            params["sharpe"], params["valid"],
                        )
                    else:
                        logger.warning("[STRICT] %s: données insuffisantes (%d barres)",
                                       sym, len(df) if df is not None else 0)
                except Exception as e:
                    logger.error("[STRICT] %s recalib error: %s", sym, e)
                await asyncio.sleep(5)

        await asyncio.sleep(STRICT_RECALIB_DAYS * 86400)


def get_strict_params(sym: str) -> Dict[str, Any]:
    return _strict_params.get(sym) or {"trix_length": 9, "trix_signal": 21}
