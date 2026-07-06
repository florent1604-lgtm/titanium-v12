"""
config_adaptive_patch.py — SMC Audit Fix File #3
=================================================
Critical config fixes and helpers for titanium_dashboard_v10.py.

Sections:
  A. SYM_OVERRIDES extension  — BTC, ETH, SOL per-symbol parameter defaults
  B. TELEGRAM_SCORE_THRESHOLD — v8 scale fix (/9 → /11) + label dict update
  C. MIN_DF30_FOR_SCAN fix    — 3 → 10 (warmup too short caused false signals)
  D. STRICT_SHARPE_FLOOR fix  — 0.30 → 0.50 (stricter regime filter)
  E. get_delta_vol_freshness_limit  — tiered delta-volume freshness gate
  F. get_regime_rsi_thresholds      — regime-aware RSI bound adjustment

Usage (integration)
-------------------
Copy the constant blocks into the corresponding section at the top of
titanium_dashboard_v10.py, and import/call the helper functions where indicated.
See fixes/integration_guide.md for exact insertion points.

Python 3.9+, stdlib only.
"""

from typing import Any, Dict, Tuple


# ===========================================================================
# A. SYM_OVERRIDES — per-symbol parameter defaults (extends existing PAXG block)
# ===========================================================================
# Paste this entire dict as the new SYM_OVERRIDES in titanium_dashboard_v10.py
# (replacing the existing one at ~line 258).
#
# Design rationale per asset:
#   BTC/USDT : High absolute ATR, wider SL needed; tight RSI on 5m (28/72)
#              TP ratios reflect BTC's tendency to extend moves (1.5-2.5×ATR)
#   ETH/USDT : Similar to BTC but more volatile intraday; slightly tighter RSI
#              TP ratios slightly shorter than BTC
#   SOL/USDT : Highly volatile alt; wide ATR mult; RSI extremes reached more often
#              TP ratios aggressive to catch sharp moves
#   PAXG/USDT: Low relative volatility; mean-reverting; keep existing calibration

import os

SYM_OVERRIDES_PATCH: Dict[str, Dict[str, Any]] = {
    # ── BTC/USDT ─────────────────────────────────────────────────────────────
    # Backtest guidance: ATR 5m ≈ $150–400 | best config ATR×1.0 TP(1.5,2.1,2.6)
    # RSI 28/72 (tighter than default 30/70 → cuts false oversold/overbought on BTC)
    # score_min = 6/11 (BTC SMC is reliable; allow slightly lower threshold)
    "BTC/USDT": {
        "atr_mult":    float(os.getenv("BTC_ATR_MULT",   "1.0")),
        "tp_ratios":   tuple(float(x) for x in os.getenv("BTC_TP_RATIOS", "1.5,2.1,2.6").split(",")),
        "rsi_long":    float(os.getenv("BTC_RSI_LONG",   "28")),
        "rsi_short":   float(os.getenv("BTC_RSI_SHORT",  "72")),
        "score_min":   int(os.getenv("BTC_SCORE_MIN",    "6")),
        "adx_threshold": float(os.getenv("BTC_ADX_THRESHOLD", "27.0")),
        "sl_floor_pct":  float(os.getenv("BTC_SL_FLOOR_PCT", "0.0010")),  # $100 floor on $100k BTC
    },

    # ── ETH/USDT ─────────────────────────────────────────────────────────────
    # Backtest guidance: ATR 5m ≈ $8–25 | best config ATR×1.0 TP(1.2,1.8,2.4)
    # RSI 27/73 (ETH more prone to fake oversold → slightly tighter than BTC)
    # score_min = 6/11
    "ETH/USDT": {
        "atr_mult":    float(os.getenv("ETH_ATR_MULT",   "1.0")),
        "tp_ratios":   tuple(float(x) for x in os.getenv("ETH_TP_RATIOS", "1.2,1.8,2.4").split(",")),
        "rsi_long":    float(os.getenv("ETH_RSI_LONG",   "27")),
        "rsi_short":   float(os.getenv("ETH_RSI_SHORT",  "73")),
        "score_min":   int(os.getenv("ETH_SCORE_MIN",    "6")),
        "adx_threshold": float(os.getenv("ETH_ADX_THRESHOLD", "27.0")),
        "sl_floor_pct":  float(os.getenv("ETH_SL_FLOOR_PCT", "0.0012")),
    },

    # ── SOL/USDT ─────────────────────────────────────────────────────────────
    # Backtest guidance: ATR 5m ≈ $0.5–2.5 | high intraday volatility
    # Wider ATR mult (1.2) to avoid SL whipsaws; RSI extremes 25/75 (SOL overshoots)
    # score_min = 7/11 (higher threshold due to more noise in SOL SMC)
    "SOL/USDT": {
        "atr_mult":    float(os.getenv("SOL_ATR_MULT",   "1.2")),
        "tp_ratios":   tuple(float(x) for x in os.getenv("SOL_TP_RATIOS", "1.2,1.8,2.4").split(",")),
        "rsi_long":    float(os.getenv("SOL_RSI_LONG",   "25")),
        "rsi_short":   float(os.getenv("SOL_RSI_SHORT",  "75")),
        "score_min":   int(os.getenv("SOL_SCORE_MIN",    "7")),
        "adx_threshold": float(os.getenv("SOL_ADX_THRESHOLD", "25.0")),
        "sl_floor_pct":  float(os.getenv("SOL_SL_FLOOR_PCT", "0.0015")),
    },

    # ── PAXG/USDT (Gold proxy) — UNCHANGED from existing calibration ──────
    "PAXG/USDT": {
        "atr_mult":    float(os.getenv("PAXG_ATR_MULT",  "1.2")),
        "tp_ratios":   tuple(float(x) for x in os.getenv("PAXG_TP_RATIOS", "1.0,1.5,2.0").split(",")),
        "rsi_long":    float(os.getenv("PAXG_RSI_LONG",  "35")),
        "rsi_short":   float(os.getenv("PAXG_RSI_SHORT", "65")),
        "score_min":   int(os.getenv("PAXG_SCORE_MIN",   "5")),
        "adx_threshold": float(os.getenv("PAXG_ADX_THRESHOLD", "25.0")),
        "sl_floor_pct":  float(os.getenv("PAXG_SL_FLOOR_PCT", "0.0025")),
    },
}


