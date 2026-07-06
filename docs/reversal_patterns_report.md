# Titanium Dashboard v10 — Reversal Pattern Analysis Report

**Date:** 2026-03-29
**Analyst:** Reversal Pattern Analyst Agent
**File analyzed:** `titanium_dashboard_v10.py` (~5,800 lines)

---

## Executive Summary

- **Pattern coverage score: 5/10**
- **Existing SMC/reversal patterns: 12**
- **Missing high-value SMC patterns: 7**

The codebase has a solid foundation of basic reversal detection (candlestick patterns, OB/FVG zones, liquidity sweep, BOS/CHoCH structure), but several key SMC setups used by institutional traders are entirely absent. The most critical gap is the lack of a **Sweep + Displacement** confirmation gate and a **Breaker Block** detector — both are considered tier-1 SMC signals. The existing patterns also lack multi-timeframe divergence cross-validation and offer no composite reversal confidence measure beyond the generic 11-point score.

---

## 1. Existing Patterns Inventory

| # | Pattern | Function | Line | Quality (1–5) | Notes |
|---|---------|----------|------|----------------|-------|
| 1 | Liquidity Sweep (Stop Hunt) | `TitaniumOptimizerV8.detect_liquidity_sweep()` | 625 | **4/5** | Strong: checks wick below historical low AND close-back confirmation with 0.3% margin. Weakness: only looks at last 5 candles for the sweep tail — could miss slow, multi-candle sweeps. No volume confirmation. |
| 2 | Break of Structure / CHoCH | `_detect_market_structure()` | 1317 | **4/5** | Good: 3-pass pivot detection (HH/HL/LH/LL), BOS validated by close (not just wick), displacement body filter (> 0.5 ATR). Weakness: pivot detection uses only single-bar neighbors (i-1, i+1) — fragile on noisy TFs. No CHoCH vs BOS distinction exported in the label. |
| 3 | Order Block (bull/bear) | `detect_ob()` | 2628 | **3/5** | Detects the last bearish candle before a bullish move (bull OB) and vice versa, with intact/tested/broken status via `_ob_status()`. Weakness: uses only the immediate preceding candle — misses multi-candle OBs. No body-size minimum filter (any candle qualifies). Quality scoring exists (1.0 intact / 0.65 tested) but is simplistic. |
| 4 | Fair Value Gap (FVG) | `detect_fvg()` | 2595 | **3/5** | Standard 3-candle imbalance (h0 < l2 or l0 > h2). Includes width_pct for size filtering. Weakness: no partial fill tracking (FVG partially mitigated vs fresh), no minimum size threshold by default, no ATR normalization to filter micro-gaps. |
| 5 | OB + FVG Double Confirmation | `_has_ob_or_fvg_alignment()` | 1516 | **4/5** | Best pattern in the codebase. Combines FVG presence inside OB for a quality bonus (× 1.2), uses dynamic Fibonacci tolerance [0.618–0.786], skips broken OBs. Weakness: proximity check uses a single tolerance band — does not differentiate "price at OB midpoint" vs "price barely touching OB edge." |
| 6 | Fibonacci OTE Zone (0.618–0.786) | `_compute_fib_tolerance()` | 1435 | **3/5** | Calculates Fib zone for OB/FVG tolerance, not as a standalone signal. Swing detection uses raw `max/min` of tail (not structured pivot swing) — susceptible to outlier wicks distorting the reference swing. No 0.5 (equilibrium) or 0.79 (golden pocket) level tracking. |
| 7 | Rejection Candle (Pin Bar / Engulfing) | `_detect_rejection_candle()` | 1398 | **3/5** | Detects: (a) hammer/pin bar (lower wick > 2× body), (b) bullish/bearish engulfing, (c) strong body candle (> 60% range). Weakness: no ATR filter on body size — a tiny-range pin bar on a flat market qualifies equally to a strong reversal. No multi-candle context check (is the pin bar at a key level?). |
| 8 | Candlestick Pattern Library | `detect_candle_patterns()` | 2660 | **3/5** | 17 patterns: Doji, Spinning Top, Marubozu, Hammer, Shooting Star, Engulfing, Harami, Morning/Evening Star, Three White Soldiers, Three Black Crows, Tweezer Top/Bottom, Piercing Line, Dark Cloud Cover, Bull/Bear Kicker, Three Inside Up/Down. Weakness: these patterns are computed on 30s candles by default — very noisy. No ATR-normalization filter. Results are currently used only for frontend display, not integrated into the 11-point score. |
| 9 | Reversal Candle Scan | `detect_reversal_candles()` | 2823 | **2/5** | Simplified version of the candle library (7 patterns), used for chart highlighting. Subset of detect_candle_patterns() with no additional value. Fully display-only — not wired into scoring. |
| 10 | ADX Regime Filter | `TitaniumOptimizerV8.get_market_regime()` | 670 | **3/5** | Classifies TREND / RANGE via ADX14. Gives bonus in score if regime matches setup type. Weakness: binary classification only — no "weakening trend" or "transition" state. Single timeframe (30m). In TREND regime, any OB/FVG qualifies — does not verify the OB is in the direction of the trend impulse leg. |
| 11 | Delta Volume (Buy/Sell Pressure) | Integrated in `score_setup()` | 1882 | **3/5** | Uses aggTrade stream to track buy vs sell volume. Confirms signal if pressure aligns with direction. Weakness: staleness threshold is 2 minutes (reasonable), but no rolling window normalization — raw delta pct can be skewed by one large trade. No order-flow imbalance threshold (any positive delta qualifies). |
| 12 | EMA200 Trend Bias (H4 + 1D) | `compute_ema200()` + scoring | 1310, 1864 | **4/5** | Two independent EMA200 checks (H4 and 1D) providing macro and intermediate bias alignment. Well-implemented with close vs EMA comparison. Weakness: EMA200 is a lagging indicator — at trend transitions, it generates false alignment signals for several candles. No slope/momentum check on the EMA itself. |

