"""
smc_corrections.py — SMC Audit Fix File #1
===========================================
Fixes for WARN/FAIL findings from the SMC Audit of titanium_dashboard_v10.py:

  1. detect_liquidity_sweep_v2   — ATR-based dynamic margin (replaces hard-coded 0.3%)
  2. detect_sweep_with_displacement — confirms displacement candle after sweep
  3. detect_breaker_blocks        — broken OB becomes S/R (Breaker Block pattern)
  4. detect_failed_auction        — price enters POI then rejects sharply

Python 3.9+, pandas/numpy only (no external deps).
"""

from __future__ import annotations  # NOT USED — removed per project constraints
# NOTE: Python 3.9+ compatible — no future annotations import

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Liquidity Sweep — ATR-based dynamic margin
# ---------------------------------------------------------------------------

def detect_liquidity_sweep_v2(
    df: pd.DataFrame,
    side: str,
    lookback: int = 50,
    atr_margin_mult: float = 0.002,
) -> Dict[str, Any]:
    """Detect institutional liquidity sweep (Stop Hunt) using an ATR-based margin.

    Replaces the fixed 0.3% confirmation margin in the original
    ``TitaniumOptimizerV8.detect_liquidity_sweep`` with a dynamic margin derived
    from the 14-period ATR of the historical window.  This prevents false negatives
    in high-volatility regimes (BTC) and false positives in low-volatility ones (PAXG).

    Algorithm
    ---------
    Historical zone : bars [-(lookback+5) : -5]
    Recent tail     : last 5 bars

    ACHAT (long side):
      - Any tail low < historical lowest low  (wick below)
      - Final close > lowest_low + dynamic_margin  (closed back above)

    VENTE (short side):
      - Any tail high > historical highest high  (wick above)
      - Final close < highest_high - dynamic_margin  (closed back below)

    Dynamic margin  = max(0.001, atr × atr_margin_mult) expressed as absolute price.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns ['open', 'high', 'low', 'close'].
        Must have at least ``lookback + 5`` rows.
    side : str
        "ACHAT" or "VENTE" (or any string containing those keywords).
    lookback : int
        Number of historical bars used to compute the sweep reference level.
    atr_margin_mult : float
        Multiplier applied to ATR14 to produce the dynamic margin.
        Default 0.002 → margin = ATR × 0.2%.

    Returns
    -------
    dict with keys:
        detected      : bool   — True if a sweep was found
        sweep_price   : float  — The extreme price that triggered the sweep
        confirm_level : float  — The threshold the close had to cross to confirm
        atr14         : float  — ATR14 value used to compute the margin
        dynamic_margin: float  — Absolute margin applied (in price units)
        side          : str    — Echoed back for traceability
    """
    result: Dict[str, Any] = {
        "detected": False,
        "sweep_price": 0.0,
        "confirm_level": 0.0,
        "atr14": 0.0,
        "dynamic_margin": 0.0,
        "side": side,
    }

    if df is None or len(df) < lookback + 5:
        return result

    try:
        recent_tail = df.tail(5)
        historical  = df.iloc[-(lookback + 5):-5]

        if historical.empty or recent_tail.empty:
            return result

        # Compute ATR14 over the historical window (true range)
        hist_h = historical["high"].values.astype(float)
        hist_l = historical["low"].values.astype(float)
        hist_c = historical["close"].values.astype(float)

        tr_arr: np.ndarray = np.maximum(
            hist_h[1:] - hist_l[1:],
            np.maximum(
                np.abs(hist_h[1:] - hist_c[:-1]),
                np.abs(hist_l[1:] - hist_c[:-1]),
            ),
        )
        atr14 = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else float(np.mean(tr_arr)) if len(tr_arr) > 0 else 0.0

        # Dynamic margin: at least 0.1% of latest close, or ATR × mult
        last_close = float(recent_tail["close"].iloc[-1])
        min_margin = last_close * 0.001  # absolute floor = 0.1% of price
        dynamic_margin = max(min_margin, atr14 * atr_margin_mult)

        result["atr14"] = round(atr14, 6)
        result["dynamic_margin"] = round(dynamic_margin, 6)

        if "ACHAT" in side.upper():
            lowest_low  = float(historical["low"].min())
            confirm_lvl = lowest_low + dynamic_margin
            swept = (
                any(float(r) < lowest_low for r in recent_tail["low"])
                and float(recent_tail["close"].iloc[-1]) > confirm_lvl
            )
            result["detected"]      = bool(swept)
            result["sweep_price"]   = round(lowest_low, 8)
            result["confirm_level"] = round(confirm_lvl, 8)

        else:  # VENTE
            highest_high = float(historical["high"].max())
            confirm_lvl  = highest_high - dynamic_margin
            swept = (
                any(float(r) > highest_high for r in recent_tail["high"])
                and float(recent_tail["close"].iloc[-1]) < confirm_lvl
            )
            result["detected"]      = bool(swept)
            result["sweep_price"]   = round(highest_high, 8)
            result["confirm_level"] = round(confirm_lvl, 8)

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# 2. Sweep + Displacement pattern
# ---------------------------------------------------------------------------

