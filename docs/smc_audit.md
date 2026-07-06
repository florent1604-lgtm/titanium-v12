# Titanium Dashboard v10 — SMC Audit Report
**Date**: 2026-03-29
**File audited**: `titanium_dashboard_v10.py` (~5,800 lines)
**Auditor**: SMC AUDITOR Agent (Claude Sonnet 4.6)

---

## Executive Summary

**Overall SMC Health Score: 6.5 / 10**

| Status | Count |
|--------|-------|
| PASS   | 5     |
| WARN   | 4     |
| FAIL   | 1     |

The codebase is well-structured and shows serious SMC intent. The core structural detection (BOS/CHoCH), OB status tracking, FVG detection, and liquidity sweep logic are all implemented with attention to quality. However, the system carries a meaningful set of silent signal degradation paths, a fundamental scoring architecture inconsistency (the score is labelled `/11` in some places and `/7` or `/9` in others), a TRIX backtest that is long-only (missing short-side performance), and a liquidity sweep that uses the wrong reference frame relative to the ADX regime integration. None of the weaknesses constitute a critical security or data-safety issue, but they degrade signal quality and can cause over-counting or under-counting of score points.

---

## Component Audits

---

### 1. CHoCH / BOS Detection

**Status: WARN**
**Location**: `_detect_market_structure()` — line ~1317

**What it does**:
Identifies market structure (Higher High / Higher Low → BULLISH; Lower High / Lower Low → BEARISH) over the last `n` candles. Uses a 3-pass algorithm: (1) detect pivot highs and lows with single-candle look-around, (2) validate BOS by requiring the close to exceed the last pivot in the last 5 candles, (3) apply an ATR displacement filter (body ≥ 0.5 × ATR14). Falls back to softer pivot+close-only rule when the displacement filter blocks both sides.

**Finding**:
- The pivot detection (`highs[i] > highs[i-1] and highs[i] > highs[i+1]`) uses a 1-bar neighbourhood. This is a minimal definition of a swing pivot and is very sensitive to noise on lower timeframes (H1, H2). A standard SMC pivot uses at minimum a 2–3 bar look-around on each side.
- The BOS confirmation window `closes[-5:]` is fixed at 5 candles regardless of the timeframe passed (H2 vs H1). On H2, 5 candles = 10 hours — acceptable. On H1, 5 candles = 5 hours — structurally reasonable, but inconsistency across frames is a latent source of divergence between `struct_h2` and `struct_h1` readings.
- The fallback path (`bull_structure = hh and hl and bos_bull_by_close` without displacement check) silently removes the most protective filter when displacement is not detected. A ranging market with two pivot swings and a single close above the last PH will register as BULLISH. This is the most common path during low-volatility periods.
- CHoCH (Change of Character — the moment when the **first** BOS in the opposite direction occurs) is not separately tracked. The function only returns the current structure label. There is no event emitted when structure flips from BEARISH to BULLISH or vice versa. In SMC theory, the CHoCH is the trigger event; here it must be inferred by comparing consecutive `struct_h2` values, which requires the caller to maintain state. No caller in the codebase does this.

**Recommendation**:
- Expand pivot detection to 2-bar neighbourhood minimum (`highs[i] > max(highs[i-2:i]) and highs[i] > max(highs[i+1:i+3])`).
- Separate CHoCH detection from BOS detection and surface it as a boolean event in `algo_context`.
- Harden the fallback by requiring at least 2 consecutive closes above the last PH (not just 1) to qualify as BOS without displacement.

---

### 2. Liquidity Sweep Detection

**Status: WARN**
**Location**: `TitaniumOptimizerV8.detect_liquidity_sweep()` — line ~625

**What it does**:
Looks at the last `LIQUIDITY_LOOKBACK+5` candles. Divides them into a "historical" zone (candles `[-(LOOKBACK+5):-5]`) and a "recent tail" (last 5 candles). For a LONG setup: checks whether any low in the tail went below the historical minimum, AND whether the latest close recovered above that minimum + 0.3%. For SHORT: analogous logic with the historical maximum.

