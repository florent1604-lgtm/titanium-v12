"""
new_reversal_patterns.py — SMC Audit Fix File #2
=================================================
P1 Missing Reversal Patterns for titanium_dashboard_v10.py:

  1. detect_inducement_sweep_choch    — Multi-TF 3-phase confluence pattern
  2. detect_rsi_divergence_at_ob      — RSI divergence coinciding with an OB level
  3. compute_reversal_confidence      — Composite reversal confidence score (0–100)

Python 3.9+, pandas/numpy only.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helper: RSI calculation (pure numpy — no pandas_ta dependency required)
# ---------------------------------------------------------------------------

def _compute_rsi(close_arr: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute RSI over a 1D numpy array of close prices.

    Uses the standard Wilder smoothing (EMA of gains/losses).

    Parameters
    ----------
    close_arr : np.ndarray  shape (N,)
    period    : int          RSI period, default 14

    Returns
    -------
    np.ndarray of same length, NaN for the first ``period`` values.
    """
    n   = len(close_arr)
    rsi = np.full(n, np.nan, dtype=float)

    if n < period + 1:
        return rsi

    deltas = np.diff(close_arr.astype(float))
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed the first average gain / loss with simple mean
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / (avg_loss + 1e-12)
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def _find_swing_lows(arr: np.ndarray, window: int = 3) -> List[int]:
    """Return indices of local minima with left/right window confirmation."""
    indices = []
    for i in range(window, len(arr) - window):
        if all(arr[i] <= arr[i - k] for k in range(1, window + 1)) and \
           all(arr[i] <= arr[i + k] for k in range(1, window + 1)):
            indices.append(i)
    return indices


def _find_swing_highs(arr: np.ndarray, window: int = 3) -> List[int]:
    """Return indices of local maxima with left/right window confirmation."""
    indices = []
    for i in range(window, len(arr) - window):
        if all(arr[i] >= arr[i - k] for k in range(1, window + 1)) and \
           all(arr[i] >= arr[i + k] for k in range(1, window + 1)):
            indices.append(i)
    return indices


# ---------------------------------------------------------------------------
# 1. Inducement → Sweep → CHoCH
# ---------------------------------------------------------------------------