**Scoring methodology for quality (1–5):**
- 5 = Complete logic, multi-TF validated, low false-positive risk, robust edge cases
- 4 = Solid logic, minor gaps in confirmation or edge case handling
- 3 = Functional but single-dimension, susceptible to noise, no ATR normalization
- 2 = Partial implementation, display-only or redundant
- 1 = Stub or trivially incorrect

---

## 2. Missing SMC Reversal Patterns

### 2.1 Sweep + Displacement

**Pattern name:** Sweep + Displacement (Impulse Confirmation)

**SMC theory:** A liquidity sweep alone is a necessary but not sufficient signal. The sweep removes stop orders (either buy-stops above a high or sell-stops below a low). The critical confirmation is the **displacement candle** that immediately follows: a large-body candle (typically > 1× ATR) that moves decisively away from the swept level. This displacement indicates that smart money has entered with size and is driving price. Without the displacement, a sweep can simply be a consolidation wick, not a reversal trigger.

**Detection logic:**
1. Detect a liquidity sweep (wick below/above historical extreme) using the existing `detect_liquidity_sweep()` logic.
2. On the candle(s) immediately following the sweep tail (next 1–3 candles):
   - Calculate body size = `abs(close - open)`
   - Calculate ATR14 on the current DataFrame
   - Require: `body >= 1.0 × ATR14` (displacement minimum size)
   - Require: candle direction aligns with the reversal (close > open for long, close < open for short)
   - Require: candle closes **inside** the pre-sweep range (not back below the sweep low)
3. If all conditions met → `sweep_displacement_confirmed = True`
4. Optional strong confirmation: displacement candle's close breaks the most recent swing high/low on the entry TF.

**Required data:** 30m OHLCV (df_m30), ATR14, last 5 candles post-sweep, existing `detect_liquidity_sweep()`.