**Finding**:
- The 0.3% confirmation margin (`lowest_low * 1.003`) is a flat percentage regardless of asset volatility. For PAXG/Gold (~$3,000), 0.3% = $9, which is a reasonable intraday wick for XAU/USD. For SOL (~$100), 0.3% = $0.30, which may be inside the spread on low-liquidity moments. The margin is not scaled to ATR.
- The look-around on the tail is 5 candles and on the historical zone is `LIQUIDITY_LOOKBACK` (default 50). This is a sensible design. However, the function receives a mixed-provenance DataFrame: in `score_setup()` (line ~1902) the fallback is `df30` (30-second candles) when `df_m30` is insufficient. A 30-second sweep using a 50-bar historical zone covers only ~25 minutes of history — far too short to represent meaningful institutional liquidity. This is a silent degradation.
- The variable name `side` is assumed to contain "ACHAT" for long detection. The string is constructed from French (`"ACHAT [LONG]"` / `"VENTE [SHORT]"`). This coupling between the detection logic and the French label convention is fragile; any refactoring of the side string will silently break the sweep detection for all signals.

**Recommendation**:
- Scale the confirmation margin to `max(0.003 * lowest_low, 0.5 * atr_val)` so it is proportional to instrument volatility.
- When `df_m30` is unavailable, refuse to run sweep detection rather than silently degrading to the 30-second store. Return `False` in that case and log a debug message.
- Decouple from French string matching. Use a `side_is_long: bool` parameter or a normalised `"long"/"short"` string.

---

### 3. Order Block Detection

**Status: PASS**
**Location**: `detect_ob()` — line ~2628; `_has_ob_or_fvg_alignment()` — line ~1516; `_ob_status()` — line ~1465

**What it does**:
`detect_ob()` scans the last `n` candles in reverse, identifies the most recent bearish candle (for LONG) or bullish candle (for SHORT) as the OB, computes its top/bottom, and assigns a status (intact/tested/broken) based on subsequent price action. The `_has_ob_or_fvg_alignment()` function checks whether current price is within a tolerance zone around an OB, skips broken OBs, and awards a quality score (1.0 intact, 0.65 tested). A bonus is applied when a FVG is co-located inside the OB zone.

**Finding**:
- OB definition is standard SMC: the last opposing candle before a decisive move. The implementation is correct and uses OHLC data appropriately.
- Status classification in `_ob_status()` correctly uses close-based invalidation (close below OB bottom for a bullish OB = broken). Wick-only touch = tested. This is consistent with ICT/SMC methodology.
- The FVG-in-OB double confirmation bonus (`quality = min(1.0, quality * 1.2)`) is capped at 1.0, so it cannot inflate the score beyond the maximum.
- The proximity tolerance uses the dynamic Fibonacci zone (`_compute_fib_tolerance()`), which improves on a fixed ATR multiplier and is methodologically sound.
- The `detect_ob()` function used for the frontend (`detect_ob(df30, side, n=60)`) operates on the 30-second store — this is the same degradation concern noted for the sweep detection, but the frontend use is informational rather than scoring-critical.

**No critical issues found.**

---

### 4. Fair Value Gap (FVG) Detection

**Status: WARN**
**Location**: `detect_fvg()` — line ~2595; FVG detection inside `_has_ob_or_fvg_alignment()` — line ~1546

**What it does**:
`detect_fvg()` iterates candles in a window of `n` (default 200), checking three-candle patterns: if `high[i-2] < low[i]` then a bullish FVG exists between those two levels; if `low[i-2] > high[i]` then a bearish FVG. Returns all detected FVGs with their zone coordinates, timestamp, type, and width percentage. No staleness filter is applied.