def detect_inducement_sweep_choch(
    df_htf: pd.DataFrame,
    df_mtf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    side: str,
) -> Dict[str, Any]:
    """Detect the full SMC 3-phase reversal confluence: Inducement → Sweep → CHoCH.

    This is the highest-priority reversal pattern in SMC theory.  Each phase is
    assessed independently, allowing partial matches (2/3 phases = 0.65 confluence).

    Phase 1 — Inducement (HTF)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~
    An inducement Order Block (OB) is an OB that was briefly touched and then
    broken — it was a *trap* placed before the true reversal.  Detection:
      - Find an OB on HTF (last bearish candle before a bull run or vice versa)
      - Confirm that price subsequently broke through it (status = broken)

    Phase 2 — Sweep (MTF)
    ~~~~~~~~~~~~~~~~~~~~~
    A liquidity sweep on the mid-TF using ATR-based margin confirmation:
      - Wick penetration of a recent significant extreme
      - Close back above (ACHAT) or below (VENTE) with margin

    Phase 3 — CHoCH (LTF)
    ~~~~~~~~~~~~~~~~~~~~~~
    Change of Character on the lower TF = first structural break against the
    prevailing micro-trend:
      - For ACHAT: first higher close that breaks above a recent lower-high
      - For VENTE: first lower close that breaks below a recent higher-low

    Parameters
    ----------
    df_htf : pd.DataFrame   Higher timeframe (e.g. H4, H1)
    df_mtf : pd.DataFrame   Mid timeframe (e.g. 15m, 30m)
    df_ltf : pd.DataFrame   Lower timeframe (e.g. 1m, 3m, 5m)
    side   : str            "ACHAT" or "VENTE"

    Returns
    -------
    dict with keys:
        detected          : bool   — True if all 3 phases confirmed
        phase1_ok         : bool   — Inducement OB found on HTF
        phase2_ok         : bool   — Sweep confirmed on MTF
        phase3_ok         : bool   — CHoCH confirmed on LTF
        confluence_score  : float  — 0.0–1.0 (1/3=0.33, 2/3=0.65, 3/3=1.0)
        details           : dict   — Per-phase evidence
    """
    result: Dict[str, Any] = {
        "detected":         False,
        "phase1_ok":        False,
        "phase2_ok":        False,
        "phase3_ok":        False,
        "confluence_score": 0.0,
        "details":          {},
    }

    details: Dict[str, Any] = {}

    # ── Phase 1: Inducement OB on HTF ───────────────────────────────────────
    phase1_ok = False
    if df_htf is not None and len(df_htf) >= 20:
        try:
            tail_htf = df_htf.tail(50)
            for i in range(len(tail_htf) - 3, 2, -1):
                c = float(tail_htf["close"].iloc[i])
                o = float(tail_htf["open"].iloc[i])
                h = float(tail_htf["high"].iloc[i])
                lo = float(tail_htf["low"].iloc[i])

                is_inducement_candidate = False
                ob_top, ob_bot = 0.0, 0.0

                if "ACHAT" in side.upper() and c < o:  # bearish OB before bull reversal
                    ob_top, ob_bot = o, lo
                    is_inducement_candidate = True
                elif "VENTE" in side.upper() and c > o:  # bullish OB before bear reversal
                    ob_top, ob_bot = h, c
                    is_inducement_candidate = True

                if not is_inducement_candidate:
                    continue

                # Check if a subsequent candle broke through this OB
                subsequent = tail_htf.iloc[i + 1:]
                if "ACHAT" in side.upper():
                    # Bull reversal: a candle should have closed ABOVE ob_top (breaking the bearish OB)
                    broken = any(float(r) > ob_top for r in subsequent["close"])
                else:
                    broken = any(float(r) < ob_bot for r in subsequent["close"])

                if broken:
                    phase1_ok = True
                    details["phase1"] = {
                        "ob_top":  round(ob_top, 8),
                        "ob_bot":  round(ob_bot, 8),
                        "bar_idx": i,
                    }
                    break

        except Exception as exc:
            details["phase1_error"] = str(exc)

    # ── Phase 2: Sweep on MTF ────────────────────────────────────────────────
    phase2_ok = False
    if df_mtf is not None and len(df_mtf) >= 30:
        try:
            from fixes.smc_corrections import detect_liquidity_sweep_v2  # type: ignore
        except ImportError:
            # Inline fallback if import fails (self-contained)
            def detect_liquidity_sweep_v2(df, side, lookback=50, atr_margin_mult=0.002):  # type: ignore
                """Inline fallback sweep detection."""
                if df is None or len(df) < lookback + 5:
                    return {"detected": False}
                try:
                    recent_tail = df.tail(5)
                    historical  = df.iloc[-(lookback + 5):-5]
                    hist_h = historical["high"].values.astype(float)
                    hist_l = historical["low"].values.astype(float)
                    hist_c = historical["close"].values.astype(float)
                    tr_arr = np.maximum(
                        hist_h[1:] - hist_l[1:],
                        np.maximum(np.abs(hist_h[1:] - hist_c[:-1]),
                                   np.abs(hist_l[1:] - hist_c[:-1])),
                    )
                    atr14 = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else 1e-9
                    last_close = float(recent_tail["close"].iloc[-1])
                    margin = max(last_close * 0.001, atr14 * atr_margin_mult)
                    if "ACHAT" in side.upper():
                        lowest = float(historical["low"].min())
                        swept = (any(float(r) < lowest for r in recent_tail["low"])
                                 and float(recent_tail["close"].iloc[-1]) > lowest + margin)
                    else:
                        highest = float(historical["high"].max())
                        swept = (any(float(r) > highest for r in recent_tail["high"])
                                 and float(recent_tail["close"].iloc[-1]) < highest - margin)
                    return {"detected": bool(swept)}
                except Exception:
                    return {"detected": False}

        try:
            sweep_result = detect_liquidity_sweep_v2(df_mtf, side, lookback=30)
            phase2_ok    = bool(sweep_result.get("detected", False))
            details["phase2"] = sweep_result
        except Exception as exc:
            details["phase2_error"] = str(exc)

    # ── Phase 3: CHoCH on LTF ───────────────────────────────────────────────
    phase3_ok = False
    if df_ltf is not None and len(df_ltf) >= 20:
        try:
            tail_ltf = df_ltf.tail(40)
            closes   = tail_ltf["close"].values.astype(float)
            highs    = tail_ltf["high"].values.astype(float)
            lows     = tail_ltf["low"].values.astype(float)
            n_ltf    = len(closes)

            if "ACHAT" in side.upper():
                # CHoCH bull: price has been making lower highs, then breaks above latest lower-high
                swing_highs = _find_swing_highs(highs, window=2)
                if len(swing_highs) >= 2:
                    # Check if the last two swing highs form a lower-high pattern
                    sh1_val = highs[swing_highs[-2]]
                    sh2_val = highs[swing_highs[-1]]
                    is_lower_high = sh2_val < sh1_val
                    # CHoCH = latest close breaks above the most recent lower-high
                    last_close_val = closes[-1]
                    choch_break    = last_close_val > sh2_val
                    if is_lower_high and choch_break:
                        phase3_ok = True
                        details["phase3"] = {
                            "swing_high_1": round(sh1_val, 8),
                            "swing_high_2": round(sh2_val, 8),
                            "break_close":  round(last_close_val, 8),
                        }
            else:
                # CHoCH bear: price has been making higher lows, then breaks below latest higher-low
                swing_lows = _find_swing_lows(lows, window=2)
                if len(swing_lows) >= 2:
                    sl1_val = lows[swing_lows[-2]]
                    sl2_val = lows[swing_lows[-1]]
                    is_higher_low  = sl2_val > sl1_val
                    last_close_val = closes[-1]
                    choch_break    = last_close_val < sl2_val
                    if is_higher_low and choch_break:
                        phase3_ok = True
                        details["phase3"] = {
                            "swing_low_1": round(sl1_val, 8),
                            "swing_low_2": round(sl2_val, 8),
                            "break_close": round(last_close_val, 8),
                        }

        except Exception as exc:
            details["phase3_error"] = str(exc)

    # ── Confluence score ─────────────────────────────────────────────────────
    phases_ok   = sum([phase1_ok, phase2_ok, phase3_ok])
    score_map   = {0: 0.0, 1: 0.33, 2: 0.65, 3: 1.0}
    conf_score  = score_map[phases_ok]

    result["phase1_ok"]        = phase1_ok
    result["phase2_ok"]        = phase2_ok
    result["phase3_ok"]        = phase3_ok
    result["confluence_score"] = round(conf_score, 4)
    result["detected"]         = phases_ok == 3
    result["details"]          = details

    return result