# ===========================================================================
# B. TELEGRAM_SCORE_THRESHOLD — v8 scale fix
# ===========================================================================
# PROBLEM: v8 extended scoring to /11 (added LIQ_SWEEP + ADX_REGIME to the
# original /9 scale).  The threshold was never updated — "6" on a /11 scale
# = only 54.5% of max score, which is far too low and causes alert spam.
#
# FIX: Raise threshold to 7/11 (consistent with SCORE_MIN_REQUIRED = 7).
#
# NOTE: Update the existing line in titanium_dashboard_v10.py (~line 341):
#   TELEGRAM_SCORE_THRESHOLD = float(os.getenv("TELEGRAM_SCORE_THRESHOLD", "6"))
# → Replace "6" default with "7"

# Correct value for v8 /11 scale (was /9 in v7, threshold was "6")
# 7/11 = 63.6% — stricter but avoids spam on weak setups
TELEGRAM_SCORE_THRESHOLD_PATCH: float = float(os.getenv("TELEGRAM_SCORE_THRESHOLD", "7"))

# Full label dict for 0–11 scale (v8)
# Previous dict only covered 4–9 (v7 /9 scale)
TELEGRAM_SCORE_LABELS_PATCH: Dict[int, str] = {
    0:  "⚫ Pas de signal",
    1:  "⚫ Pas de signal",
    2:  "⚫ Pas de signal",
    3:  "🔵 Signal faible",
    4:  "📡 Surveillance",
    5:  "📡 Surveillance",
    6:  "✅ Bon setup",
    7:  "🔥 Setup fort",      # v8 threshold minimum
    8:  "🚀 Setup optimal",
    9:  "💎 Signal premium",
    10: "🌟 Setup parfait",
    11: "👑 Signal absolu",
}


# ===========================================================================
# C. MIN_DF30_FOR_SCAN fix — 3 → 10
# ===========================================================================
# PROBLEM: MIN_DF30_FOR_SCAN = 3 allows the scan to run with only 3 × 30s =
# 90 seconds of data.  OB/FVG/EMA lookbacks require 20–60 bars minimum, so
# running with 3 bars produces garbage signals and wastes CPU.
#
# FIX: Raise to 10 (5 minutes of 30s data = enough for basic indicator warmup).
# This matches the effective minimum required for the 5-bar tail used in
# detect_liquidity_sweep and for a usable ATR14 estimate.
#
# Replace the existing line (~line 214):
#   MIN_DF30_FOR_SCAN = int(os.getenv("MIN_DF30_FOR_SCAN", "3"))
# with:
#   MIN_DF30_FOR_SCAN = int(os.getenv("MIN_DF30_FOR_SCAN", "10"))

MIN_DF30_FOR_SCAN_PATCH: int = int(os.getenv("MIN_DF30_FOR_SCAN", "10"))