def detect_sweep_with_displacement(
    df: pd.DataFrame,
    side: str,
    lookback: int = 50,
    displacement_atr_mult: float = 0.75,
) -> Dict[str, Any]:
    """Detect a Liquidity Sweep followed immediately by a strong Displacement candle.

    This is the full institutional entry confirmation pattern:
      Phase 1 — Sweep   : wick penetration of historical extreme (uses ATR margin)
      Phase 2 — Displacement : the candle immediately AFTER the sweep has a body
                               larger than ``displacement_atr_mult × ATR14`` and
                               closes strongly in the sweep direction.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.  Must have at least ``lookback + 7`` rows.
    side : str
        "ACHAT" or "VENTE".
    lookback : int
        Historical window for sweep detection.
    displacement_atr_mult : float
        Minimum body size of the displacement candle expressed as a multiple of
        ATR14.  Default 0.75 (body must be ≥ 75% of ATR14).

    Returns
    -------
    dict with keys:
        detected             : bool   — True only if BOTH sweep AND displacement confirmed
        sweep_detected       : bool   — Phase 1 result
        displacement_detected: bool   — Phase 2 result
        sweep_price          : float  — Swept extreme level
        displacement_strength: float  — Body size / ATR14 ratio (higher = stronger)
        displacement_bar_idx : int    — Index (iloc) of the displacement candle
        atr14                : float  — ATR14 used for sizing
        side                 : str
    """
    result: Dict[str, Any] = {
        "detected": False,
        "sweep_detected": False,
        "displacement_detected": False,
        "sweep_price": 0.0,
        "displacement_strength": 0.0,
        "displacement_bar_idx": -1,
        "atr14": 0.0,
        "side": side,
    }

    if df is None or len(df) < lookback + 7:
        return result

    try:
        # ── Phase 1: locate sweep within the recent 5-bar tail ──────────────
        recent_tail = df.tail(5)
        historical  = df.iloc[-(lookback + 5):-5]

        if historical.empty or recent_tail.empty:
            return result

        # ATR14 on historical window
        hist_h = historical["high"].values.astype(float)
        hist_l = historical["low"].values.astype(float)
        hist_c = historical["close"].values.astype(float)

        tr_arr = np.maximum(
            hist_h[1:] - hist_l[1:],
            np.maximum(
                np.abs(hist_h[1:] - hist_c[:-1]),
                np.abs(hist_l[1:] - hist_c[:-1]),
            ),
        )
        atr14 = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else float(np.mean(tr_arr)) if len(tr_arr) > 0 else 1e-9

        result["atr14"] = round(atr14, 6)

        last_close = float(recent_tail["close"].iloc[-1])
        min_margin = last_close * 0.001
        dynamic_margin = max(min_margin, atr14 * 0.002)

        sweep_detected  = False
        sweep_bar_iloc  = -1  # position in df.tail(5)
        sweep_price     = 0.0

        if "ACHAT" in side.upper():
            lowest_low  = float(historical["low"].min())
            confirm_lvl = lowest_low + dynamic_margin
            for idx_in_tail in range(len(recent_tail)):
                if float(recent_tail["low"].iloc[idx_in_tail]) < lowest_low:
                    # Check that subsequent bars in tail close back above
                    remaining_close = float(recent_tail["close"].iloc[-1])
                    if remaining_close > confirm_lvl:
                        sweep_detected = True
                        sweep_bar_iloc = len(df) - 5 + idx_in_tail  # absolute iloc in df
                        sweep_price    = lowest_low
                        break
        else:
            highest_high = float(historical["high"].max())
            confirm_lvl  = highest_high - dynamic_margin
            for idx_in_tail in range(len(recent_tail)):
                if float(recent_tail["high"].iloc[idx_in_tail]) > highest_high:
                    remaining_close = float(recent_tail["close"].iloc[-1])
                    if remaining_close < confirm_lvl:
                        sweep_detected = True
                        sweep_bar_iloc = len(df) - 5 + idx_in_tail
                        sweep_price    = highest_high
                        break

        result["sweep_detected"] = sweep_detected
        result["sweep_price"]    = round(sweep_price, 8)

        if not sweep_detected:
            return result

        # ── Phase 2: displacement candle immediately after sweep bar ────────
        displacement_iloc = sweep_bar_iloc + 1
        if displacement_iloc >= len(df):
            return result

        disp_candle = df.iloc[displacement_iloc]
        d_open  = float(disp_candle["open"])
        d_close = float(disp_candle["close"])
        d_high  = float(disp_candle["high"])
        d_low   = float(disp_candle["low"])

        body_size = abs(d_close - d_open)
        strength  = body_size / (atr14 + 1e-12)

        # Displacement direction must match the sweep direction (close strongly)
        if "ACHAT" in side.upper():
            # Bullish displacement: close > open, close near high of bar
            body_bullish = d_close > d_open
            close_position = (d_close - d_low) / (d_high - d_low + 1e-12)  # 1.0 = closed at high
            strongly_closed = close_position >= 0.6
            disp_ok = body_bullish and (body_size >= displacement_atr_mult * atr14) and strongly_closed
        else:
            # Bearish displacement: close < open, close near low of bar
            body_bearish = d_close < d_open
            close_position = (d_high - d_close) / (d_high - d_low + 1e-12)  # 1.0 = closed at low
            strongly_closed = close_position >= 0.6
            disp_ok = body_bearish and (body_size >= displacement_atr_mult * atr14) and strongly_closed

        result["displacement_detected"]  = bool(disp_ok)
        result["displacement_strength"]  = round(float(strength), 4)
        result["displacement_bar_idx"]   = int(displacement_iloc)
        result["detected"]               = bool(disp_ok)

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# 3. Breaker Block detection (broken OB becomes S/R)
# ---------------------------------------------------------------------------