**Finding**:
- The three-candle FVG pattern definition is correct and standard.
- **Critical absence: no staleness / mitigation filter.** A FVG detected 200 candles ago that has since been fully filled (price traded through both boundaries) is still returned with no indication of its fill status. The `detect_fvg()` function was explicitly de-capped in v4 ("Note v4 : cap retiré"). This means the frontend and the OB/FVG double-confirmation logic may reference FVGs that have been entirely mitigated. In SMC, a filled FVG is no longer a valid zone of interest.
- Inside `_has_ob_or_fvg_alignment()`, the FVG check only tests proximity (`abs(price - mid) <= tol`). It does not check whether the FVG was subsequently traded through. An old, fully-filled FVG at the right price level will still generate a `True` return with quality 0.85.
- The proximity check uses the midpoint of the FVG zone, not the nearest boundary. This is methodologically defensible but means price is checked against the centre rather than whether price has entered the zone at all.
- `width_pct` is calculated but not used in scoring — it is available for informational display only.

**Recommendation**:
- Add a mitigation check: after detecting a FVG, scan subsequent candles to determine if any candle's range fully overlapped the FVG (both boundaries breached). Mark such FVGs as `mitigated=True` and exclude them from scoring proximity checks.
- In `_has_ob_or_fvg_alignment()`, replace the midpoint check with a boundary-entry check: `(fvg_bot - tol) <= price <= (fvg_top + tol)` to confirm price is actually inside or touching the zone.

---

### 5. ADX Regime Classification

**Status: PASS**
**Location**: `TitaniumOptimizerV8.get_market_regime()` — line ~670

**What it does**:
Computes ADX14 on the provided DataFrame using `pandas_ta.adx()`. Returns `"TREND"` if the ADX value exceeds `ADX_TREND_THRESHOLD` (default 27), `"RANGE"` otherwise, or `"UNKNOWN"` if data is insufficient or computation fails. The ADX column name is resolved dynamically to handle different `pandas_ta` version casing.

**Finding**:
- ADX14 is the standard industry setting. The threshold of 27.0 (raised from 25 in v9) is more selective and appropriate for crypto volatility regimes.
- The function handles `NaN` values and empty DataFrames defensively.
- Column name resolution handles different `pandas_ta` version casing (ADX_14 vs adx_14) correctly.
- In `score_setup()` (line ~1915), the regime bonus is awarded when: TREND AND OB/FVG is present, OR RANGE AND OB status is 'intact' or 'tested'. This is methodologically sound: trending markets favor continuation plays near FVGs; ranging markets favor mean-reversion at intact OBs.
- One limitation: ADX alone does not indicate directional bias. ADX > 27 could be a strong downtrend or uptrend. The directional alignment is correctly handled by the EMA200 bias (criterion 1), so ADX serves purely as a regime filter — which is its correct SMC role.

**No critical issues found.**

---

### 6. Multi-Timeframe Alignment

**Status: WARN**
**Location**: `score_setup()` — line ~1604; `scan_loop()` — line ~4437

**What it does**:
Fetches 9 timeframes concurrently (H4, H2, H1, 30m, 15m, 5m, 3m, 1m, 1D) per symbol via `asyncio.gather()`. The scoring function uses H4 for macro bias, H2+H1 for structural confirmation, 30m+15m for OB/FVG zones, and 5m for TRIX/RSI entry. Active TF adjusts OB lookback windows and the rejection candle confirmation timeframe.