**Priority: P1** — This is the single most common institutional entry trigger in SMC. The existing sweep detection scores a point without verifying that a displacement followed. This creates the most significant false-positive risk in the current scoring system.

**Estimated false-positive rate:** Low (< 20%) when body >= 1× ATR and directional close are both required.

---

### 2.2 Inducement → Sweep → CHoCH (3-Phase SMC Setup)

**Pattern name:** Inducement + Sweep + CHoCH (3-Phase Institutional Sequence)

**SMC theory:** This is the full SMC narrative for a major reversal:
- **Phase 1 — Inducement:** Price creates a minor swing high/low (often a small consolidation or fake breakout) that induces retail traders to place stops. This is typically identified as a fractal that looks like a continuation but is actually a trap.
- **Phase 2 — Sweep:** Price aggressively sweeps through the inducement level, triggering retail stop-losses and creating the liquidity pool that smart money needs to fill large orders.
- **Phase 3 — CHoCH (Change of Character):** After the sweep, price breaks the structure in the opposite direction — confirming the reversal intent of the smart money entry.

**Detection logic:**
1. **Inducement detection:** Find the last minor swing high (for short setup) or swing low (for long setup) using 2-bar pivot logic. Record the inducement level `ind_level`.
2. **Sweep confirmation:** Check if the most recent candle's wick has broken `ind_level` with a close-back (same logic as existing sweep detection but scoped to the inducement level, not just historical extremes).
3. **CHoCH detection (new):** After the sweep candle, check if any of the next 1–5 candles has broken the **opposite** swing (e.g., for a long setup: did price close above the last minor swing high that existed before the sweep?). This is the structural flip that confirms CHoCH vs a simple retracement.
4. All 3 phases must be detected in chronological sequence within the same lookback window (e.g., 20–40 candles).
5. Output: `three_phase_smc_ok = True | False`, phase labels for display.

**Required data:** 5m or 15m OHLCV, swing pivot detection (reuse `_detect_market_structure()` pivot logic), ATR14.

**Priority: P1** — Provides the highest-conviction reversal context. Currently the codebase detects sweep and BOS independently but never validates them as part of the same 3-phase sequence.

**Estimated false-positive rate:** Low (< 25%) when all 3 phases are sequential and within a bounded window.

---

### 2.3 RSI Divergence at Order Block

**Pattern name:** RSI Divergence at OB (Classic or Hidden)

**SMC theory:** When price retests an Order Block and simultaneously shows RSI divergence (price makes a new low but RSI makes a higher low, for bullish divergence), it dramatically increases the probability that the OB will hold. The OB provides the structural reason (institutional demand), and the RSI divergence provides the momentum exhaustion evidence — two independent signals pointing to the same reversal.

**Detection logic:**
1. Detect an active Order Block (using existing `detect_ob()`) with status `intact` or `tested`.
2. On the confirmation TF (5m or 15m), identify the last 2 swing lows (for bullish setup):
   - `swing_low_1` = older swing low with RSI value `rsi_1`
   - `swing_low_2` = more recent swing low (current retest of OB) with RSI value `rsi_2`
3. Bullish divergence condition: `swing_low_2 < swing_low_1` (price lower) AND `rsi_2 > rsi_1` (RSI higher)
4. Bearish divergence condition (short setup): `swing_high_2 > swing_high_1` AND `rsi_high_2 < rsi_high_1`
5. Require: the more recent swing coincides with price being inside or within 1× ATR of the OB zone.
6. Minimum RSI divergence: `abs(rsi_2 - rsi_1) >= 3 points` (avoids noise).

**Required data:** 5m or 15m OHLCV for RSI14, swing pivot detection, existing OB detection output.

**Priority: P1** — RSI divergence at OB is one of the most reliable confluence filters in SMC. Currently the RSI fallback in `score_setup()` only checks absolute RSI level (oversold/overbought), ignoring divergence entirely.

**Estimated false-positive rate:** Medium (30–40%) — divergence alone is unreliable, but combined with OB proximity it becomes a strong signal.

