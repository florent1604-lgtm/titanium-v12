"""core/smc_engine.py — Smart Money Concepts : OB, FVG, BOS, Sweep, Breaker."""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import pandas_ta as ta
from utils.config import (
    OB_FVG_ATR_MULT, OB_FVG_PCT_FALLBACK, OB_FVG_FIB_DYNAMIC,
    FIB_LEVEL_LOW, FIB_LEVEL_HIGH, FIB_SWING_LOOKBACK, LIQUIDITY_LOOKBACK,
    ADX_TREND_THRESHOLD,
)
from utils.logger import get_logger

logger = get_logger(__name__)


# ── ATR ──────────────────────────────────────────────────────────────────────

def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calcule l'ATR courant. Retourne 0.0 si données insuffisantes."""
    if df is None or len(df) < period + 1:
        return 0.0
    try:
        atr_s = ta.atr(df["high"], df["low"], df["close"], length=period)
        if atr_s is None or atr_s.empty:
            return 0.0
        val = float(atr_s.iloc[-1])
        return val if not pd.isna(val) else 0.0
    except Exception:
        return 0.0


# ── Fibonacci Tolerance ───────────────────────────────────────────────────────

def compute_fib_tolerance(df: pd.DataFrame, price: float, atr_val: float) -> float:
    """Tolérance OB/FVG dynamique basée sur zone Fibonacci [0.618–0.786]."""
    fallback = max(abs(price) * OB_FVG_PCT_FALLBACK, atr_val * OB_FVG_ATR_MULT)
    if not OB_FVG_FIB_DYNAMIC or len(df) < 10:
        return fallback
    try:
        tail = df.tail(FIB_SWING_LOOKBACK)
        sh   = float(tail["high"].max())
        sl   = float(tail["low"].min())
        rng  = sh - sl
        if rng < 1e-9:
            return fallback
        fib618 = sl + FIB_LEVEL_LOW  * rng
        fib786 = sl + FIB_LEVEL_HIGH * rng
        tol = abs(fib786 - fib618) * 0.5
        return max(fallback, min(tol, rng * 0.15))
    except Exception:
        return fallback


# ── OB Status ────────────────────────────────────────────────────────────────

def ob_status(df_after: pd.DataFrame, ob_top: float, ob_bot: float, side: str) -> str:
    """Analyse le statut d'un OB : 'intact' | 'tested' | 'broken'."""
    if df_after is None or df_after.empty:
        return "intact"
    tested = False
    for i in range(len(df_after)):
        c  = float(df_after.iloc[i]["close"])
        lo = float(df_after.iloc[i]["low"])
        hi = float(df_after.iloc[i]["high"])
        if "ACHAT" in side:
            if c < ob_bot:
                return "broken"
            if lo <= ob_top and hi >= ob_bot:
                tested = True
        else:
            if c > ob_top:
                return "broken"
            if hi >= ob_bot and lo <= ob_top:
                tested = True
    return "tested" if tested else "intact"


# ── FVG Detection ─────────────────────────────────────────────────────────────

def detect_fvg(df: pd.DataFrame, side: str) -> List[Tuple[float, float]]:
    """Détecte toutes les Fair Value Gaps dans la direction donnée."""
    zones = []
    for i in range(2, len(df)):
        h0 = float(df.iloc[i - 2]["high"])
        l0 = float(df.iloc[i - 2]["low"])
        l2 = float(df.iloc[i]["low"])
        h2 = float(df.iloc[i]["high"])
        if "ACHAT" in side and h0 < l2:
            zones.append((h0, l2))
        elif "VENTE" in side and l0 > h2:
            zones.append((h2, l0))
    return zones


