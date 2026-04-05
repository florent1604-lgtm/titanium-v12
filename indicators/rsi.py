"""indicators/rsi.py — RSI vectorisé numpy + divergence."""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Tuple
from utils.logger import get_logger

logger = get_logger(__name__)


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs   = avg_gain / avg_loss.replace(0, np.nan)
    rsi  = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def rsi_signal(df: pd.DataFrame, rsi_long: float, rsi_short: float, period: int = 14) -> Tuple[bool, bool, float]:
    if df is None or len(df) < period + 2:
        return False, False, 50.0
    rsi = compute_rsi(df["close"], period)
    val = float(rsi.iloc[-1])
    if pd.isna(val):
        return False, False, 50.0
    return val <= rsi_long, val >= rsi_short, round(val, 2)


def rsi_divergence(df: pd.DataFrame, lookback: int = 20, period: int = 14) -> str:
    if df is None or len(df) < lookback + period:
        return "none"
    try:
        tail   = df.tail(lookback + period)
        rsi    = compute_rsi(tail["close"], period).tail(lookback)
        prices = tail["close"].tail(lookback)
        if prices.iloc[-1] < prices.iloc[0] and rsi.iloc[-1] > rsi.iloc[0]:
            return "bullish"
        if prices.iloc[-1] > prices.iloc[0] and rsi.iloc[-1] < rsi.iloc[0]:
            return "bearish"
    except Exception as e:
        logger.debug("[RSI] divergence error: %s", e)
    return "none"