---

### 2.4 Failed Auction (Multiple Rejections at Key Level)

**Pattern name:** Failed Auction / Multiple Rejection Pattern

**SMC theory:** A Failed Auction occurs when price attempts to close above (or below) a key level multiple times but fails on each attempt. Each failure represents a rejection of the auction price at that level, suggesting insufficient demand (or supply) to sustain the move. After 2–3 failed attempts, the probability of a reversal increases sharply because the level has proven to be a strong barrier, and the failed attempts themselves have consumed buy-side (or sell-side) fuel.

**Detection logic:**
1. Define a "key level" as either: an OB top/bot, an FVG midpoint, a round number (price divisible by a significant step), or the last ATH/ATL within the lookback window.
2. Scan the last N candles (N = 30–50): count how many candles have a wick that touched the key level zone (within 0.2% tolerance) but closed on the opposite side.
3. `rejection_count >= 2` → Failed Auction condition met.
4. Additional filter: the candles performing the rejection should not be equally spaced (organic behavior), and at least one should be a pin bar or engulfing.
5. Output: `failed_auction_ok = True`, `rejection_count`, `key_level_tested`.

**Required data:** 15m or 30m OHLCV, OB/FVG zone data, ATR for tolerance.

**Priority: P2** — Particularly valuable for RANGE regime (where ADX is low) as it identifies consolidation boundaries with precision. Complements the existing `adx_regime` scoring criterion.

**Estimated false-positive rate:** Medium (30–45%) — key level identification is subjective; tight tolerance required.

---

### 2.5 Breaker Block

**Pattern name:** Breaker Block (Flip Structure)

**SMC theory:** A Breaker Block is a previously valid Order Block that has been **broken through** (its status is `broken` in the current codebase). Once an OB is broken, it typically flips its role: a former bull OB (demand zone) becomes a supply zone (resistance), and vice versa. Price frequently returns to test this flipped level, which then acts as a high-probability reversal zone — because smart money repositions at the level where they previously exited stop-outs.

**Detection logic:**
1. Use the existing `_ob_status()` and `detect_ob()` to collect all OBs with `status == "broken"`.
2. For each broken OB, record its `ob_top` and `ob_bot` range as a **Breaker Block zone**, with flipped polarity:
   - A former bull OB (broken bearishly) → becomes a Breaker Block supply zone
   - A former bear OB (broken bullishly) → becomes a Breaker Block demand zone
3. Check if the current price is within the Breaker Block zone (within ATR tolerance).
4. Require: price has returned to this zone from the direction of the breakout (i.e., a true retest, not a continued move through).
5. Confirm with a rejection candle at the Breaker Block zone.

**Required data:** 30m or 15m OHLCV, existing `detect_ob()` output (specifically broken OBs), ATR, existing `_detect_rejection_candle()`.

**Priority: P1** — Currently the codebase explicitly skips broken OBs (`continue` in `_has_ob_or_fvg_alignment()` at line 1584). Breaker Blocks are the second most important structural level after Order Blocks in full SMC methodology. Adding this detection requires minimal new code — it reuses most existing infrastructure.

**Estimated false-positive rate:** Low–Medium (25–35%) — works best when combined with a rejection candle confirmation.

---

### 2.6 Mitigation Block

**Pattern name:** Mitigation Block (Partially Filled OB)

**SMC theory:** A Mitigation Block is an Order Block that has been **partially tested** (price entered the zone but did not close through it — `status == "tested"` in the current codebase). "Mitigation" refers to the partial filling of pending orders at the OB. The key distinction from a fresh OB: on the first test, some pending orders are filled (partial mitigation). When price returns for a **second visit**, the remaining unfilled orders act as a stronger magnet — because (a) the remaining liquidity is concentrated, and (b) the fact that price reversed on the first test is evidence the level is defended.