def detect_fvg_unfilled(df: pd.DataFrame, side: str,
                        lookback: int = 100) -> List[Tuple[float, float]]:
    """FVG encore OUVERTES (non comblées) dans la fenêtre récente.

    `detect_fvg` renvoie TOUTES les FVG de l'historique — sur du M15, des dizaines
    par côté, la plupart déjà rebouchées. Une FVG rebouchée n'est plus un signal :
    le prix est repassé au travers. Une zone n'est retenue que si sa borne de
    déséquilibre n'a JAMAIS été franchie par une barre postérieure à sa création :
      · FVG haussière (support) : aucune clôture/mèche basse sous sa borne basse ;
      · FVG baissière (résistance) : aucune mèche haute au-dessus de sa borne haute.
    C'est le « FVG actif/non comblé » demandé par Codex (22/07/2026).
    """
    n = len(df)
    if n < 3:
        return []
    debut = max(2, n - lookback)
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    ouvertes: List[Tuple[float, float]] = []
    for i in range(debut, n):
        h0, l0 = highs[i - 2], lows[i - 2]
        l2, h2 = lows[i], highs[i]
        if "ACHAT" in side and h0 < l2:
            # comblée si une barre postérieure redescend sous la borne basse (h0)
            if i + 1 >= n or lows[i + 1:].min() > h0:
                ouvertes.append((h0, l2))
        elif "VENTE" in side and l0 > h2:
            # comblée si une barre postérieure remonte au-dessus de la borne haute (l0)
            if i + 1 >= n or highs[i + 1:].max() < l0:
                ouvertes.append((h2, l0))
    return ouvertes


# ── OB/FVG Alignment ─────────────────────────────────────────────────────────

def has_ob_or_fvg_alignment(
    df: pd.DataFrame, side: str, price: float, lookback: int = 50
) -> Tuple[bool, str, float]:
    """Vérifie si le prix est dans/proche d'un OB ou FVG actif.

    Returns: (aligned, status, quality 0-1)
    """
    if df is None or len(df) < 5 or price <= 0:
        return False, "none", 0.0

    tail    = df.tail(lookback).copy()
    atr_val = compute_atr(tail)
    if atr_val == 0:
        atr_val = abs(price) * OB_FVG_PCT_FALLBACK
    tol     = compute_fib_tolerance(tail, price, atr_val)
    fvg_zones = detect_fvg(tail, side)

    # Check FVG
    for fvg_bot, fvg_top in fvg_zones:
        mid = (fvg_bot + fvg_top) / 2.0
        if abs(price - mid) <= tol:
            return True, "fvg", 0.85

    # Check OB
    for i in range(len(tail) - 2, 0, -1):
        c   = float(tail.iloc[i]["close"])
        o   = float(tail.iloc[i]["open"])
        h   = float(tail.iloc[i]["high"])
        lo  = float(tail.iloc[i]["low"])
        if "ACHAT" in side and c < o:
            ob_top, ob_bot = o, lo
        elif "VENTE" in side and c > o:
            ob_top, ob_bot = h, c
        else:
            continue

        if not ((ob_bot - tol) <= price <= (ob_top + tol)):
            continue

        df_after = tail.iloc[i + 1:].copy()
        status   = ob_status(df_after, ob_top, ob_bot, side)
        if status == "broken":
            continue

        quality = 1.0 if status == "intact" else 0.65
        fvg_in_ob = any(ob_bot <= b and t <= ob_top for b, t in fvg_zones)
        if fvg_in_ob:
            quality = min(1.0, quality * 1.2)
        return True, status, round(quality, 3)

    return False, "none", 0.0


# ── Liquidity Sweep ───────────────────────────────────────────────────────────

# Repli du sweep exprimé en fraction d'ATR quand un ATR est fourni. Remplace le
# tampon fixe 0,3 % qui n'a aucun sens transversal : 0,3 % vaut ~9 ATR sur un
# indice calme et une fraction d'ATR sur une crypto volatile (revue Codex 22/07).
LIQUIDITY_SWEEP_ATR_MULT = 0.25


