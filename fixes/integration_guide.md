# Integration Guide — SMC Audit Fixes for titanium_dashboard_v10.py
## Fix Files: smc_corrections.py · new_reversal_patterns.py · config_adaptive_patch.py · scoring_update.py

---

## Priority Order

| Priority | Fix | File | Impact |
|----------|-----|------|--------|
| CRITICAL | Liquidity sweep ATR margin | smc_corrections.py | False positives on BTC/SOL |
| CRITICAL | TELEGRAM_SCORE_THRESHOLD scale | config_adaptive_patch.py | Alert spam on /11 scale |
| CRITICAL | Annualised Sharpe formula | scoring_update.py | Backtest rank bias |
| HIGH | MIN_DF30_FOR_SCAN 3→10 | config_adaptive_patch.py | Garbage signals on startup |
| HIGH | STRICT_SHARPE_FLOOR 0.30→0.50 | config_adaptive_patch.py | Over-optimistic calibration |
| HIGH | BTC/ETH/SOL SYM_OVERRIDES | config_adaptive_patch.py | All symbols use PAXG params |
| HIGH | Sweep + Displacement pattern | smc_corrections.py | Missing displacement confirm |
| HIGH | Inducement→Sweep→CHoCH | new_reversal_patterns.py | Missing top-priority pattern |
| MEDIUM | Breaker Block detection | smc_corrections.py | S/R flip not tracked |
| MEDIUM | Failed Auction detection | smc_corrections.py | POI rejection undetected |
| MEDIUM | RSI Divergence at OB | new_reversal_patterns.py | Missing momentum confirmation |
| MEDIUM | OPT_CONFIGURATIONS 7→15 | scoring_update.py | Under-explored parameter space |
| MEDIUM | Walk-forward split | scoring_update.py | No OOS validation |
| MEDIUM | Profit factor metric | scoring_update.py | Missing key performance stat |
| LOW | Reversal confidence bonus | scoring_update.py | Score bonus for strong setups |
| LOW | Delta vol freshness tiered | config_adaptive_patch.py | Uniform 120s freshness limit |
| LOW | Regime-aware RSI bounds | config_adaptive_patch.py | RSI thresholds not regime-adjusted |

---

## Checklist

- [ ] **A.** Fix TELEGRAM_SCORE_THRESHOLD (line 341)
- [ ] **B.** Fix MIN_DF30_FOR_SCAN (line 214)
- [ ] **C.** Fix STRICT_SHARPE_FLOOR (line 428)
- [ ] **D.** Extend SYM_OVERRIDES with BTC/ETH/SOL (lines 258–275)
- [ ] **E.** Replace Sharpe formula in _backtest_strategy_real (line 2146)
- [ ] **F.** Replace Sharpe formula in strict_trix_backtest_sharpe (line 3587)
- [ ] **G.** Replace OPT_CONFIGURATIONS with 15-config set (lines 321–329)
- [ ] **H.** Replace detect_liquidity_sweep call in score_setup (line 1904)
- [ ] **I.** Add imports at top of file
- [ ] **J** (optional): Integrate reversal patterns into score_setup
- [ ] **K** (optional): Replace delta vol freshness gate (line 1888)
- [ ] **L** (optional): Add profit factor to _backtest_strategy_real output

---

## FILE 1: smc_corrections.py

### What it fixes
- **Liquidity sweep margin** fixed from hard-coded 0.3% to ATR-based dynamic margin.  Prevents false positives on BTC (where ATR can be $500 but 0.3% = $300, causing under-detection) and PAXG (where 0.3% is appropriate but arbitrary).
- **Sweep + Displacement** adds the institutional confirmation step missing from the original: the candle immediately after the sweep must show a strong displacement body (> 0.75×ATR14).
- **Breaker Blocks** adds S/R flip tracking for broken OBs — a standard SMC concept entirely absent from v10.
- **Failed Auction** adds the POI entry + sharp reversal detection pattern.

### Integration: detect_liquidity_sweep_v2 (CRITICAL)

**Where:** `score_setup()` function, Criterion 8 block — lines **1899–1907**

**Current code (~line 1903–1904):**
```python
if _df_liq is not None and len(_df_liq) >= LIQUIDITY_LOOKBACK + 5:
    liq_sweep_ok = TitaniumOptimizerV8.detect_liquidity_sweep(_df_liq, side)
```