**Detection logic:**
1. Use existing OB detection to identify OBs with `status == "tested"`.
2. Track visit history: count how many times the OB zone has been tested (`touch_count`).
3. Mitigation Block condition: `touch_count == 1` (first touch confirmed rejection) and price is returning to the zone for a second approach.
4. Detect "returning" price: the current close is moving toward the OB zone from the confirmation candle, with at least one candle gap between visits.
5. Assign a higher quality score (e.g., 1.1 vs 1.0 for fresh OB) to reflect the concentration of remaining liquidity.
6. Require: the zone has NOT been fully broken since the first test.

**Required data:** 30m or 15m OHLCV, OB detection with enhanced touch-count tracking (minor extension to existing `_ob_status()`).

**Priority: P2** — Upgrades the existing "tested" OB handling from a quality penalty (currently 0.65 vs 1.0) to a quality opportunity (second visit to a tested OB should score higher, not lower). This is a conceptual correction as much as a new pattern.

**Estimated false-positive rate:** Medium (30–40%) — requires reliable first-visit detection and a clear re-approach structure.

---

### 2.7 Premium / Discount Zone Entry

**Pattern name:** Premium / Discount Zone (Fibonacci Equilibrium Filter)

**SMC theory:** In SMC, every price swing is divided into three zones:
- **Premium zone** (top 38.2% of the swing, above 61.8% retracement): price is expensive — optimal zone for short entries.
- **Equilibrium** (50% retracement): neutral; neither premium nor discount.
- **Discount zone** (bottom 38.2% of the swing, below 38.2% retracement): price is cheap — optimal zone for long entries.
Smart money consistently sells in premium zones and buys in discount zones. An OB or FVG located within the correct zone (discount for longs, premium for shorts) has significantly higher probability than one located at the equilibrium or wrong zone.

**Detection logic:**
1. Identify the last significant swing: `swing_high = max(high, lookback=60)`, `swing_low = min(low, lookback=60)`. This already partially exists in `_compute_fib_tolerance()` — but currently only computes 0.618–0.786 for tolerance, not for zone classification.
2. Calculate the full Fibonacci grid:
   - `fib_50  = swing_low + 0.50 × (swing_high - swing_low)`
   - `fib_618 = swing_low + 0.618 × (swing_high - swing_low)`
   - `fib_786 = swing_low + 0.786 × (swing_high - swing_low)`
3. Classify current price:
   - For LONG setups: `in_discount = price <= fib_50` (price is in the lower half of the swing)
   - For SHORT setups: `in_premium = price >= fib_50` (price is in the upper half of the swing)
4. Ideal entry zone (OTE — Optimal Trade Entry): `fib_618 to fib_786` (long OTE = discount of discount; short OTE = premium of premium).
5. Output: `zone = "DISCOUNT" | "PREMIUM" | "EQUILIBRIUM"`, `in_ote = True | False`.
6. Bonus points in scoring if OB/FVG is located within the OTE zone.

**Required data:** 30m or H1 OHLCV for swing identification (same data already used), `_compute_fib_tolerance()` extended to return zone classification.

**Priority: P2** — The code already calculates Fibonacci levels for tolerance (`_compute_fib_tolerance()`) but discards the zone classification. Converting this partial calculation into a zone filter requires trivial additional code. This would make the existing OB/FVG quality scoring significantly more accurate.

**Estimated false-positive rate:** Low (15–25%) — Fibonacci zone filtering is a powerful noise reducer. The main risk is incorrect swing identification, which is already present in the codebase.

---

## 3. Reversal Confidence Score Proposal

### 3.1 Design Philosophy

The existing 11-point score measures **setup quality** (multi-timeframe alignment, macro bias, structural confirmation). The proposed **Reversal Confidence Score (RCS)** measures **reversal probability specifically** — it is a separate, orthogonal metric that focuses on the entry event itself rather than the broader setup context.

The RCS is computed on a **0.0 to 10.0 floating-point scale**, published alongside the existing integer score as `reversal_confidence` in the `algo_context` dict.