def detect_liquidity_sweep(df: pd.DataFrame, side: str,
                           atr: Optional[float] = None,
                           atr_mult: float = LIQUIDITY_SWEEP_ATR_MULT) -> bool:
    """Détecte un Stop Hunt institutionnel (sweep de liquidité).

    La mèche perce un extrême historique PUIS la clôture revient au-delà d'un
    tampon de reconquête.

    `atr` : si fourni (> 0), le tampon devient `atr_mult × ATR` — normalisé par
    la volatilité de l'instrument. Sans `atr`, on garde le tampon historique fixe
    de 0,3 % (rétrocompatibilité STRICTE : le scorer /16 live ne change pas).
    """
    if df is None or len(df) < LIQUIDITY_LOOKBACK + 5:
        return False
    try:
        tail       = df.tail(5)
        historical = df.iloc[-(LIQUIDITY_LOOKBACK + 5):-5]
        use_atr = atr is not None and float(atr) > 0
        buf = float(atr) * atr_mult if use_atr else None
        if "ACHAT" in side:
            lowest_low  = float(historical["low"].min())
            confirm_lvl = (lowest_low + buf) if use_atr else lowest_low * 1.003
            return (
                any(float(r) < lowest_low for r in tail["low"])
                and float(tail["close"].iloc[-1]) > confirm_lvl
            )
        else:
            highest_high = float(historical["high"].max())
            confirm_lvl  = (highest_high - buf) if use_atr else highest_high * 0.997
            return (
                any(float(r) > highest_high for r in tail["high"])
                and float(tail["close"].iloc[-1]) < confirm_lvl
            )
    except Exception as e:
        logger.debug("[SMC] detect_liquidity_sweep: %s", e)
        return False


def detect_sweep_with_displacement(df: pd.DataFrame, side: str) -> bool:
    """Sweep + displacement : sweep suivi d'une bougie d'impulsion."""
    if not detect_liquidity_sweep(df, side):
        return False
    try:
        tail = df.tail(3)
        atr  = compute_atr(df)
        if atr == 0:
            return False
        last_body = abs(float(tail.iloc[-1]["close"]) - float(tail.iloc[-1]["open"]))
        return last_body > atr * 0.5
    except Exception:
        return False


# ── Break of Structure ─────────────────────────────────────────────────────────

def detect_bos(df: pd.DataFrame, side: str, lookback: int = 20) -> bool:
    """Détecte un Break of Structure (BOS) dans la direction donnée."""
    if df is None or len(df) < lookback + 3:
        return False
    try:
        tail = df.tail(lookback)
        if "ACHAT" in side:
            prev_high = float(tail.iloc[:-3]["high"].max())
            last_close = float(tail.iloc[-1]["close"])
            return last_close > prev_high
        else:
            prev_low   = float(tail.iloc[:-3]["low"].min())
            last_close = float(tail.iloc[-1]["close"])
            return last_close < prev_low
    except Exception:
        return False


# ── EMA200 ────────────────────────────────────────────────────────────────────

def compute_ema200(series: pd.Series) -> float:
    """EMA 200 sur la série de clôtures."""
    if series is None or len(series) < 200:
        return float("nan")
    try:
        ema = series.ewm(span=200, adjust=False).mean()
        return float(ema.iloc[-1])
    except Exception:
        return float("nan")


# ── Rejection Candle ──────────────────────────────────────────────────────────

def detect_rejection_candle(df: pd.DataFrame, side: str) -> bool:
    """Détecte une bougie de rejet (wick long, petit body) sur la dernière bougie."""
    if df is None or len(df) < 3:
        return False
    try:
        c  = df.iloc[-1]
        o, h, lo, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        body = abs(cl - o)
        rng  = h - lo
        if rng < 1e-9:
            return False
        if "ACHAT" in side:
            lower_wick = min(o, cl) - lo
            return lower_wick > rng * 0.5 and body < rng * 0.35
        else:
            upper_wick = h - max(o, cl)
            return upper_wick > rng * 0.5 and body < rng * 0.35
    except Exception:
        return False


# ── Volume Spike ──────────────────────────────────────────────────────────────

def detect_volume_spike(df: pd.DataFrame, lookback: int = 20, multiplier: float = 1.5) -> bool:
    """Détecte un pic de volume sur la dernière bougie."""
    if df is None or len(df) < lookback + 1:
        return False
    try:
        vol_avg = float(df.tail(lookback + 1).iloc[:-1]["v"].mean())
        vol_cur = float(df.iloc[-1]["v"])
        return vol_avg > 0 and vol_cur > vol_avg * multiplier
    except Exception:
        return False