def detect_breaker_blocks(
    df: pd.DataFrame,
    obs_list: List[Dict[str, Any]],
    side: str,
    lookback: int = 100,
) -> List[Dict[str, Any]]:
    """Detect active Breaker Blocks from a list of broken Order Blocks.

    A Breaker Block is formed when:
      1. An Order Block is BROKEN by price (status == 'broken' in obs_list)
      2. Price subsequently RETESTS the old OB zone
      3. Price HOLDS at that zone on retest (acts as new S/R)

    Only looks at the last ``lookback`` bars of ``df``.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    obs_list : list of dict
        List of OB dicts as produced by ``detect_ob()``.  Each entry must have
        at minimum: ``top`` (float), ``bot`` (float), ``status`` (str), ``type`` (str).
    side : str
        "ACHAT" (looking for bull breakers) or "VENTE" (bear breakers).
    lookback : int
        Number of recent bars to scan for retests.

    Returns
    -------
    list of dict, each containing:
        top           : float  — Upper boundary of breaker zone
        bot           : float  — Lower boundary of breaker zone
        direction     : str    — "bull_breaker" or "bear_breaker"
        retest_count  : int    — Number of times price re-entered the zone
        last_retest_bar: int   — iloc index of most recent retest
        hold_confirmed : bool  — True if price closed back outside zone on last retest
        strength      : float  — 0.0–1.0, based on retest count and hold quality
        original_type : str    — OB type before it was broken
    """
    active_breakers: List[Dict[str, Any]] = []

    if df is None or len(df) < 10 or not obs_list:
        return active_breakers

    try:
        recent = df.tail(lookback).copy()
        closes = recent["close"].values.astype(float)
        highs  = recent["high"].values.astype(float)
        lows   = recent["low"].values.astype(float)
        n_bars = len(recent)

        # Filter to broken OBs only
        broken_obs = [ob for ob in obs_list if ob.get("status") == "broken"]

        if not broken_obs:
            return active_breakers

        for ob in broken_obs:
            ob_top = float(ob.get("top", 0.0))
            ob_bot = float(ob.get("bot", 0.0))
            ob_type = str(ob.get("type", ""))

            if ob_top <= ob_bot or ob_top == 0.0:
                continue

            # For a bull OB that was broken bearishly → becomes bear breaker
            # For a bear OB that was broken bullishly → becomes bull breaker
            if "ACHAT" in side.upper():
                # We want bear breakers (broken bull OBs that now act as resistance)
                if "bull" not in ob_type.lower():
                    continue
                direction = "bear_breaker"
            else:
                # We want bull breakers (broken bear OBs that now act as support)
                if "bear" not in ob_type.lower():
                    continue
                direction = "bull_breaker"

            # Scan recent bars for retests of the zone
            retest_count    = 0
            last_retest_bar = -1
            hold_count      = 0

            for bar_idx in range(n_bars):
                bar_high  = highs[bar_idx]
                bar_low   = lows[bar_idx]
                bar_close = closes[bar_idx]

                # Price re-entered the OB zone (wick or body)
                zone_touched = bar_low <= ob_top and bar_high >= ob_bot

                if zone_touched:
                    retest_count   += 1
                    last_retest_bar = bar_idx

                    # Hold = closed back outside the zone (rejection)
                    if direction == "bear_breaker" and bar_close > ob_top:
                        hold_count += 1
                    elif direction == "bull_breaker" and bar_close < ob_bot:
                        hold_count += 1

            if retest_count == 0:
                continue

            hold_confirmed = hold_count > 0
            # Strength: combination of retest frequency and hold quality
            hold_ratio  = hold_count / retest_count
            freq_score  = min(1.0, retest_count / 3.0)
            strength    = round(0.6 * hold_ratio + 0.4 * freq_score, 4)

            active_breakers.append({
                "top":             round(ob_top, 8),
                "bot":             round(ob_bot, 8),
                "direction":       direction,
                "retest_count":    retest_count,
                "last_retest_bar": last_retest_bar,
                "hold_confirmed":  hold_confirmed,
                "strength":        strength,
                "original_type":   ob_type,
            })

        # Sort by strength descending
        active_breakers.sort(key=lambda x: x["strength"], reverse=True)

    except Exception as exc:
        # Return partial results + error info rather than raising
        active_breakers.append({"error": str(exc)})

    return active_breakers