### 3.2 Component Weights Table

| # | Component | Max Points | Rationale |
|---|-----------|-----------|-----------|
| C1 | Liquidity Sweep confirmed | 2.0 | Most reliable single reversal trigger (institutional stop-hunt) |
| C2 | Sweep + Displacement candle | +1.5 bonus | Displacement confirms smart money entry; applies only if C1 is true |
| C3 | Rejection candle at OB/FVG zone | 1.5 | Price action confirmation at structural level |
| C4 | OB/FVG zone quality (intact=1.0, tested=0.65, fvg=0.85) | 1.5 | Structural level strength |
| C5 | Multi-TF structure alignment (H2 + H1 + 1D all aligned) | 1.0 | Macro confluence |
| C6 | ADX regime matches setup type | 0.5 | Confirms market is in a state where the reversal pattern works |
| C7 | Delta Volume confirms direction | 0.5 | Real-time order flow evidence |
| C8 | RSI divergence at zone (if detected) | 1.0 | Independent momentum exhaustion signal |
| C9 | Premium/Discount zone alignment | 0.5 | OB/FVG in correct Fibonacci half of swing |
| C10 | Distance from last liquidity pool (<= 0.5× ATR) | 1.0 | Proximity to unfilled institutional orders |
| **Total** | | **11.0 capped to 10.0** | |

### 3.3 Scoring Formula

```
RCS_raw = (
    C1_sweep * 2.0
  + C2_displacement * 1.5  # only if C1 == True
  + C3_rejection * 1.5
  + C4_ob_quality * 1.5    # ob_quality_30m from existing algo_context [0.0–1.0] * 1.5
  + C5_mtf_align * 1.0     # 1.0 if ALIGN(H2+H1) AND EMA200(1D) both confirmed, 0.5 if one
  + C6_adx_regime * 0.5
  + C7_delta_vol * 0.5
  + C8_rsi_divergence * 1.0
  + C9_fib_zone * 0.5       # 0.5 if in OTE (0.618–0.786), 0.25 if in correct half only
  + C10_liq_proximity * 1.0 # 1.0 if within 0.5 ATR of last sweep level, 0.5 if within 1 ATR
)

RCS = min(10.0, round(RCS_raw, 2))
```

Where all `C*` components are boolean (0 or 1) except `C4_ob_quality` (float 0.0–1.0) and `C9_fib_zone` (0.0, 0.25, or 0.5).

### 3.4 Interpretation Thresholds

| RCS Range | Interpretation | Recommended Action |
|-----------|---------------|-------------------|
| 0.0 – 2.9 | Weak reversal evidence | Ignore or paper-trade only |
| 3.0 – 4.9 | Partial confluence | Wait for additional confirmation before entry |
| 5.0 – 6.9 | Solid reversal setup | Valid signal, standard position size |
| 7.0 – 8.9 | High-confidence reversal | Full position size, tighter SL permissible |
| 9.0 – 10.0 | Exceptional setup (rare) | Maximum conviction; institutional-grade signal |

### 3.5 Key Design Constraints

- **RCS never replaces the 11-point score** — it supplements it. A signal can have a high 11-point score (good macro context) but a low RCS (no actual reversal evidence on entry TF), and vice versa.
- **Displacement bonus (C2) is conditional** on C1 being true — this enforces the logical dependency and prevents inflated scores.
- **C8 (RSI divergence) defaults to 0** if the detection function does not exist — the score degrades gracefully as missing patterns are not yet implemented.
- **Minimum viable RCS** for signal emission should be configurable via `.env` (`RCS_MIN = 4.0` recommended as starting value).

---

## 4. Integration Recommendations

### 4.1 Where to Compute RCS

Compute the RCS at the end of `score_setup()`, after all existing criteria have been evaluated but before the final `algo_context` dict is assembled. The RCS can use data already computed within `score_setup()` (e.g., `ob_fvg_ok`, `ob_quality_30m`, `liq_sweep_ok`, `rejection_ok`, `align_bonus`, `delta_vol_ok`, `adx_regime_bonus`) — requiring no additional data fetches.