**Finding**:
- The MTF cascade (H4 → H2 → H1 → 30m → 15m → 5m) is correctly ordered from highest to lowest timeframe, consistent with SMC top-down analysis.
- The `ALIGN_H2H1` bonus correctly requires both H2 and H1 structure to align with the H4 bias — a sound confluence requirement.
- **Score labelling inconsistency**: The docstring in `score_setup()` says "score /9", the comments in v8 changelog say "/11", `score_max` in the broadcast payload is hardcoded to `11`, but the log line at line ~4757 says `"score=%s/7"`. The `SCORE_CRITERIA` list has 11 entries. The actual maximum possible `score_raw` from the implementation is: EMA200_H4 (1) + STRUCT (1) + ALIGN bonus (1) + OB30m (quality-weighted, max 1) + OB15m (quality-weighted, max 1) + REJET (1) + TRIX (1) + EMA200_1D (1) + DELTA_VOL (1) + LIQ_SWEEP (1) + ADX_REGIME (1) = 11 maximum, minus 1 possible for ATR gate = 10 minimum possible. But because OB criteria are quality-weighted floats (not integers), `score_raw` is a float clamped to `min(11, int(round(score_raw)))`. This is correct but the inconsistent labelling creates confusion about what a score of 7 means.
- The 30s candle store (`df30`) is used as a fallback for nearly every MTF criterion when proper REST-fetched data is unavailable. A system running for less than ~25 minutes post-start will have fewer than 50 30-second candles and will degrade silently (no warning emitted) through all fallback paths.
- For PAXG, only the H4 timeframe is overridden with Gold real data (`df_h4 = df_gold_h4`). The H2, H1, 30m, 15m, and 5m data remain as PAXG/USDT from Binance. This means structural analysis on H2/H1 uses a proxy asset instead of true XAU/USD structure — a meaningful discrepancy when PAXG diverges from spot gold.

**Recommendation**:
- Standardise score labelling: pick one label (`/11`) and use it uniformly across all log lines, comments, and docstrings.
- For PAXG: extend Gold real data injection to H2 and H1 at minimum (fetch corresponding intervals from Twelve Data / Yahoo).
- Add an explicit warm-up guard: refuse to emit signals for the first N seconds after startup (e.g., `WARMUP_SECONDS = 120`) when fewer than 50 30-second candles are available.

---

### 7. TRIX Signal (STRICT Indicator)

**Status: WARN**
**Location**: `strict_trix_apply()` — line ~3525; `strict_trix_backtest_sharpe()` — line ~3554; `_compute_strict_zones_for_symbol()` — line ~3813

**What it does**:
Implements a TRIX oscillator (Rate-of-Change of triple EMA) with a signal line. The entry condition is TRIX histogram crossing above zero while price is above a long-period trend MA. Walk-forward optimisation uses random search (300 iterations) across TRIX length (5–51), signal length (5–51), and trend MA length (100–800). Results are evaluated on robustness across sub-periods (30-day windows), with a Sharpe floor of 0.30. Four fallback modes (strict → relaxed → ultra-relaxed → best-effort) ensure a parameter set is always produced.

**Finding**:
- **Long-only backtest**: `strict_trix_backtest_sharpe()` only evaluates long entries (`entry_long`, `exit_long`). Short-side performance (which would use `exit_long` as entry and re-entry of `entry_long` as exit) is never backtested. In crypto bear markets (2022, early 2024), a long-only STRICT backtest will produce very poor Sharpe ratios, causing the system to fall back through all four modes until it reaches "best_effort" — which accepts any Sharpe > 0. The final `strict_params` loaded into scoring are optimised only for long, yet the signal is used for both LONG and SHORT directions in `score_setup()` lines ~1826–1831.
- The random search with 300 iterations over a grid of 47 × 47 = 2,209 trix_len × signal_len combinations (plus 8 trend_MA options) covers 300/17,672 ≈ 1.7% of the parameter space per recalibration. The Gaussian blur and zone-picking are sound practices to handle this sparsity, but 1.7% coverage means many good configurations are never evaluated. The fixed seed (`np.random.default_rng(42)`) means every recalibration visits the same 300 parameter sets — there is no exploration benefit from repeated runs.
- The `STRICT_RECALIB_DAYS` parameter defaults to 120 days, but `STRICT_IN_SAMPLE_DAYS` also defaults to 120 days. This means every recalibration retrains on the same fixed-length window rather than an expanding window. Effectively, the walk-forward is not a genuine walk-forward; it is a rolling-window optimisation, which is acceptable but should be documented as such.
- The fallback modes silently lower quality standards (`floor_relaxed = STRICT_SHARPE_FLOOR - 0.2`, `floor_ultra = 0.0`). There is no way for the caller to know which mode was used, beyond inspecting `_strict_store[sym]['mode']`. The scoring in `score_setup()` does not adjust TRIX signal weight based on which fallback mode was activated.

