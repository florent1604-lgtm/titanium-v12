# Signal Configuration Audit — Titanium Dashboard v10

**File audited:** `titanium_dashboard_v10.py`
**Audit date:** 2026-03-29
**Auditor:** Signal Config Auditor Agent

---

## Executive Summary

**Config quality score: 5/10**

The codebase has grown organically across 9 versions and shows a split personality: it has a sophisticated adaptive learning layer (Module 4) and per-symbol override system (Module 19), but most signal parameters remain global static constants with no awareness of which asset they are applied to. There are several instances of stale comments, orphaned variables, and contradictions between the documented score scale and the runtime scale.

| Category | Count |
|---|---|
| Static (global constant, no per-pair override) | 14 |
| Adaptive (walk-forward recalibrated) | 3 |
| Per-pair override (SYM_OVERRIDES / MODULE 19) | 7 (PAXG only) |
| Regime-aware (changes behaviour based on ADX) | 2 |

---

## Variable-by-Variable Audit Table

| Variable | Default Value | Static/Adaptive | Per-pair override? | Regime-aware? | Issue | Fix |
|---|---|---|---|---|---|---|
| `RSI_ENTRY_LONG` | 28 | Static | Yes — PAXG overridden to 35 | No | Applied on 5m timeframe only. Tight threshold (28) may never fire during strong trends where RSI stays above 35; effective for RANGE, harmful in TREND. No override for BTC/ETH/SOL. | Make regime-aware: use 28 in RANGE, remove RSI gate in TREND (rely on TRIX instead). Add per-pair .env overrides. |
| `RSI_ENTRY_SHORT` | 72 | Static | Yes — PAXG overridden to 65 | No | Mirror issue to RSI_LONG. In trending bear markets RSI rarely rises to 72, blocking all SHORT signals. | Same fix as LONG. |
| `ADX_TREND_THRESHOLD` | 27.0 | Static | No | By definition | Single global threshold used for all 4 assets. Gold (XAU/USD) has fundamentally different volatility regime — 27 ADX is almost always in range for gold. RANGE regime forces OB-only logic which is correct for gold but the threshold is calibrated on crypto. | Add `PAXG_ADX_THRESHOLD` override in `SYM_OVERRIDES`, value ~20 for gold. |
| `SCORE_MIN_REQUIRED` | 7 | Static | Partially — PAXG: 5, others: **unused** | No | **Critical dead variable.** `SCORE_MIN_REQUIRED=7` is defined at line 460 and printed at startup (line 5744) but is NEVER used as a gate in `scan_loop()`. The actual gate is `_score_min = get_sym_override(sym, "score_min", 0)` which defaults to `0` for BTC/ETH/SOL. This means all scores ≥ 0 are emitted for non-PAXG pairs. The global constant is decorative. | Wire `SCORE_MIN_REQUIRED` into `scan_loop()` as the default for `get_sym_override(sym, "score_min", SCORE_MIN_REQUIRED)`. |
| `TRIX trix_len` (STRICT) | Walk-forward: range 5–51 | Adaptive (per-symbol, recalibrated every `STRICT_RECALIB_DAYS`) | Yes — separate per-symbol store `_strict_store[sym]` | No | One of the few properly adaptive parameters. However, the search space (5–51) is fixed globally; PAXG would benefit from a different range given lower volatility and slower price action. | Add `PAXG_TRIX_LEN_MAX` env var to narrow the search range for gold. |
| `TRIX signal_len` (STRICT) | Walk-forward: range 5–51 | Adaptive | Yes (per-symbol store) | No | Same issue as `trix_len`. | Same fix. |
| `TRIX trend_ma_len` (STRICT) | Walk-forward: one of [100,200,300,400,500,600,700,800] | Adaptive | Yes (per-symbol store) | No | Search space is fixed. For PAXG (mean-reverting), a long trend MA (800) will rarely flip side, making the trend filter permanently bullish or bearish and suppressing entries. | Restrict PAXG trend_ma_len candidates to [100,200,300]. |
| `STRICT_SHARPE_FLOOR` | 0.30 | Static | No | No | Applied uniformly to BTC, ETH, SOL, and PAXG. PAXG backtest historically shows Sharpe around −3.6, which means the STRICT system will fall back to "relaxed" or "ultra_relaxed" mode for gold constantly. The 0.30 floor is calibrated on crypto volatility. | Add `PAXG_STRICT_SHARPE_FLOOR` override, default 0.10. |
| `OB_FVG_ATR_MULT` | 0.750 | Static | No | No | Single multiplier for all assets. ATR on PAXG (gold) in dollar terms is ~$15–50 per 5m candle; the same absolute tolerance applied to BTC ($300+ ATR) vs PAXG ($25 ATR) creates very different proximity acceptance windows. Fibonacci dynamic mode partially mitigates this but the fallback is still ATR × 0.75 globally. | Add `PAXG_OB_FVG_ATR_MULT` override, consider 0.5 for gold which has tighter OBs. |
| `OB_FVG_PCT_FALLBACK` | 0.004 (0.4%) | Static | No | No | 0.4% fallback tolerance used when `OB_FVG_FIB_DYNAMIC=0` or no swing detected. Identical for BTC ($400 tolerance at $100k) and PAXG ($12 tolerance at $3000). Proportionally 33× too loose for PAXG. | Add `PAXG_OB_FVG_PCT_FALLBACK=0.002` in `SYM_OVERRIDES`. |
| `FIB_SWING_LOOKBACK` | 60 candles | Static | No | No | 60 candles on 5m = 5 hours. For gold with daily macro drivers, this is too short to capture meaningful swings. For BTC in high-volatility regimes, 5 hours is reasonable. | PAXG override to 120 candles (10 hours). |
| `LIQUIDITY_LOOKBACK` | 50 candles | Static | No | No | 50 × 30m = 25 hours for liquidity sweep context. Crypto vs. gold have very different sweep patterns — gold sweeps tend to be more gradual over multiple sessions. Same value for all. | Add PAXG override to 80 candles. |
| `DELTA_VOL_SIGNAL_PCT` | 0.60 (60%) | Static | No | No | 60% buy/sell dominance to qualify delta volume signal. For PAXG, this data comes from PAXG/USDT Binance spot trades (a thin proxy market with low liquidity), not from real gold futures flow. The signal is near-meaningless for PAXG yet still scores a point. | Disable `DELTA_VOL` criterion for PAXG by setting its weight to 0 in initial `scoring_weights`, or exclude in Module 19. |
| `LEARNING_ADAPT_RATE` | 0.05 | Static | No | No | Single adaptation speed for all assets. With only 10 minimum signals (LEARNING_MIN_SIGNALS), a 5% adaptation per cycle converges in ~20 signals. PAXG generates far fewer signals (lower score rate), so weights stagnate. BTC may adapt too quickly if signal frequency is high (overfitting to recent regime). | Per-pair adapt rate: PAXG=0.02 (slower, fewer signals), BTC/SOL=0.05. |
| `LEARNING_MIN_SIGNALS` | 10 | Static | No | No | 10 signals minimum before adapting weights. For PAXG (effectively filtered at score≥5) the real number of qualified signals will be small; 10 may never be reached, meaning weights stay at 1.0 forever for PAXG. | PAXG override: 5. |
| `MAX_DD_MULTIPLIER` | 1.3 | Static | No | No | Circuit breaker fires if live DD > backtest DD × 1.3. PAXG backtest DD is documented as −3.679 Sharpe equivalent. The base `max_drawdown` stored in `_best_results_2025` for PAXG will be very negative, making `allowed_dd = allowed_base × 1.3` extremely permissive (the multiplier amplifies an already large negative value in the wrong direction — it relaxes the limit further). The circuit breaker will never fire for PAXG. | Per-pair multiplier, or special-case assets with negative base Sharpe (don't apply CB when backtest itself is bad). |
| `ATR gate threshold` | 0.0005 (0.05%) | Static (hardcoded) | No | No | Hardcoded in `score_setup()` at line 1714 — not an env variable. PAXG/gold 5m ATR is typically 0.15–0.3% of price, well above 0.05%, so this gate never fires for gold. For crypto in dead hours (off-market UTC midnight), BTC ATR can drop to 0.04–0.06%, where this correctly suppresses signals. However, the threshold is not configurable via .env. | Extract to `ATR_GATE_PCT = float(os.getenv("ATR_GATE_PCT", "0.0005"))`. |
| `Supertrend length/multiplier` | length=10, multiplier=3.0 | Static (hardcoded) | No | No | Hardcoded in `compute_supertrend()` at line 2922 — not configurable via .env. Supertrend is informational-only in this codebase (not part of scoring) so impact is lower, but it is displayed on the dashboard for PAXG where these crypto-tuned parameters are suboptimal. | Expose `ST_LENGTH` and `ST_MULTIPLIER` as env vars. |

---

## Dead Zone Analysis

### Dead Zone 1 — SCORE_MIN_REQUIRED is never enforced for BTC/ETH/SOL

**Mechanism:** `SCORE_MIN_REQUIRED=7` is defined globally. In `scan_loop()`, the actual threshold used is:
```python
_score_min = get_sym_override(sym, "score_min", 0)
```
For BTC, ETH, SOL there is no entry in `SYM_OVERRIDES`, so `default=0` is returned. Every signal with score ≥ 1 is emitted and recorded. The published SCORE_MIN_REQUIRED=7 is dead code. **All weak 1–6 score signals are emitted for non-PAXG pairs.**

### Dead Zone 2 — RSI fallback + TRIX strict: mutual exclusion may prevent both from firing

**Mechanism:** `entry_signal` (TRIX/RSI gate) requires either:
- TRIX: strict_params loaded + cross-up + in-trend + side alignment, OR
- RSI fallback: `poi_ok=True` (ob_fvg_ok OR rejection_ok) AND RSI5m ≤ 28 AND RSI10m ≤ 33

In a TREND regime (ADX > 27), if the market is trending strongly:
- RSI5m on 5m will rarely be ≤ 28 (momentum stays elevated)
- STRICT TRIX may not have been calibrated yet (first run takes ~15 minutes)

Result: Score criterion 5 (TRIX_5M) **never fires** at the start of a trending session before STRICT calibration completes, and RSI is too tight to fill in. A strong trending setup can only score 4/11 maximum in the first 15 minutes after startup (missing EMA200_1D if bias is bearish, TRIX_5M, LIQ_SWEEP not built yet). Signal threshold of 7 means **no signals emit for ~15 minutes after startup**.

### Dead Zone 3 — EMA200_1D silently disabled when USE_1D_BIAS=0

**Mechanism:** `USE_1D_BIAS = os.getenv("USE_1D_BIAS", "1")`. If set to 0 in .env, the daily bias criterion is silently skipped and the score max effectively drops to 10/11. The `score_max: 11` field in the signal payload stays at 11, misrepresenting the actual achievable score. A score of 9/11 with USE_1D_BIAS=0 is the same as 9/10 — the percentage threshold SCORE_MIN_REQUIRED=7 maps to 64% but is really 70%.

### Dead Zone 4 — DELTA_VOL stale data (2-minute freshness gate)

**Mechanism:** In `score_setup()` at line 1889: `dv_fresh = (datetime.now(...) - dv_ts) < 120` — delta vol is only used if < 2 minutes old. If the Binance aggTrade WS is disconnected or reconnecting, `DELTA_VOL` criterion fires 0 points. Combined with `SCORE_MIN_REQUIRED=7` (if enforced), this creates a gap: a perfectly valid 6-point setup that normally scores 7 via DELTA_VOL will stop emitting signals during WS outages.

### Dead Zone 5 — PAXG score_min=5 vs score system out of 11

**Mechanism:** The PAXG comment at line 252 says "score minimum 5/7 requis" but the system scores /11. A PAXG threshold of 5/11 (45%) is extremely permissive compared to the intended 5/7 (71%). This is a version drift from the v7 → v8 upgrade that added 2 new criteria but did not update the PAXG score_min.

---

## Cross-pair Consistency

| Parameter | BTC/USDT | ETH/USDT | SOL/USDT | PAXG/USDT | Should differ? | Issue |
|---|---|---|---|---|---|---|
| RSI thresholds | 28/72 | 28/72 | 28/72 | 35/65 ✓ | Yes — PAXG correct | BTC/ETH/SOL share identical RSI, which is acceptable. SOL is more volatile and may warrant wider thresholds (25/75) but is not critical. |
| SL ATR multiplier | 1.0 | 1.0 | 1.0 | 1.2 ✓ | Yes | PAXG has override. SOL is highly volatile; atr_mult=1.0 may be too tight during volatile sessions. |
| TP ratios | (1.2,1.8,2.4) | (1.2,1.8,2.4) | (1.2,1.8,2.4) | (1.0,1.5,2.0) ✓ | Yes | PAXG has smaller TPs, correct for mean-reverting gold. |
| score_min | 0 (effectively) | 0 (effectively) | 0 (effectively) | 5 | Yes | BTC/ETH/SOL should have score_min=7 wired to SCORE_MIN_REQUIRED. |
| TRIX params | Walk-forward | Walk-forward | Walk-forward | Walk-forward | Yes | Same search space for all. PAXG benefits from a constrained space. |
| Futures data | Enabled ✓ | Enabled ✓ | Enabled ✓ | Not in FUTURES_SYMBOLS_MAP | Correct — gold has no perp | PAXG is correctly excluded from futures fetch. |
| Delta vol criterion | Binance spot data | Binance spot data | Binance spot data | PAXG/USDT spot (proxy) | PAXG should be disabled | PAXG delta vol is from a thin proxy market (PAXG/USDT on Binance) not real gold flow. The signal is noise for gold. The EMA200 and structure criteria correctly use real XAU/USD data (overridden via `fetch_gold_candles`), but delta vol still uses PAXG spot trades. |
| Gold H4 data | Binance OHLCV | Binance OHLCV | Binance OHLCV | XAU/USD (Twelve Data / Yahoo) ✓ | Correct — gold override works | The `fetch_gold_candles()` pipeline only injects H4 data, not 30m/15m/5m. All OB/FVG lookback on sub-hourly TFs for PAXG still uses Binance PAXG/USDT klines, not real gold data. EMA200_H4 uses real gold, but OB/FVG scoring uses PAXG proxy. |
| ADX threshold | 27.0 | 27.0 | 27.0 | 27.0 | Yes | Gold trends at lower ADX values due to slower price action. 27 is calibrated on crypto. |
| LIQUIDITY_LOOKBACK | 50 | 50 | 50 | 50 | Yes | Gold sweeps are slower and benefit from deeper lookback. |

### Key cross-pair bug: Gold sub-hourly data is still PAXG proxy

When `GOLD_REAL_ENABLED=1`, only the H4 candles are replaced with real XAU/USD data. The 30m, 15m, 5m timeframes used for OB/FVG scoring still come from Binance PAXG/USDT klines via `get_m30_cached`, `get_m15_cached`, `get_m5_cached`. This means:
- Criterion 3 (OB/FVG 30m) is evaluated on PAXG spot, not gold
- Criterion 4 (OB/FVG 15m confirm) is evaluated on PAXG spot, not gold
- Criterion 5 (TRIX/RSI 5m) is evaluated on PAXG spot, not gold
- Only criteria 1 (EMA200 H4) and 6 (EMA200 1D) use real gold

This is a significant data consistency issue for PAXG scoring.

---

## Regime Awareness Gaps

The following parameters change signal behaviour but are NOT currently regime-aware (i.e., they do not change their values between TREND and RANGE):

| Parameter | Current behaviour | How TREND/RANGE should affect it | Impact |
|---|---|---|---|
| `RSI_ENTRY_LONG / SHORT` | Fixed threshold regardless of regime | In TREND: disable RSI gate (momentum stays extended); In RANGE: tighten to 25/75 for precision | High — RSI blocks trending signals |
| `OB_FVG_ATR_MULT` (proximity tolerance) | Fixed 0.75 × ATR | In TREND: widen to 1.0× (price approaches OB faster, less precise entry OK); In RANGE: tighten to 0.5× (precision bounce matters more) | Medium |
| `LIQUIDITY_LOOKBACK` | Fixed 50 candles | In TREND: could reduce to 30 (recent sweeps more relevant); In RANGE: keep 50 (wider context needed) | Low-medium |
| `FIB_SWING_LOOKBACK` | Fixed 60 candles | In RANGE: extend to 100+ (swings are wider and take longer to develop) | Medium |
| `STRICT_SHARPE_FLOOR` | Fixed 0.30 | In sustained TREND periods: relax to 0.20 (TRIX performs better in trends, lower Sharpe still valid); In RANGE: tighten to 0.40 (need higher bar for noisy ranging conditions) | Medium |
| `LEARNING_ADAPT_RATE` | Fixed 0.05 | In RANGE: increase to 0.10 (faster adaptation to changing OB/FVG performance); In TREND: reduce to 0.02 (regime is stable, avoid over-weighting recent data) | Medium |
| Score weighting for `OB_FVG_30M` vs `TRIX_5M` | Both weight 1.0 regardless of regime | In TREND: TRIX should dominate (weight 1.5); In RANGE: OB/FVG should dominate (weight 1.5) | High |

Note: `ADX_REGIME` criterion (criteria 9) partially addresses regime awareness by granting +1 point for trend continuation (FVG) or range bounce (OB intact). However, the other 10 parameters above do not adapt, meaning a RANGE regime detected by ADX only adds 1 point of bonus but does not change any of the underlying detection thresholds.

---

## Recommendations (ranked by impact)

### 1. [CRITICAL] Wire SCORE_MIN_REQUIRED into scan_loop for non-PAXG pairs

**File:** `scan_loop()`, line 4561
**Change:** Replace `get_sym_override(sym, "score_min", 0)` with `get_sym_override(sym, "score_min", SCORE_MIN_REQUIRED)`.

Currently BTC/ETH/SOL emit signals at score ≥ 1. Every scan cycle produces a "signal" regardless of confluence quality. This floods `signal_history` with low-quality entries and degrades the learning system's ability to adapt weights meaningfully (Module 4 computes win rates on all historical signals including 1/11 noise).

**Expected impact:** Eliminates ~40-60% of low-quality signals for BTC/ETH/SOL, improving learning system accuracy.

---

### 2. [HIGH] Fix PAXG score_min to reflect /11 scale (not /7)

**File:** `SYM_OVERRIDES["PAXG/USDT"]["score_min"]`, line 269
**Change:** Update comment and value. The old comment says "5/7 requis" but the system is /11. The intended 71% bar maps to 8/11. Consider setting `PAXG_SCORE_MIN=6` (conservative) or `PAXG_SCORE_MIN=7` (matching global threshold).

---

### 3. [HIGH] Disable DELTA_VOL criterion for PAXG

**File:** `scoring_weights` initialization or `SYM_OVERRIDES`
**Change:** Add `"delta_vol_weight": 0.0` for PAXG, or short-circuit the criterion in `score_setup()` when `sym` is in GOLD_SYMBOL_MAP. The PAXG/USDT aggTrade stream is not a proxy for real gold flow and injects noise into the score.

---

### 4. [HIGH] Inject real gold data for sub-hourly timeframes (30m, 15m, 5m)

**File:** `scan_loop()`, lines 4486-4497
**Change:** Currently only H4 is overridden with real gold data. Extend the gold fetch to 30m, 15m, 5m intervals and inject into `df_m30`, `df_m15`, `df_5m` for PAXG. This ensures OB/FVG scoring is based on real XAU/USD candles. This requires `fetch_gold_candles()` to be called for each required interval.

**Expected impact:** All 11 scoring criteria for PAXG will use coherent real gold data instead of a mix.

---

### 5. [HIGH] Make RSI gate regime-aware

**File:** `score_setup()`, lines 1836-1859
**Change:** Wrap RSI gate in a regime check. If `adx_regime == "TREND"`, skip RSI requirement and rely on TRIX alone. If `adx_regime == "RANGE"`, apply RSI gate normally (or even tighten to 25/75).

```python
# Pseudocode:
if adx_regime == "TREND":
    entry_signal = True  # momentum is directional, skip RSI
elif adx_regime == "RANGE":
    # apply tighter RSI: 25/75 instead of 28/72
```

---

### 6. [MEDIUM] Add PAXG-specific ADX threshold override

**File:** `SYM_OVERRIDES["PAXG/USDT"]`
**Change:** Add `"adx_threshold": 20.0` and read it in `TitaniumOptimizerV8.get_market_regime()`. Gold rarely exceeds ADX 27; using 20 properly classifies trending vs. ranging gold sessions.

---

### 7. [MEDIUM] Extract hardcoded ATR gate to .env variable

**File:** `score_setup()`, line 1714
**Change:** Replace `0.0005` with `ATR_GATE_PCT = float(os.getenv("ATR_GATE_PCT", "0.0005"))`. Currently the ATR minimum volatility gate is not configurable, preventing tuning without code changes.

---

### 8. [MEDIUM] Fix version drift in score_max references

Multiple places still reference score /9 or /7 in comments, log strings, and the Ollama vision context builder:
- Line 1208: `score_max = int(algo_context.get("score_max", 9))` — default 9 is wrong (should be 11)
- Line 1639: Docstring says "max 9" but runtime caps at 11
- Line 4757: `logger.info("[SIGNAL] %s score=%s/7 ..."` — log says /7 but score is /11
- `TELEGRAM_SCORE_LABELS` (line 343): labels only cover /9 scale (max label is `9: "🌟 Setup parfait"`) but score can reach 11

Update all references to consistently use /11.

---

### 9. [MEDIUM] Per-pair LEARNING_ADAPT_RATE

**File:** `SYM_OVERRIDES` and `_compute_learning_report()`
**Change:** Add `"adapt_rate"` to `SYM_OVERRIDES` for PAXG (value 0.02), read in `_compute_learning_report()` instead of global `LEARNING_ADAPT_RATE`.

---

### 10. [LOW] Expose Supertrend parameters to .env

**File:** `compute_supertrend()`, line 2922
**Change:** `ta.supertrend(..., length=10, multiplier=3.0)` — add `ST_LENGTH = int(os.getenv("ST_LENGTH","10"))` and `ST_MULTIPLIER = float(os.getenv("ST_MULTIPLIER","3.0"))`. Supertrend is informational only but dashboard users tune it visually.

---

### 11. [LOW] Consider BTC/SOL volatility differentiation

SOL has 3–5× higher relative volatility than BTC. Current identical RSI/ATR/TP parameters for both are acceptable as a starting point, but after sufficient signal history accumulates, Module 4 adaptive weights will handle this automatically. No immediate code change required — ensure LEARNING_MIN_SIGNALS is reached and `scoring_weights.json` is persisting correctly.

---

## Config Variables Reference Summary

```
# Core Signal Thresholds
RSI_ENTRY_LONG=28           # [STATIC] Global, PAXG→35 override
RSI_ENTRY_SHORT=72          # [STATIC] Global, PAXG→65 override
ADX_TREND_THRESHOLD=27.0    # [STATIC] Global, no PAXG override (BUG)
SCORE_MIN_REQUIRED=7        # [ORPHANED] Defined but not used as gate for BTC/ETH/SOL
DELTA_VOL_SIGNAL_PCT=0.60   # [STATIC] Global, no PAXG exclusion (BUG)

# OB/FVG Detection
OB_FVG_ATR_MULT=0.750       # [STATIC] Global proximity tolerance multiplier
OB_FVG_PCT_FALLBACK=0.004   # [STATIC] Fallback 0.4% tolerance
OB_FVG_FIB_DYNAMIC=1        # [STATIC] Enable Fibonacci dynamic tolerance
FIB_LEVEL_LOW=0.618         # [STATIC] Fixed Fib level
FIB_LEVEL_HIGH=0.786        # [STATIC] Fixed Fib level
FIB_SWING_LOOKBACK=60       # [STATIC] Global, no PAXG override

# Liquidity Sweep
LIQUIDITY_LOOKBACK=50       # [STATIC] Global candles for stop hunt context
# Hardcoded 0.3% confirmation margin — not in .env

# EMA Periods
# EMA200 (H4, 1D): span=200 — hardcoded, not configurable
# EMA20 (30s): length=20 — hardcoded, not configurable

# SL/TP (PAXG overrides exist, BTC/ETH/SOL use defaults)
atr_mult (default)=1.0      # [STATIC for BTC/ETH/SOL]
tp_ratios (default)=(1.2,1.8,2.4) # [STATIC for BTC/ETH/SOL]
PAXG: atr_mult=1.2, tp_ratios=(1.0,1.5,2.0), sl_floor_pct=0.0025

# Adaptive Learning
LEARNING_ADAPT_RATE=0.05    # [STATIC] Global, no per-pair override
LEARNING_MIN_SIGNALS=10     # [STATIC] Global

# STRICT TRIX (walk-forward adaptive, per-symbol)
STRICT_RECALIB_DAYS=120     # [STATIC] Recalibration period
STRICT_IN_SAMPLE_DAYS=120   # [STATIC] Training window
STRICT_RANDOM_ITERS=300     # [STATIC] Search iterations
STRICT_SHARPE_FLOOR=0.30    # [STATIC] No PAXG override (BUG)
STRICT_MIN_TRADES=3         # [STATIC] Min trades per subperiod

# Circuit Breaker
MAX_DD_MULTIPLIER=1.3       # [STATIC] Effectively disabled for PAXG (BUG)
CB_CHECK_INTERVAL=3600      # [STATIC]
```