**Replace with:**
```python
if _df_liq is not None and len(_df_liq) >= LIQUIDITY_LOOKBACK + 5:
    _sweep_result = detect_liquidity_sweep_v2(_df_liq, side, lookback=LIQUIDITY_LOOKBACK)
    liq_sweep_ok = bool(_sweep_result.get("detected", False))
```

**Add import** at top of file (after the existing imports block, around line 76):
```python
from fixes.smc_corrections import (
    detect_liquidity_sweep_v2,
    detect_sweep_with_displacement,
    detect_breaker_blocks,
    detect_failed_auction,
)
```

Or copy the functions directly into the file body (after line 697, before `_load_learning_state`).

### Integration: detect_breaker_blocks (MEDIUM)

**Where:** After `detect_ob()` call in the main scan loop (~line 4532)

**Current code (~line 4531–4532):**
```python
fvgs = detect_fvg(df30)
obs = detect_ob(df30, side)
```

**Add after:**
```python
# Breaker block detection (broken OBs acting as S/R)
breaker_blocks = detect_breaker_blocks(df30, obs, side, lookback=100)
```

Then add `breaker_blocks` to the signal dict where `obs` and `fvgs` are assembled.

### Integration: detect_failed_auction (MEDIUM)

**Where:** After OB/FVG detection, using the first active OB as the POI.

**Add after breaker_blocks (~line 4533):**
```python
# Failed auction at nearest OB zone
_active_obs = [ob for ob in obs if ob.get("status") == "intact"]
if _active_obs:
    _nearest_ob = _active_obs[0]
    failed_auction_result = detect_failed_auction(
        df30, _nearest_ob["top"], _nearest_ob["bot"], side, lookback_after=5
    )
else:
    failed_auction_result = {"auction_failed": False}
```

---

## FILE 2: new_reversal_patterns.py

### What it fixes
- **Inducement → Sweep → CHoCH** — the highest-priority SMC reversal pattern; was entirely missing.  Supports partial matches (2/3 phases = 0.65 confluence score).
- **RSI Divergence at OB** — momentum divergence confirmation at institutional zones; was missing.
- **Reversal Confidence Score** — composite 0–100 score replacing ad-hoc confidence guesses.

### Integration: detect_inducement_sweep_choch (HIGH)

**Where:** Inside `score_setup()` after criterion 9 (ADX regime), before the final return, approximately **lines 1930–1960**.

**Add import** (same block as smc_corrections imports):
```python
from fixes.new_reversal_patterns import (
    detect_inducement_sweep_choch,
    detect_rsi_divergence_at_ob,
    compute_reversal_confidence,
)
```

**Add code in score_setup() after the ADX regime block (~line 1930):**
```python
# ── Optional: Multi-TF Reversal Confluence (Inducement→Sweep→CHoCH) ──────
isc_result = detect_inducement_sweep_choch(
    df_htf=df_h4,
    df_mtf=df_m30 if df_m30 is not None else df_h1,
    df_ltf=df_m5  if df_m5  is not None else df30,
    side=side,
)
algo_context["isc_confluence"] = isc_result.get("confluence_score", 0.0)
algo_context["isc_detected"]   = isc_result.get("detected", False)
```

### Integration: detect_rsi_divergence_at_ob (MEDIUM)

**Where:** Same block, after `isc_result`.

```python
# ── RSI Divergence at nearest OB zone ────────────────────────────────────
_div_result = {"divergence_detected": False, "divergence_type": "none", "strength": 0.0}
_active_obs_for_div = [o for o in getattr(algo_context, "obs", []) if o.get("status") == "intact"]
# Note: obs list must be passed into algo_context earlier (see detect_ob call at ~line 4532)
if _active_obs_for_div and df_m5 is not None:
    _ob0 = _active_obs_for_div[0]
    _div_result = detect_rsi_divergence_at_ob(
        df_m5, float(_ob0["top"]), float(_ob0["bot"]), side, lookback=50
    )
algo_context["rsi_divergence"] = _div_result
```

### Integration: compute_reversal_confidence (MEDIUM → bonus scoring)

**Where:** In the main scan loop after `score_setup()` call (~line 4514), before the `_below_min` check (~line 4561).

```python
# Compute composite reversal confidence
_rc_total, _rc_breakdown = compute_reversal_confidence(
    pattern_results=algo_context.get("isc_confluence_raw", {}),
    ob_status=(obs[0]["status"] if obs else "none"),
    fvg_status=("active" if fvgs else "none"),
    delta_vol_state=delta_state,
    rsi_val=float(algo_context.get("rsi5", 50.0)),
    adx_val=float(algo_context.get("adx", 20.0)),
    side=side,
)
algo_context["reversal_confidence"] = _rc_total
```