**Recommendation**:
- Add short-side backtesting: when `exit_long` fires, consider this a short entry and simulate short trades until `entry_long` re-fires.
- Randomise the seed per recalibration (`np.random.default_rng(int(time.time()))`) to provide genuine exploration across runs.
- In `score_setup()`, reduce the TRIX weight when `_strict_store[sym]['mode']` is `'best_effort'` or `'ultra_relaxed'` to reduce reliance on low-confidence parameters.

---

### 8. Delta Volume

**Status: PASS**
**Location**: `_update_delta_vol()` — line ~3473; scoring in `score_setup()` — line ~1882

**What it does**:
Maintains a rolling deque of the last `DELTA_VOL_WINDOW` (default 100) aggTrade events per symbol. Each event records quantity and whether the buyer was the maker (seller-aggressive) or not (buyer-aggressive). Computes `buy_vol`, `sell_vol`, `delta`, and `delta_pct` = buy_vol / total. Signals BULLISH when `delta_pct >= 0.60`, BEARISH when `delta_pct <= 0.40`. The scoring criterion checks freshness (data < 2 minutes old) before using the signal.

**Finding**:
- The aggTrade stream correctly uses `is_buyer_maker` to distinguish aggressive buyers from aggressive sellers. The interpretation is correct: `is_buyer_maker=True` means the sell order was the taker = aggressive sell.
- The freshness check (`(now - dv_ts) < 120`) prevents stale data from influencing the score during WS disconnections.
- The rolling window of 100 trades is well-suited for 5-minute timeframes on liquid pairs (BTC, ETH). For PAXG/USDT, which is considerably less liquid, 100 trades may span 30–60 minutes, making `delta_pct` a lagging indicator of pressure rather than a real-time signal.
- The `delta_pct` threshold (60% / 40%) is reasonable and configurable.
- Delta Volume is correctly gated: only credited if `DELTA_VOL_ENABLED=1` AND the signal aligns with the trade direction.

**No critical issues found. Minor note: PAXG liquidity consideration noted above but not a FAIL.**

---

### 9. EMA200 Bias

**Status: PASS**
**Location**: `compute_ema200()` — line ~1310; applied in `score_setup()` — lines ~1722–1726 (H4) and ~1864–1879 (1D)

**What it does**:
Calculates the EMA200 using `pandas_ta`-style exponential weighting (`ewm(span=200, adjust=False)`). For criterion 1 (H4), the trade direction is set by whether the H4 close is above or below EMA200. This direction governs ALL subsequent criteria — the entire score is conditional on this initial bias. For criterion 6 (1D), the daily close vs EMA200(1D) is checked as an independent confirmation point.

**Finding**:
- The `adjust=False` parameter on `ewm()` uses the recursive formula (same as most charting platforms), ensuring consistency with external EMA200 calculations.
- A minimum of 5 H4 candles is enforced before scoring (`if len(df_h4) < 5: return 0, "N/A", [], {}`). EMA200 requires 200+ candles for a valid reading. With `H4_LIMIT=210` (line ~401), a fresh fetch will have at most 210 candles, providing a barely-valid EMA200. After startup warmup, the fetch provides 210 bars which gives approximately 7 periods of EMA200 "memory loading" — this is sufficient but tight.
- The direction is set exclusively by the H4 close vs EMA200. There is no structure confirmation (a close can be 0.001% above EMA200 and still generate a LONG bias). This single-candle proximity without displacement confirmation means the direction can flip back and forth during consolidation near EMA200. A displacement threshold (e.g., close must be > 0.1% above/below EMA200) would reduce whipsaw.
- The 1D EMA200 correctly uses 50 candles as the minimum (`len(df_1d) >= 50`), which is a sensible lower bound for computing a meaningful daily EMA.