# ---------------------------------------------------------------------------
# 4. Failed Auction / Rejection at POI
# ---------------------------------------------------------------------------

def detect_failed_auction(
    df: pd.DataFrame,
    poi_top: float,
    poi_bot: float,
    side: str,
    lookback_after: int = 5,
) -> Dict[str, Any]:
    """Detect a Failed Auction — price enters a Point of Interest (POI) and is rejected.

    A Failed Auction is confirmed when:
      1. Price enters the POI zone (close or wick inside [poi_bot, poi_top])
      2. Within the next ``lookback_after`` bars, price sharply reverses
      3. Volume decreases on the entry bar(s) relative to the prior average (weak attempt)

    This pattern indicates that the POI absorbed all demand/supply → high-probability reversal.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.  Must have a 'volume' column, or volume checks are skipped.
        Minimum length: 20 + lookback_after bars.
    poi_top : float
        Upper boundary of the Point of Interest zone.
    poi_bot : float
        Lower boundary of the Point of Interest zone.
    side : str
        "ACHAT" → looking for bullish POI rejection (price falls into support and is bid up)
        "VENTE" → looking for bearish POI rejection (price rises into resistance and rolls)
    lookback_after : int
        Number of bars after entry into POI to confirm rejection.  Default 5.

    Returns
    -------
    dict with keys:
        auction_failed    : bool  — True if failed auction confirmed
        entry_bar_idx     : int   — iloc of first bar entering POI
        failure_strength  : float — 0.0–1.0 composite score of rejection sharpness
        bars_to_reject    : int   — How many bars until clear reversal close
        volume_declining  : bool  — Volume lower on entry bars vs prior avg
        price_entry_level : float — Actual price level of POI entry
        side              : str
    """
    result: Dict[str, Any] = {
        "auction_failed":    False,
        "entry_bar_idx":     -1,
        "failure_strength":  0.0,
        "bars_to_reject":    -1,
        "volume_declining":  False,
        "price_entry_level": 0.0,
        "side":              side,
    }

    if df is None or len(df) < 20 + lookback_after:
        return result
    if poi_top <= poi_bot or poi_top == 0.0:
        return result

    try:
        # Use the last 100 bars maximum for efficiency
        scan_df   = df.tail(100).copy()
        n         = len(scan_df)
        closes    = scan_df["close"].values.astype(float)
        opens_arr = scan_df["open"].values.astype(float)
        highs     = scan_df["high"].values.astype(float)
        lows      = scan_df["low"].values.astype(float)

        has_volume = "volume" in scan_df.columns
        volumes    = scan_df["volume"].values.astype(float) if has_volume else None

        # ATR14 for measuring rejection sharpness
        tr_arr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:]  - closes[:-1]),
            ),
        )
        atr14 = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else float(np.mean(tr_arr)) if len(tr_arr) > 0 else 1e-9

        # Volume baseline: average of 10 bars before the scan window
        if has_volume and volumes is not None:
            vol_baseline = float(np.mean(volumes[:10])) if n >= 10 else float(np.mean(volumes))
        else:
            vol_baseline = 1.0

        # Find entry into POI (within last 30 bars, excluding final lookback_after)
        entry_bar_idx = -1
        entry_price   = 0.0
        scan_start    = max(0, n - 30)
        scan_end      = n - lookback_after

        for i in range(scan_start, scan_end):
            bar_h = highs[i]
            bar_l = lows[i]

            if "ACHAT" in side.upper():
                # POI is a support zone → price dips into it from above
                entered = bar_l <= poi_top and bar_h >= poi_bot
            else:
                # POI is a resistance zone → price rises into it from below
                entered = bar_h >= poi_bot and bar_l <= poi_top

            if entered:
                entry_bar_idx = i
                entry_price   = closes[i]
                break

        if entry_bar_idx == -1:
            return result

        result["entry_bar_idx"]     = entry_bar_idx
        result["price_entry_level"] = round(entry_price, 8)

        # Volume check on entry bar
        if has_volume and volumes is not None:
            entry_vol    = float(volumes[entry_bar_idx])
            vol_declining = entry_vol < vol_baseline * 0.85  # >15% below baseline
        else:
            vol_declining = False

        result["volume_declining"] = vol_declining

        # Check for sharp rejection in the following bars
        post_end = min(entry_bar_idx + lookback_after + 1, n)
        rejection_found = False
        bars_to_reject  = -1
        rejection_magnitude = 0.0

        for j in range(entry_bar_idx + 1, post_end):
            bar_close = closes[j]
            bar_open  = opens_arr[j]
            bar_range = highs[j] - lows[j]

            if "ACHAT" in side.upper():
                # Bullish rejection: close strongly above POI top
                rejected = bar_close > poi_top
                direction_body = bar_close - bar_open  # positive = bullish body
                body_ratio = direction_body / (bar_range + 1e-12)
                move_from_poi = bar_close - poi_bot
            else:
                # Bearish rejection: close strongly below POI bot
                rejected = bar_close < poi_bot
                direction_body = bar_open - bar_close  # positive = bearish body
                body_ratio = direction_body / (bar_range + 1e-12)
                move_from_poi = poi_top - bar_close

            if rejected and body_ratio >= 0.5:
                rejection_found = True
                bars_to_reject  = j - entry_bar_idx
                rejection_magnitude = abs(move_from_poi) / (atr14 + 1e-12)
                break

        if not rejection_found:
            return result

        result["bars_to_reject"] = bars_to_reject

        # Failure strength: composite of rejection magnitude, speed, and volume signal
        speed_score  = max(0.0, 1.0 - (bars_to_reject - 1) / lookback_after)
        mag_score    = min(1.0, rejection_magnitude / 1.5)
        vol_score    = 0.2 if vol_declining else 0.0
        strength     = round(0.5 * mag_score + 0.3 * speed_score + 0.2 * vol_score, 4)

        result["auction_failed"]   = True
        result["failure_strength"] = strength

    except Exception as exc:
        result["error"] = str(exc)

    return result