The only components requiring new functions are: C2 (displacement), C8 (RSI divergence), C9 (Fibonacci zone), and C10 (liquidity proximity distance). These functions are self-contained and can be added as private helpers alongside `_detect_rejection_candle()` and `_has_ob_or_fvg_alignment()`.

### 4.2 Changes to `algo_context`

Add the following keys to the `algo_context` dict returned by `score_setup()`:

```python
algo_context["reversal_confidence"] = rcs_value          # float 0.0–10.0
algo_context["rcs_components"] = {                       # breakdown for UI display
    "sweep":          liq_sweep_ok,
    "displacement":   displacement_ok,       # new
    "rejection":      rejection_ok,
    "ob_quality":     ob_quality_30m,
    "mtf_align":      ...,
    "adx_regime":     adx_regime_bonus,
    "delta_vol":      delta_vol_ok,
    "rsi_divergence": rsi_div_ok,            # new
    "fib_zone":       fib_zone_score,        # new (extended from existing)
    "liq_proximity":  liq_prox_score,        # new
}
```

### 4.3 Integration with the 11-Point Score

Two integration options (not mutually exclusive):

**Option A — Parallel gate (recommended):**
Keep the existing 11-point score as-is. Add a secondary filter: a signal is only emitted if BOTH `score >= SCORE_MIN_REQUIRED (7)` AND `reversal_confidence >= RCS_MIN (4.0)`. This is the safest integration — the 11-point score handles macro bias and context, the RCS handles reversal timing precision.

**Option B — RCS as a scoring criterion:**
Add `reversal_confidence >= 5.0` as criterion 12 in the 11-point system (making it a 12-point system), contributing `+1` to `score_raw`. This reduces the weight of each individual component but ties the score more directly to reversal quality. Downside: it conflates context quality with timing quality.

**Recommendation:** Implement Option A first. After 30+ days of signal history data, analyze whether `reversal_confidence` correlates with signal outcomes (`win/loss/pending` in `signal_history.json`). If the correlation is strong (> 0.3 Pearson), consider Option B in a future version.

### 4.4 Display on the Dashboard

The `titanium_dashboard.html` frontend already displays `confs[]` (confirmations array) and `algo_context` data. The RCS should be added as:
- A visual gauge or progress bar (0–10 scale, color-coded by threshold) in the signal card
- A tooltip breakdown showing each `rcs_components` key
- A filter control in the sidebar allowing users to set a minimum RCS threshold

### 4.5 Learning Loop Integration

The existing `learning_report_loop()` adapts `scoring_weights[]` per symbol based on signal outcomes. Once RCS is implemented, extend the learning loop to also correlate `reversal_confidence` values with outcomes. Symbols where high RCS consistently predicts wins can have the `RCS_MIN` threshold raised (more selective) or the `RCS` weight in Option B increased.

### 4.6 Implementation Priority Order

| Step | Task | Estimated effort |
|------|------|-----------------|
| 1 | Add Breaker Block detection (reuses existing broken-OB data) | Low |
| 2 | Extend `_compute_fib_tolerance()` to return zone classification (Premium/Discount/OTE) | Low |
| 3 | Add displacement confirmation to `detect_liquidity_sweep()` | Low–Medium |
| 4 | Add RSI divergence detector at OB (new helper function) | Medium |
| 5 | Assemble RCS formula in `score_setup()` using available data | Low (after steps 1–4) |
| 6 | Add Sweep + CHoCH 3-phase sequence detector | Medium–High |
| 7 | Add Mitigation Block touch-count tracking | Medium |
| 8 | Add Failed Auction detector | Medium |

Steps 1–5 represent the highest-value additions with the lowest implementation risk and are recommended for the next version iteration.

---

*Report generated by the Reversal Pattern Analyst Agent — Titanium Dashboard v10 codebase review.*