**No critical issues found. A displacement guard on the H4 EMA200 direction would reduce noise but is not a fail.**

---

### 10. SL/TP Level Computation

**Status: FAIL**
**Location**: `compute_adaptive_levels()` — line ~2463; PAXG overrides — lines ~258–275; floor SL logic — lines ~4596–4614

**What it does**:
Computes SL and 3 TPs using ATR clamped between the 20th and 80th percentile of a rolling-30 window of the historical ATR column. Adjusts entry price by Binance fee (4 bps). SL = adjusted entry ± ATR × `atr_mult`. TPs = entry + R × ratios where R = SL distance. A 4th TP is appended to complete the array. For PAXG, a floor SL percentage (`sl_floor_pct = 0.0025`) prevents micro-SLs.

**Finding**:
- **Critical: ATR clamping uses `hist_atr.quantile(0.2)` as the lower bound and `hist_atr.quantile(0.8)` as the upper bound on the rolling mean of ATR, not on ATR itself.** Specifically, `hist_atr = lookback_df["atr"].rolling(30).mean().dropna()`. This is the quantile of rolling-mean-ATR values, not instantaneous ATR values. This means the clamp range is narrower than it should be (rolling means compress variance), and the clamping does not protect against extreme single-candle ATR spikes. A flash-crash ATR spike will be partially smoothed by the rolling mean before being further clamped — but a sudden ATR collapse to near-zero (e.g., exchange halt) will produce a floor at the 20th percentile of the smooth series, which may still be near-zero.
- **The `compute_atr_levels()` function (line ~2519) is called to compute `entry, _sl_base, _tps_base` in `scan_loop()` (line ~4534), but the resulting SL/TPs are IMMEDIATELY DISCARDED** and replaced by `compute_adaptive_levels()` output (lines ~4587–4594). The swing-based SL from `compute_atr_levels()` (which uses the 60-bar swing low/high as the SL anchor) is never used. This makes `compute_atr_levels()` a dead computation path in the main signal flow — it consumes CPU for OB/FVG TP calculation and entry price determination only. The actual SL in the signal is always ATR-based, never swing-based.
- **TP completion logic (lines ~4609–4614)**: when `len(tps) < 4`, additional TPs are appended using `_r = max(abs(entry - sl), _atr_val * 0.5)` with incrementing multipliers 1, 2, 3, 4. However, `_n = len(tps) + 1` starts at 4 for the 4th TP (since 3 TPs are already present). The multiplier `_n` equals 4 but `_r` is the full risk distance, so TP4 = entry + 4×R which is a very aggressive target with no historical basis. This TP4 will almost never be hit.
- **For the backtest optimizer `_backtest_strategy_real()`**: the backtest only tests against TP1 as the exit target (line ~4082 comment "Sortie : premier TP touché (TP1)"). TP2, TP3, TP4 are not simulated. This means the optimiser's performance metrics (sharpe, expectancy, winrate) measure a strategy that always exits at TP1, which does not reflect real usage where partial exits at TP1, TP2, TP3 could be applied.
- **PAXG floor SL**: the logic at line ~4597 checks `if abs(entry - sl) < _sl_min_dist` and widens the SL. But the recalculation of TPs uses `_tp_ratios` from `get_sym_override()` — this is correct. However, there is no corresponding floor for TPs (a minimum TP1 distance from entry), so a scenario where ATR is very small could produce TP1 nearly coinciding with entry even after SL widening.

**Recommendation**:
- Fix ATR clamping: apply `np.clip(atr, np.percentile(raw_atr_values, 20), np.percentile(raw_atr_values, 80))` on the raw ATR series, not on its rolling mean.
- Either restore swing-based SL from `compute_atr_levels()` as the primary SL anchor (with ATR as a minimum distance buffer), or remove the dead code path to eliminate the unnecessary computation.
- Cap TP4 at a maximum of 3× R above TP3 to prevent unreachable targets.
- Extend the backtest to simulate TP1+TP2 partial exit or document clearly that the strategy is TP1-only.