# ---------------------------------------------------------------------------
# 2. RSI Divergence at Order Block
# ---------------------------------------------------------------------------

def detect_rsi_divergence_at_ob(
    df: pd.DataFrame,
    ob_top: float,
    ob_bot: float,
    side: str,
    lookback: int = 50,
    rsi_period: int = 14,
    proximity_pct: float = 0.005,
) -> Dict[str, Any]:
    """Detect RSI divergence coinciding with an Order Block zone.

    A divergence at an OB is a high-conviction signal because it combines:
      - Price at a significant institutional zone (OB)
      - Momentum exhaustion (RSI divergence)

    Detection logic
    ---------------
    Bullish divergence (ACHAT):
      - Find two price lows near the OB level (within ``proximity_pct``)
      - Price makes a lower low (LL) at the second touch
      - RSI makes a higher low (HL) at the second touch
      → Bullish hidden divergence = institutional accumulation at OB

    Bearish divergence (VENTE):
      - Find two price highs near the OB level
      - Price makes a higher high (HH) at second touch
      - RSI makes a lower high (LH) at second touch
      → Bearish divergence = institutional distribution at OB

    Parameters
    ----------
    df            : pd.DataFrame  OHLCV with at least ``lookback`` bars
    ob_top        : float         OB upper boundary
    ob_bot        : float         OB lower boundary
    side          : str           "ACHAT" or "VENTE"
    lookback      : int           Number of bars to scan
    rsi_period    : int           RSI period (default 14)
    proximity_pct : float         Maximum % distance from OB for a bar to "count"

    Returns
    -------
    dict with keys:
        divergence_detected : bool   — True if divergence confirmed
        divergence_type     : str    — "bullish" | "bearish" | "none"
        price_level_1       : float  — First extreme price
        price_level_2       : float  — Second extreme price (the divergence bar)
        rsi_at_level_1      : float  — RSI at first extreme
        rsi_at_level_2      : float  — RSI at second extreme
        bars_apart          : int    — Number of bars between the two extremes
        strength            : float  — 0.0–1.0 (magnitude of price/RSI divergence)
    """
    result: Dict[str, Any] = {
        "divergence_detected": False,
        "divergence_type":     "none",
        "price_level_1":       0.0,
        "price_level_2":       0.0,
        "rsi_at_level_1":      0.0,
        "rsi_at_level_2":      0.0,
        "bars_apart":          0,
        "strength":            0.0,
    }

    if df is None or len(df) < rsi_period + lookback:
        return result
    if ob_top <= ob_bot or ob_top == 0.0:
        return result

    try:
        scan_df = df.tail(lookback + rsi_period).copy()
        closes  = scan_df["close"].values.astype(float)
        lows    = scan_df["low"].values.astype(float)
        highs   = scan_df["high"].values.astype(float)

        # Compute RSI
        rsi_arr = _compute_rsi(closes, rsi_period)
        n       = len(closes)

        # Proximity filter: bar must be within proximity_pct of OB zone
        mid_price  = (ob_top + ob_bot) / 2.0
        prox_range = mid_price * proximity_pct

        # Keep last `lookback` bars only (RSI has NaN prefix from period)
        start_idx = max(rsi_period + 1, n - lookback)

        if "ACHAT" in side.upper():
            # Look for two lows near or inside the OB zone
            candidate_lows: List[Tuple[int, float, float]] = []  # (bar_idx, price_low, rsi_val)
            for i in range(start_idx, n):
                if np.isnan(rsi_arr[i]):
                    continue
                bar_low = lows[i]
                # Within proximity of OB
                if abs(bar_low - ob_bot) <= prox_range or (ob_bot <= bar_low <= ob_top):
                    # Must be a local low (lower than immediate neighbours)
                    if i > 0 and i < n - 1 and bar_low <= lows[i - 1] and bar_low <= lows[i + 1]:
                        candidate_lows.append((i, bar_low, float(rsi_arr[i])))

            if len(candidate_lows) >= 2:
                # Take the two most recent candidates
                c1 = candidate_lows[-2]
                c2 = candidate_lows[-1]
                price_ll = c2[1] < c1[1]   # price made lower low
                rsi_hl   = c2[2] > c1[2]   # RSI made higher low
                if price_ll and rsi_hl:
                    bars_apart = c2[0] - c1[0]
                    price_div  = abs(c1[1] - c2[1]) / (c1[1] + 1e-12)
                    rsi_div    = abs(c2[2] - c1[2]) / 100.0
                    strength   = round(min(1.0, (price_div * 10 + rsi_div) / 2.0), 4)
                    result.update({
                        "divergence_detected": True,
                        "divergence_type":     "bullish",
                        "price_level_1":       round(c1[1], 8),
                        "price_level_2":       round(c2[1], 8),
                        "rsi_at_level_1":      round(c1[2], 2),
                        "rsi_at_level_2":      round(c2[2], 2),
                        "bars_apart":          int(bars_apart),
                        "strength":            strength,
                    })

        else:  # VENTE
            candidate_highs: List[Tuple[int, float, float]] = []
            for i in range(start_idx, n):
                if np.isnan(rsi_arr[i]):
                    continue
                bar_high = highs[i]
                if abs(bar_high - ob_top) <= prox_range or (ob_bot <= bar_high <= ob_top):
                    if i > 0 and i < n - 1 and bar_high >= highs[i - 1] and bar_high >= highs[i + 1]:
                        candidate_highs.append((i, bar_high, float(rsi_arr[i])))

            if len(candidate_highs) >= 2:
                c1 = candidate_highs[-2]
                c2 = candidate_highs[-1]
                price_hh = c2[1] > c1[1]   # price made higher high
                rsi_lh   = c2[2] < c1[2]   # RSI made lower high
                if price_hh and rsi_lh:
                    bars_apart = c2[0] - c1[0]
                    price_div  = abs(c2[1] - c1[1]) / (c1[1] + 1e-12)
                    rsi_div    = abs(c1[2] - c2[2]) / 100.0
                    strength   = round(min(1.0, (price_div * 10 + rsi_div) / 2.0), 4)
                    result.update({
                        "divergence_detected": True,
                        "divergence_type":     "bearish",
                        "price_level_1":       round(c1[1], 8),
                        "price_level_2":       round(c2[1], 8),
                        "rsi_at_level_1":      round(c1[2], 2),
                        "rsi_at_level_2":      round(c2[2], 2),
                        "bars_apart":          int(bars_apart),
                        "strength":            strength,
                    })

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# 3. Reversal Confidence Score (composite)
# ---------------------------------------------------------------------------