---

## FILE 3: config_adaptive_patch.py

### What it fixes
1. **SYM_OVERRIDES** — adds BTC, ETH, SOL per-symbol calibrations (critical: all 3 assets were falling through to global defaults which were calibrated for PAXG).
2. **TELEGRAM_SCORE_THRESHOLD** — fixes a v7→v8 scale migration bug: threshold of 6 on a /11 scale = 54.5% (too low → alert spam).
3. **MIN_DF30_FOR_SCAN** — 3 bars (90s of 30s data) is insufficient for any indicator warmup; minimum should be 10.
4. **STRICT_SHARPE_FLOOR** — 0.30 is near-random in short windows; 0.50 is the minimum "acceptable" threshold in quantitative finance.
5. **get_delta_vol_freshness_limit** — tiered freshness logic (30s/60s/120s by TF).
6. **get_regime_rsi_thresholds** — regime-aware RSI bounds.

### Integration A: SYM_OVERRIDES extension (HIGH — CRITICAL for BTC/ETH/SOL)

**Where:** Line **258** — replace the entire `SYM_OVERRIDES` dict.

**Current code (lines 258–275):**
```python
SYM_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "PAXG/USDT": { ... },
    # Extendable : ajouter BTC/USDT, ETH/USDT, SOL/USDT ici si besoin
}
```

**Replace with** `SYM_OVERRIDES_PATCH` from `config_adaptive_patch.py`.
Copy the entire dict (it includes the original PAXG entry unchanged).

### Integration B: TELEGRAM_SCORE_THRESHOLD (CRITICAL)

**Where:** Line **341**

```python
# BEFORE:
TELEGRAM_SCORE_THRESHOLD = float(os.getenv("TELEGRAM_SCORE_THRESHOLD", "6"))
# Labels de qualité par palier de score /9 (v7)
TELEGRAM_SCORE_LABELS: Dict[int, str] = {
    4: "📡 Surveillance",
    ...
    9: "🌟 Setup parfait",
}
```

```python
# AFTER: (copy from config_adaptive_patch.py)
# [V10-FIX] Scale updated from /9 (v7) to /11 (v8: +LIQ_SWEEP +ADX_REGIME)
# Old threshold 6/9 = 66.7%; new threshold 7/11 = 63.6% (consistent with SCORE_MIN_REQUIRED)
TELEGRAM_SCORE_THRESHOLD = float(os.getenv("TELEGRAM_SCORE_THRESHOLD", "7"))
TELEGRAM_SCORE_LABELS: Dict[int, str] = {
    0:  "⚫ Pas de signal",
    1:  "⚫ Pas de signal",
    2:  "⚫ Pas de signal",
    3:  "🔵 Signal faible",
    4:  "📡 Surveillance",
    5:  "📡 Surveillance",
    6:  "✅ Bon setup",
    7:  "🔥 Setup fort",
    8:  "🚀 Setup optimal",
    9:  "💎 Signal premium",
    10: "🌟 Setup parfait",
    11: "👑 Signal absolu",
}
```

### Integration C: MIN_DF30_FOR_SCAN (HIGH)

**Where:** Line **214**

```python
# BEFORE:
MIN_DF30_FOR_SCAN = int(os.getenv("MIN_DF30_FOR_SCAN", "3"))   # 3 bougies 30s = 90s de warmup

# AFTER:
# [V10-FIX] 10 bars minimum (5 min of 30s data) — 3 was insufficient for ATR/OB warmup
MIN_DF30_FOR_SCAN = int(os.getenv("MIN_DF30_FOR_SCAN", "10"))
```

### Integration D: STRICT_SHARPE_FLOOR (HIGH)

**Where:** Line **428**

```python
# BEFORE:
STRICT_SHARPE_FLOOR = float(os.getenv("STRICT_SHARPE_FLOOR", "0.30"))

# AFTER:
# [V10-FIX] 0.50 floor — 0.30 was near-random in 30-day windows; 0.50 is the
# accepted "acceptable" Sharpe threshold in quantitative finance practice.
STRICT_SHARPE_FLOOR = float(os.getenv("STRICT_SHARPE_FLOOR", "0.50"))
```

**Note:** Also update the `floor_relaxed` calculation at line **3839** to adjust for the new floor:
```python
# BEFORE:
floor_relaxed = max(0.1, float(STRICT_SHARPE_FLOOR) - 0.2)

# AFTER (keeps relaxed mode usable):
floor_relaxed = max(0.1, float(STRICT_SHARPE_FLOOR) - 0.3)
```