# ===========================================================================
# D. STRICT_SHARPE_FLOOR fix — 0.30 → 0.50
# ===========================================================================
# PROBLEM: 0.30 is close to a random strategy's Sharpe in many short windows.
# At STRICT_SUBPERIOD_DAYS = 30, a floor of 0.30 allows strategies with
# borderline performance to pass the robust check, producing over-optimistic
# calibrations.
#
# FIX: Raise to 0.50.  This is the commonly accepted "mediocre but acceptable"
# threshold in quantitative finance (Sharpe > 0.5 over 30-day sub-periods).
# The stricter floor means fewer configurations survive STRICT mode, but those
# that do are genuinely robust.
#
# Replace the existing line (~line 428):
#   STRICT_SHARPE_FLOOR = float(os.getenv("STRICT_SHARPE_FLOOR", "0.30"))
# with:
#   STRICT_SHARPE_FLOOR = float(os.getenv("STRICT_SHARPE_FLOOR", "0.50"))

STRICT_SHARPE_FLOOR_PATCH: float = float(os.getenv("STRICT_SHARPE_FLOOR", "0.50"))


# ===========================================================================
# E. Delta volume freshness tiered gate
# ===========================================================================

def get_delta_vol_freshness_limit(active_tf: str) -> int:
    """Return the maximum acceptable age (in seconds) of delta volume data
    before it is considered stale for the given active timeframe.

    Rationale
    ---------
    Delta volume from aggTrade WebSocket is real-time, but network latency or
    reconnect gaps can leave stale data in the buffer.  On short timeframes
    (1m/3m/5m), a 30-second-old delta vol reading can span an entire candle —
    unacceptable.  On longer TFs (1h+) a 2-minute-old reading is still valid.

    Parameters
    ----------
    active_tf : str
        Active timeframe string.  Recognised values:
        "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"

    Returns
    -------
    int — maximum freshness limit in seconds
    """
    tf = active_tf.strip().lower()

    # Short TFs: delta vol must be very fresh (≤ 30s)
    if tf in ("1m", "3m", "5m"):
        return 30

    # Mid TFs: tolerate up to 60s (one full 1m candle lag)
    if tf in ("15m", "30m"):
        return 60

    # Long TFs: 2 minutes acceptable
    # Covers 1h, 2h, 4h, 6h, 8h, 12h, 1d and any unrecognised TF
    return 120


# ===========================================================================
# F. Regime-aware RSI bounds
# ===========================================================================

def get_regime_rsi_thresholds(
    regime: str,
    base_long: float,
    base_short: float,
) -> Tuple[float, float]:
    """Adjust RSI entry thresholds based on the current market regime.

    In a TREND regime, RSI extremes are "allowed" to persist longer, so we
    tighten the thresholds to avoid counter-trend entries.
    In a RANGE regime, RSI extremes are more reliable reversal signals, so we
    loosen the thresholds slightly to catch more mean-reversion setups.

    Parameters
    ----------
    regime      : str    "TREND" | "RANGE" | "UNKNOWN"
    base_long   : float  Base oversold threshold for long entries (e.g. 28.0)
    base_short  : float  Base overbought threshold for short entries (e.g. 72.0)

    Returns
    -------
    Tuple[float, float] : (adjusted_rsi_long, adjusted_rsi_short)

    Examples
    --------
    >>> get_regime_rsi_thresholds("TREND", 28.0, 72.0)
    (23.0, 77.0)   # tighter — need deeper oversold/overbought in trending market

    >>> get_regime_rsi_thresholds("RANGE", 28.0, 72.0)
    (31.0, 69.0)   # looser — RSI extremes are more reliable in ranging market

    >>> get_regime_rsi_thresholds("UNKNOWN", 28.0, 72.0)
    (28.0, 72.0)   # no adjustment when regime unknown
    """
    regime_upper = regime.strip().upper()

    if regime_upper == "TREND":
        # Tighter: only enter on strong extremes (avoid counter-trend traps)
        adj_long  = base_long  - 5.0   # e.g. 28 → 23
        adj_short = base_short + 5.0   # e.g. 72 → 77

    elif regime_upper == "RANGE":
        # Looser: mean-reversion setups more reliable in range
        adj_long  = base_long  + 3.0   # e.g. 28 → 31
        adj_short = base_short - 3.0   # e.g. 72 → 69

    else:
        # UNKNOWN or any unrecognised value: no adjustment
        adj_long  = base_long
        adj_short = base_short

    # Hard clamps to prevent nonsensical values
    adj_long  = max(10.0, min(45.0, adj_long))
    adj_short = max(55.0, min(90.0, adj_short))

    return float(adj_long), float(adj_short)
