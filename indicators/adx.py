"""indicators/adx.py — ADX + détection de régime TREND/RANGE/VOLATILE."""
from __future__ import annotations
import pandas as pd
import pandas_ta as ta
from utils.config import ADX_TREND_THRESHOLD, ADX_VOLATILE_THRESHOLD
from utils.logger import get_logger

logger = get_logger(__name__)

REGIMES = ("TREND", "RANGE", "VOLATILE", "UNKNOWN")


def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Retourne la valeur ADX courante. NaN → -1."""
    if df is None or len(df) < period + 5:
        return -1.0
    try:
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=period)
        if adx_df is None or adx_df.empty:
            return -1.0
        col = next((c for c in adx_df.columns if "ADX" in c.upper()), None)
        if col is None:
            return -1.0
        val = float(adx_df[col].iloc[-1])
        return val if not pd.isna(val) else -1.0
    except Exception as e:
        logger.debug("[ADX] compute error: %s", e)
        return -1.0


def get_market_regime(df: pd.DataFrame, adx_threshold: float = None) -> str:
    """Détermine le régime de marché.

    Returns:
        'TREND'    — ADX > threshold (continuation FVG recommandée)
        'RANGE'    — ADX ≤ threshold (rebond OB recommandé)
        'VOLATILE' — ADX > volatile_threshold (forte tendance, filtrer)
        'UNKNOWN'  — données insuffisantes
    """
    threshold = adx_threshold or ADX_TREND_THRESHOLD
    val = compute_adx(df)
    if val < 0:
        return "UNKNOWN"
    if val > ADX_VOLATILE_THRESHOLD:
        return "VOLATILE"
    if val > threshold:
        return "TREND"
    return "RANGE"