### Integration E: get_delta_vol_freshness_limit (LOW)

**Where:** Line **1888** in `score_setup()`.

```python
# BEFORE:
dv_fresh = (datetime.now(timezone.utc).timestamp() - dv_ts) < 120  # données < 2min

# AFTER:
# Import at top: from fixes.config_adaptive_patch import get_delta_vol_freshness_limit
_dv_limit = get_delta_vol_freshness_limit(active_tf or ACTIVE_TF)
dv_fresh = (datetime.now(timezone.utc).timestamp() - dv_ts) < _dv_limit
```

### Integration F: get_regime_rsi_thresholds (LOW)

**Where:** In the main scan loop where RSI overrides are applied (~lines 4511–4512).

```python
# BEFORE:
_rsi_long  = get_sym_override(sym, "rsi_long",  RSI_ENTRY_LONG)
_rsi_short = get_sym_override(sym, "rsi_short", RSI_ENTRY_SHORT)

# AFTER:
# Import: from fixes.config_adaptive_patch import get_regime_rsi_thresholds
_rsi_long_base  = get_sym_override(sym, "rsi_long",  RSI_ENTRY_LONG)
_rsi_short_base = get_sym_override(sym, "rsi_short", RSI_ENTRY_SHORT)
_adx_regime_str = algo_context.get("adx_regime", "UNKNOWN") if 'algo_context' in dir() else "UNKNOWN"
_rsi_long, _rsi_short = get_regime_rsi_thresholds(_adx_regime_str, _rsi_long_base, _rsi_short_base)
```

Note: `algo_context` is only available after `score_setup()` is called.  The regime-aware thresholds apply on the *next* scan cycle after the first score_setup call.  This is acceptable as the regime changes slowly.

---

## FILE 4: scoring_update.py

### What it fixes
1. **Annualised Sharpe** — the existing `mean / std * sqrt(n_trades)` formula is mathematically incorrect (scales by trade count, not time).  The correct formula is `mean / std * sqrt(252 / backtest_days)`.
2. **walk_forward_split** — adds temporal OOS validation (was missing entirely).
3. **compute_profit_factor** — adds a standard performance metric.
4. **OPT_CONFIGURATIONS_EXTENDED** — expands from 7 to 15 configs covering ATR×0.6 and 0.8 (missing scalp tiers).
5. **apply_reversal_confidence_bonus** — integrates reversal pattern quality into the raw score.
6. **get_effective_score_min** — centralises per-symbol score_min logic.

### Integration A: Sharpe formula fix (CRITICAL)

**Location 1:** `_backtest_strategy_real()` — line **2146**

```python
# BEFORE:
sharpe   = mean_pnl / (std_pnl + 1e-12) * (n_trades ** 0.5)

# AFTER:
# Import: from fixes.scoring_update import compute_annualized_sharpe
# backtest_days must be passed to _backtest_strategy_real or computed from df index
_bt_days = max(1, (df.index[-1] - df.index[0]).days) if hasattr(df.index[-1], 'days') else OPT_IN_SAMPLE_DAYS
sharpe = compute_annualized_sharpe(arr_pnl, backtest_days=_bt_days)
```

**Practical approach** (simpler, avoids refactoring df access):
```python
# Estimate backtest_days from the number of 5m candles
# 5m × n_candles → days: n_candles / (288 candles per day on 5m)
_candles_per_day = 288  # 5m TF default
_bt_days_est = max(1, int(len(df) / _candles_per_day))
sharpe = compute_annualized_sharpe(arr_pnl, backtest_days=_bt_days_est)
```

**Location 2:** `strict_trix_backtest_sharpe()` — line **3587**

```python
# BEFORE:
sharpe = mean / (std + 1e-12) * (len(r) ** 0.5)

# AFTER:
_bt_days_strict = max(1, int(len(df) / 288))
sharpe = compute_annualized_sharpe(r, backtest_days=_bt_days_strict)
```

### Integration B: OPT_CONFIGURATIONS (HIGH)

**Where:** Lines **321–329** — replace 7-config list.

```python
# BEFORE:
OPT_CONFIGURATIONS: List[Dict[str, Any]] = [
    {"atr_mult": 0.7,  "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    ... (7 total)
]

# AFTER:
# Import: from fixes.scoring_update import OPT_CONFIGURATIONS_EXTENDED
OPT_CONFIGURATIONS = OPT_CONFIGURATIONS_EXTENDED  # 15 configs (adds ATR×0.6, 0.8 tiers)
```