---

## Critical Findings Summary

| # | Component | Severity | One-line Fix |
|---|-----------|----------|--------------|
| 1 | SL/TP — ATR clamping on rolling mean instead of raw ATR | FAIL | Clip `atr` against percentiles of `lookback_df["atr"].dropna().values` directly, not of `.rolling(30).mean()` |
| 2 | SL/TP — `compute_atr_levels()` result discarded silently | FAIL | Remove call to `compute_atr_levels()` or re-integrate its swing SL as a floor on `compute_adaptive_levels()` SL |
| 3 | FVG — No staleness / mitigation filter | WARN | Add a post-scan loop in `_has_ob_or_fvg_alignment()` that marks FVGs as mitigated if subsequent candles fully overlapped the zone |
| 4 | TRIX — Long-only backtest used for both LONG and SHORT scoring | WARN | Add short-side simulation in `strict_trix_backtest_sharpe()` or maintain separate short-side parameter sets |
| 5 | MTF — PAXG H2/H1 structure uses PAXG proxy, not XAU/USD | WARN | Extend `fetch_gold_candles()` calls to H2 and H1 intervals in `scan_loop()` for PAXG |
| 6 | Score labelling inconsistent (`/7`, `/9`, `/11`) | WARN | Standardise all log lines, comments, and docstrings to `/11` |

---

## PAXG/Gold SMC Specifics

**Overall PAXG SMC Quality: WARN**

### RSI Override (lines ~265–267)
RSI thresholds for PAXG are set to 35 (long) / 65 (short) vs 28/72 for crypto. This is appropriate: gold reacts to oversold/overbought conditions earlier than Bitcoin. **PASS.**

### ATR Multiplier / TP Ratios (line ~263)
ATR×1.2 with TP ratios (1.0, 1.5, 2.0) — more conservative than the crypto default (ATR×1.0, TPs 1.2/1.8/2.4). The backtest commentary in the code notes Sharpe -3.679 for best PAXG config, which is negative — meaning the optimizer has not found a profitable configuration for Gold. This is concerning: the system emits PAXG signals using parameters calibrated from a historically unprofitable regime. **WARN.**

### Score Minimum (line ~269)
PAXG requires score ≥ 5 (vs 7 for other symbols). Given that the all-in-all backtest Sharpe is negative, a lower minimum threshold may actually increase the number of losing signals emitted. The comment says "WR 40.3% → manque de confluence → score minimum 5/7 requis" — this references the old 7-point system. With 11 points now possible, a score of 5/11 is a very low bar. **WARN.**

### Gold Data Injection (lines ~4487–4496)
Only the H4 frame is replaced with XAU/USD real data. H2, H1, 30m, 15m remain as PAXG/USDT from Binance. PAXG/USDT can diverge from XAU/USD by 0.3–1.0% during premium/discount cycles, which will cause the 30m and 15m OB/FVG zones to be computed on a different price series than the H4 trend. This cross-asset structural inconsistency means OB/FVG zones may not align with actual Gold price action. **WARN.**

### Liquidity Sweep on Gold (line ~1902)
The sweep detection falls through to `df30` (30-second PAXG candles) when `df_m30` is insufficient. This is a particularly bad degradation for Gold, where 50 × 30 seconds = 25 minutes of history is used to define "institutional liquidity levels" — these are meaningless at that timeframe for an asset with $3,000+ price and ATR of ~$20–50 per 5-minute candle. **WARN.**

### PAXG OPT Configurations (lines ~278–292)
12 configurations covering ATR×(0.8–1.5) with various TP ratios. Compared to 7 configurations for crypto assets. The diversity is appropriate for Gold's different volatility profile. However, all configurations use `trailing: False`, so trailing stop functionality is never tested for Gold — even though Gold's mean-reverting nature might benefit from trailing stops that lock in gains during trend extensions. **PASS** (informational note only).

---

*End of SMC Audit — Titanium Dashboard v10*