def compute_reversal_confidence(
    pattern_results: Dict[str, Any],
    ob_status: str,
    fvg_status: str,
    delta_vol_state: Optional[Dict[str, Any]],
    rsi_val: float,
    adx_val: float,
    side: str,
) -> Tuple[float, Dict[str, float]]:
    """Compute a composite reversal confidence score from 0.0 to 100.0.

    Combines five sub-scores with fixed weights:
      - Pattern quality  (25%): quality of detected reversal pattern
      - Location quality (20%): is price at a high-conviction zone?
      - Confluence count (25%): how many confirming signals agree?
      - Volume score     (15%): delta volume alignment with reversal direction
      - Momentum score   (15%): RSI and ADX support for the reversal

    Parameters
    ----------
    pattern_results : dict
        Output from ``detect_inducement_sweep_choch()`` or similar pattern function.
        Expected keys: ``confluence_score`` (0–1), ``detected`` (bool).
    ob_status : str
        Status of the nearest OB: "intact" | "tested" | "broken" | "none"
    fvg_status : str
        Status of the nearest FVG: "active" | "filled" | "none"
    delta_vol_state : dict or None
        Delta volume output.  Expected keys:
          ``direction`` ("long"/"short"/"neutral"), ``strength`` (float 0–1).
    rsi_val : float
        Current RSI value (0–100).
    adx_val : float
        Current ADX value (0–100).
    side : str
        "ACHAT" or "VENTE"

    Returns
    -------
    Tuple[float, Dict[str, float]]
        (total_score_0_to_100, breakdown_dict)

    Breakdown keys:
        pattern_score, location_score, confluence_score, volume_score, momentum_score
    """
    breakdown: Dict[str, float] = {
        "pattern_score":    0.0,
        "location_score":   0.0,
        "confluence_score": 0.0,
        "volume_score":     0.0,
        "momentum_score":   0.0,
    }

    # ── 1. Pattern quality (0–100) ───────────────────────────────────────────
    # Based on confluence_score from pattern detector (0.0–1.0) × 100
    raw_conf  = float(pattern_results.get("confluence_score", 0.0))
    detected  = bool(pattern_results.get("detected", False))
    # Partial match bonus already baked into confluence_score
    pat_score = min(100.0, raw_conf * 100.0)
    # Full detection gives slight bonus over the 3/3 = 1.0 mapping
    if detected:
        pat_score = min(100.0, pat_score + 5.0)
    breakdown["pattern_score"] = round(pat_score, 2)

    # ── 2. Location quality (0–100) ──────────────────────────────────────────
    # Best = intact OB + active FVG (both at same zone = premium location)
    ob_points  = {"intact": 60.0, "tested": 40.0, "broken": 10.0, "none": 0.0}
    fvg_points = {"active": 40.0, "filled": 15.0, "none": 0.0}
    loc_score  = ob_points.get(ob_status.lower(), 0.0) + fvg_points.get(fvg_status.lower(), 0.0)
    loc_score  = min(100.0, loc_score)
    breakdown["location_score"] = round(loc_score, 2)

    # ── 3. Confluence count (0–100) ──────────────────────────────────────────
    # Count binary agreement signals:
    #   phase1_ok, phase2_ok, phase3_ok from pattern + ob_intact + fvg_active
    conf_signals = [
        bool(pattern_results.get("phase1_ok", False)),
        bool(pattern_results.get("phase2_ok", False)),
        bool(pattern_results.get("phase3_ok", False)),
        ob_status.lower() == "intact",
        fvg_status.lower() == "active",
    ]
    n_conf      = sum(conf_signals)
    conf_score  = min(100.0, n_conf / len(conf_signals) * 100.0)
    breakdown["confluence_score"] = round(conf_score, 2)

    # ── 4. Volume score (0–100) ──────────────────────────────────────────────
    vol_score = 0.0
    if delta_vol_state is not None:
        dv_dir      = str(delta_vol_state.get("direction", "neutral")).lower()
        dv_strength = float(delta_vol_state.get("strength", 0.0))
        is_long = "ACHAT" in side.upper()
        # Volume aligned with trade direction = bullish confirmation
        if (is_long and dv_dir == "long") or (not is_long and dv_dir == "short"):
            vol_score = min(100.0, dv_strength * 100.0)
        elif dv_dir == "neutral":
            vol_score = 25.0  # neutral = not confirmatory but not contradictory
        else:
            vol_score = 0.0   # opposing volume = penalise
    breakdown["volume_score"] = round(vol_score, 2)

    # ── 5. Momentum score (0–100) ────────────────────────────────────────────
    # RSI contribution: oversold for ACHAT, overbought for VENTE
    # ADX contribution: moderate ADX (15–35) is better for reversals than extreme values
    rsi_val = float(rsi_val)
    adx_val = float(adx_val)

    if "ACHAT" in side.upper():
        if rsi_val <= 30:
            rsi_score = 100.0
        elif rsi_val <= 40:
            rsi_score = 60.0
        elif rsi_val <= 50:
            rsi_score = 30.0
        else:
            rsi_score = max(0.0, 100.0 - rsi_val * 1.5)
    else:
        if rsi_val >= 70:
            rsi_score = 100.0
        elif rsi_val >= 60:
            rsi_score = 60.0
        elif rsi_val >= 50:
            rsi_score = 30.0
        else:
            rsi_score = max(0.0, (rsi_val - 50.0) * 2.0)

    # ADX: best for reversal when between 15 and 30 (market not overextended)
    if 15 <= adx_val <= 30:
        adx_score = 100.0
    elif adx_val < 15:
        adx_score = adx_val / 15.0 * 70.0  # weak trend = ok but less convincing
    else:
        adx_score = max(0.0, 100.0 - (adx_val - 30.0) * 2.5)  # strong trend = reversal harder

    mom_score = (rsi_score * 0.6 + adx_score * 0.4)
    breakdown["momentum_score"] = round(mom_score, 2)

    # ── Weighted total ───────────────────────────────────────────────────────
    weights = {
        "pattern_score":    0.25,
        "location_score":   0.20,
        "confluence_score": 0.25,
        "volume_score":     0.15,
        "momentum_score":   0.15,
    }

    total = sum(breakdown[k] * w for k, w in weights.items())
    total = round(min(100.0, max(0.0, total)), 2)

    return total, breakdown