Or paste the list directly.  **Note:** Also update the startup print at line **5748** which displays `{len(OPT_CONFIGURATIONS)} configs`.

### Integration C: walk_forward_split (MEDIUM)

**Where:** Add to `_run_optimisation_sync()` at line ~**2237**, before the config loop.

```python
# Optional: walk-forward OOS validation
# Import: from fixes.scoring_update import walk_forward_split
try:
    df_train, df_oos = walk_forward_split(df_year, train_ratio=0.7)
except ValueError:
    df_train, df_oos = df_year, None  # fallback: use all data if too few rows

# Run configs on df_train, validate on df_oos
for cfg in configurations:
    res = _backtest_strategy_real(df_train, cfg)
    if df_oos is not None and len(df_oos) >= OPT_MIN_CANDLES // 3:
        res_oos = _backtest_strategy_real(df_oos, cfg)
        res["oos_sharpe"]  = res_oos.get("sharpe", -1e9)
        res["oos_trades"]  = res_oos.get("trades", 0)
    res["_score"] = _opt_score(res)
    all_results.append(res)
```

### Integration D: compute_profit_factor (MEDIUM)

**Where:** In `_backtest_strategy_real()`, after the expectancy calculation (~line **2153**).

```python
# Import: from fixes.scoring_update import compute_profit_factor
profit_factor = compute_profit_factor(arr_pnl)
```

Then add `"profit_factor": float(profit_factor)` to the return dict at ~line **2162**.

### Integration E: apply_reversal_confidence_bonus (LOW)

**Where:** In the main scan loop, after `score_setup()` result and after reversal_confidence is computed (~line 4520+).

```python
# Import: from fixes.scoring_update import apply_reversal_confidence_bonus
_rc = algo_context.get("reversal_confidence", 0.0)
if _rc > 0:
    score = apply_reversal_confidence_bonus(float(score), _rc)
    score = min(11, int(round(score)))  # re-apply cap after bonus
```

### Integration F: get_effective_score_min (LOW)

**Where:** Line **4561** — replace the existing `get_sym_override` call for score_min.

```python
# BEFORE:
_score_min  = get_sym_override(sym, "score_min", 0)

# AFTER:
# Import: from fixes.scoring_update import get_effective_score_min
_score_min = get_effective_score_min(sym, SYM_OVERRIDES, SCORE_MIN_REQUIRED)
```

This is functionally equivalent but centralises the logic and uses `SCORE_MIN_REQUIRED` as the authoritative global fallback instead of hardcoded 0.

---

## Import Block (add near top of titanium_dashboard_v10.py, after line 82)

To avoid circular import issues, add all fix imports in a guarded block:

```python
# ---------------------------------------------------------------------------
# SMC Audit Fixes — v10 patch imports
# ---------------------------------------------------------------------------
try:
    from fixes.smc_corrections import (
        detect_liquidity_sweep_v2,
        detect_sweep_with_displacement,
        detect_breaker_blocks,
        detect_failed_auction,
    )
    from fixes.new_reversal_patterns import (
        detect_inducement_sweep_choch,
        detect_rsi_divergence_at_ob,
        compute_reversal_confidence,
    )
    from fixes.config_adaptive_patch import (
        get_delta_vol_freshness_limit,
        get_regime_rsi_thresholds,
    )
    from fixes.scoring_update import (
        compute_annualized_sharpe,
        walk_forward_split,
        compute_profit_factor,
        OPT_CONFIGURATIONS_EXTENDED,
        apply_reversal_confidence_bonus,
        get_effective_score_min,
    )
    _FIXES_LOADED = True
except ImportError as _e:
    _FIXES_LOADED = False
    import logging as _log
    _log.getLogger(__name__).warning("SMC fix imports failed: %s — running without patches", _e)
```

Then in each integration site, guard with `if _FIXES_LOADED:` where appropriate to ensure backward compatibility.

---

## Notes

- The `fixes/` directory must be in the same folder as `titanium_dashboard_v10.py` for relative imports to work.  It must contain an `__init__.py` (can be empty).
- All fix functions are self-contained and have no side effects on global state — safe to import.
- The `from __future__ import annotations` at line 1 of the main file is incompatible with the fix files (project constraint).  The fix files do not use it.
- After integration, run the startup print section to verify `{len(OPT_CONFIGURATIONS)} configs` shows 15.
