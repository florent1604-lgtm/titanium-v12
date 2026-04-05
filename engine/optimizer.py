"""engine/optimizer.py — Backtest SL/TP + walk-forward avec split train/test obligatoire.

Fixes appliqués :
  - Backtest bidirectionnel (LONG + SHORT) → élimine le biais directionnel
  - Minimum OPT_MIN_OOS_TRADES trades OOS pour valider une config
  - Fallback IS×0.5 quand OOS invalide (trop peu de trades)
  - Cap du Sharpe à ±10 pour éviter les valeurs aberrantes
  - Split 60j in-sample / 20j out-of-sample
  - Sharpe annualisé correctement par trades/jour
"""
from __future__ import annotations
import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from utils.config import (
    SYMBOLS, OPT_TF, OPT_IN_SAMPLE_DAYS, OPT_OOS_DAYS,
    OPT_REFRESH_HOURS, OPT_MIN_CANDLES, OPT_FEE_BPS,
    OPT_SCORE_CRITERIA, OPT_CONFIGURATIONS, OPT_CONFIGURATIONS_PAXG,
    OPT_MIN_OOS_TRADES,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_SHARPE_CAP = 10.0   # valeur max/min raisonnable pour le Sharpe

# État global (protégé par Lock)
_opt_lock    = asyncio.Lock()
_opt_results: Dict[str, Dict[str, Any]] = {}
_opt_last_ts: float = 0.0


def _backtest_config(
    df: pd.DataFrame,
    atr_mult: float,
    tp_ratios: tuple,
    fee_bps: float = 4.0,
) -> Dict[str, float]:
    """Backtest vectorisé bidirectionnel sur un DataFrame OHLCV.

    Signale LONG quand prix > EMA20 et haussier, SHORT quand prix < EMA20 et baissier.
    Returns: dict avec sharpe, expectancy, winrate, max_drawdown, trades
    """
    if df is None or len(df) < 30:
        return {"sharpe": -_SHARPE_CAP, "expectancy": 0.0, "winrate": 0.0, "max_drawdown": 0.0, "trades": 0}

    try:
        close = df["close"].values.astype(float)
        high  = df["high"].values.astype(float)
        low   = df["low"].values.astype(float)
        n     = len(close)
        fee   = fee_bps / 10000.0

        # ATR rolling 14
        tr  = np.maximum(high[1:] - low[1:],
              np.maximum(np.abs(high[1:] - close[:-1]),
                         np.abs(low[1:]  - close[:-1])))
        atr = np.concatenate([[tr[0]], np.convolve(tr, np.ones(14) / 14, mode="full")[:len(tr)]])

        returns  = []
        in_trade = False
        sl = tp1 = tp2 = tp3 = 0.0
        entry    = 0.0
        is_long  = True

        for i in range(20, n):
            if not in_trade:
                ema_fast = float(np.mean(close[i - 5:i]))
                ema_slow = float(np.mean(close[i - 20:i]))
                atr_v    = atr[i] * atr_mult

                if ema_fast > ema_slow and close[i] > close[i - 1]:
                    # LONG signal
                    entry    = close[i] * (1 + fee)
                    sl       = entry - atr_v
                    tp1      = entry + atr_v * tp_ratios[0]
                    tp2      = entry + atr_v * tp_ratios[1]
                    tp3      = entry + atr_v * tp_ratios[2]
                    in_trade = True
                    is_long  = True

                elif ema_fast < ema_slow and close[i] < close[i - 1]:
                    # SHORT signal
                    entry    = close[i] * (1 - fee)
                    sl       = entry + atr_v
                    tp1      = entry - atr_v * tp_ratios[0]
                    tp2      = entry - atr_v * tp_ratios[1]
                    tp3      = entry - atr_v * tp_ratios[2]
                    in_trade = True
                    is_long  = False

            else:
                if is_long:
                    if low[i] <= sl:
                        returns.append((sl - entry) / entry - fee)
                        in_trade = False
                    elif high[i] >= tp3:
                        returns.append((tp3 - entry) / entry - fee)
                        in_trade = False
                    elif high[i] >= tp2:
                        returns.append((tp2 - entry) / entry - fee)
                        in_trade = False
                    elif high[i] >= tp1:
                        returns.append((tp1 - entry) / entry - fee)
                        in_trade = False
                else:  # SHORT
                    if high[i] >= sl:
                        returns.append((entry - sl) / entry - fee)
                        in_trade = False
                    elif low[i] <= tp3:
                        returns.append((entry - tp3) / entry - fee)
                        in_trade = False
                    elif low[i] <= tp2:
                        returns.append((entry - tp2) / entry - fee)
                        in_trade = False
                    elif low[i] <= tp1:
                        returns.append((entry - tp1) / entry - fee)
                        in_trade = False

        if len(returns) < 2:
            return {"sharpe": -_SHARPE_CAP, "expectancy": 0.0, "winrate": 0.0, "max_drawdown": 0.0, "trades": len(returns)}

        ret_arr  = np.array(returns)
        mean_ret = float(np.mean(ret_arr))
        std_ret  = float(np.std(ret_arr))

        # Sharpe annualisé par trades/jour (correct pour trade-level returns)
        candles_per_day = 288  # 5m candles
        n_days          = max(len(df) / candles_per_day, 1.0)
        trades_per_day  = len(returns) / n_days
        annual_factor   = math.sqrt(252.0 * max(trades_per_day, 0.05))
        sharpe = float(np.clip(mean_ret / std_ret * annual_factor, -_SHARPE_CAP, _SHARPE_CAP)) if std_ret > 1e-10 else -_SHARPE_CAP

        wins       = sum(1 for r in returns if r > 0)
        winrate    = wins / len(returns)
        expectancy = mean_ret

        equity = np.cumprod(1 + ret_arr)
        peak   = np.maximum.accumulate(equity)
        dd     = (equity - peak) / peak
        max_dd = float(np.min(dd))

        return {
            "sharpe":       round(sharpe, 4),
            "expectancy":   round(expectancy, 6),
            "winrate":      round(winrate, 4),
            "max_drawdown": round(max_dd, 4),
            "trades":       len(returns),
        }
    except Exception as e:
        logger.warning("[OPT] backtest error: %s", e)
        return {"sharpe": -_SHARPE_CAP, "expectancy": 0.0, "winrate": 0.0, "max_drawdown": 0.0, "trades": 0}


def _opt_score(result: dict) -> float:
    """Score combiné pour sélectionner la meilleure config."""
    trades = result.get("trades", 0)
    if trades < 3:
        return -1e18
    sharpe = result.get("sharpe", -_SHARPE_CAP)
    expect = result.get("expectancy", 0.0)
    max_dd = result.get("max_drawdown", 0.0)
    if OPT_SCORE_CRITERIA == "sharpe":
        return sharpe
    if OPT_SCORE_CRITERIA == "expectancy":
        return expect
    # combined = 0.5×Sharpe + 0.3×Expectancy + 0.2×(1-|MaxDD|)
    return 0.5 * sharpe + 0.3 * expect + 0.2 * (1 - abs(max_dd))


def run_optimization(sym: str, df_full: pd.DataFrame) -> Dict[str, Any]:
    """Optimisation walk-forward sur un symbole.

    Split : 60j in-sample, 20j out-of-sample.
    Sélectionne la meilleure config sur IS, valide sur OOS.
    Si OOS insuffisant (< OPT_MIN_OOS_TRADES), reporte le score IS avec pénalité 50%.
    """
    if df_full is None or len(df_full) < OPT_MIN_CANDLES:
        return {"error": "données insuffisantes", "computed_at": datetime.now(timezone.utc).isoformat()}

    tf_minutes  = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
    min_per_c   = tf_minutes.get(OPT_TF, 5)
    is_candles  = int(OPT_IN_SAMPLE_DAYS  * 1440 / min_per_c)
    oos_candles = int(OPT_OOS_DAYS * 1440 / min_per_c)
    total_needed = is_candles + oos_candles

    if len(df_full) < total_needed:
        ratio       = len(df_full) / total_needed
        is_candles  = int(is_candles * ratio)
        oos_candles = len(df_full) - is_candles

    df_is  = df_full.iloc[:is_candles]
    df_oos = df_full.iloc[is_candles:is_candles + oos_candles]

    configs        = OPT_CONFIGURATIONS_PAXG if sym == "PAXG/USDT" else OPT_CONFIGURATIONS
    best_is_score  = -1e18
    best_config    = None
    best_is_result = {}
    all_results    = []

    for cfg in configs:
        atr_mult  = cfg["atr_mult"]
        tp_ratios = cfg["tp_ratios"]
        is_res    = _backtest_config(df_is, atr_mult, tp_ratios, OPT_FEE_BPS)
        sc        = _opt_score(is_res)
        all_results.append({"atr_mult": atr_mult, "tp_ratios": tp_ratios, "_is_score": sc, **is_res})
        if sc > best_is_score:
            best_is_score  = sc
            best_config    = cfg
            best_is_result = is_res

    if best_config is None:
        return {"error": "aucune config valide", "computed_at": datetime.now(timezone.utc).isoformat()}

    # Valider sur OOS
    oos_res = _backtest_config(df_oos, best_config["atr_mult"], best_config["tp_ratios"], OPT_FEE_BPS)

    # ── Sanity check OOS ──────────────────────────────────────────────────────
    oos_valid = oos_res["trades"] >= OPT_MIN_OOS_TRADES
    if not oos_valid:
        # Trop peu de trades OOS → reporter IS avec pénalité 50%
        logger.warning(
            "[OPT] %s OOS invalide (%d trades < %d min) — fallback IS×0.5",
            sym, oos_res["trades"], OPT_MIN_OOS_TRADES,
        )
        reported_sharpe = round(best_is_result.get("sharpe", -_SHARPE_CAP) * 0.5, 4)
        oos_res = {
            **best_is_result,
            "sharpe":  reported_sharpe,
            "trades":  oos_res["trades"],
            "_source": "is_fallback",
        }

    all_results.sort(key=lambda x: float(x.get("_is_score", -1e18)), reverse=True)

    result = {
        "atr_mult":     best_config["atr_mult"],
        "tp_ratios":    best_config["tp_ratios"],
        "is_sharpe":    round(best_is_score, 4),
        "sharpe":       oos_res["sharpe"],
        "expectancy":   oos_res["expectancy"],
        "winrate":      oos_res["winrate"],
        "max_drawdown": oos_res["max_drawdown"],
        "trades_oos":   oos_res["trades"],
        "oos_valid":    oos_valid,
        "overfitting_gap": round(
            abs(best_is_result.get("sharpe", 0) - oos_res["sharpe"]), 4
        ),
        "score_criteria": OPT_SCORE_CRITERIA,
        "computed_at":  datetime.now(timezone.utc).isoformat(),
        "all_results":  all_results[:6],
    }

    # Avertir si gap IS/OOS suspect (overfitting potentiel)
    if result["overfitting_gap"] > 2.0:
        logger.warning(
            "[OPT] %s gap IS/OOS élevé (%.2f) — possible overfitting",
            sym, result["overfitting_gap"],
        )

    return result


async def optimisation_loop(session: Any) -> None:
    """Boucle d'optimisation périodique (24h par défaut)."""
    global _opt_results, _opt_last_ts
    from data.binance_rest import fetch_klines_history

    await asyncio.sleep(30)
    while True:
        async with _opt_lock:
            logger.info("[OPT] Démarrage optimisation SL/TP — %s actifs", len(SYMBOLS))
            for sym in SYMBOLS:
                try:
                    df = await fetch_klines_history(session, sym, OPT_TF, OPT_IN_SAMPLE_DAYS + OPT_OOS_DAYS)
                    if df is not None and not df.empty:
                        result = run_optimization(sym, df)
                        _opt_results[sym] = result
                        logger.info(
                            "[OPT] %s → sharpe_oos=%.2f winrate=%.0f%% atr=%.1f oos_valid=%s gap=%.2f",
                            sym,
                            result.get("sharpe", 0),
                            result.get("winrate", 0) * 100,
                            result.get("atr_mult", 0),
                            result.get("oos_valid", "?"),
                            result.get("overfitting_gap", 0),
                        )
                    else:
                        logger.warning("[OPT] %s: données insuffisantes", sym)
                except Exception as e:
                    logger.error("[OPT] %s erreur: %s", sym, e)
                await asyncio.sleep(2)
            _opt_last_ts = datetime.now(timezone.utc).timestamp()

        await asyncio.sleep(OPT_REFRESH_HOURS * 3600)


def get_opt_results() -> Dict[str, Any]:
    return dict(_opt_results)
