# Titanium Dashboard v10 — Performance Audit

**Auditor:** Claude Sonnet 4.6 (Performance Analyst Agent)
**Date:** 2026-03-29
**File audited:** `titanium_dashboard_v10.py` (~5,800 lines)

---

## Executive Summary

**Overall performance framework score: 5.5 / 10**

The codebase shows genuine engineering effort and several sound practices (fees included, ATR clamping, circuit breaker, adaptive weights). However, three structural flaws significantly compromise the reliability of the performance claims derived from the backtest and optimization systems.

### Top 3 Risks

1. **Sharpe ratio formula is non-standard (P0 — critical).**
   Both `_backtest_strategy_real()` and `strict_trix_backtest_sharpe()` compute Sharpe as
   `mean / std × sqrt(N_trades)` — a trade-count-scaled ratio, not an annualized one.
   This makes Sharpe values incomparable across symbols, timeframes, and data windows,
   and systematically inflates the score when a configuration generates more trades.
   The optimizer therefore selects the highest-frequency strategy, not the best risk-adjusted one.

2. **Module 18 optimization has no out-of-sample (OOS) validation (P0 — critical).**
   All 7 (or 12 for PAXG) configurations are evaluated on the same 60-day in-sample window,
   and the best is selected and immediately applied live. There is no held-out test period.
   The "combined" score (Sharpe + Expectancy + Drawdown) is computed on the same data used
   for selection, guaranteeing in-sample overfitting on a 2-parameter search space.

3. **Circuit breaker drawdown comparison uses incompatible units (P1 — important).**
   The backtest tracks drawdown as a ratio on an equity curve starting at 1.0 (e.g., -0.08 = -8%).
   The circuit breaker reconstructs live drawdown using `np.cumsum(pnl_list)` where each `pnl`
   entry is a raw normalized P&L per trade. `cumsum` produces additive return, not a multiplicative
   equity curve. The peak/drawdown logic therefore operates on additive units vs multiplicative
   units from the backtest, making the threshold comparison unreliable.

---

## 1. Backtest Engine Audit

### Function: `_backtest_strategy_real()` (line ~2007)

**Vectorized logic:**
The function iterates candle-by-candle (not fully vectorized despite the comment). Starting at bar 200 to skip EMA warmup, it classifies each bar as LONG or SHORT based on whether the close is above or below EMA200. It then calls `compute_adaptive_levels()` to derive SL and TP1, and simulates the trade forward bar-by-bar for up to 50 candles. The first SL or TP1 touch exits. If neither is hit in 50 bars, it exits at the close of bar 200+50. A mandatory 3-bar rest is enforced after each trade.

**Trade simulation — realism assessment:**

| Aspect | Implementation | Assessment |
|---|---|---|
| Entry price | `close_arr[i]` (current bar close) | Mild lookahead: real entry is next bar open |
| TP/SL check | Uses H/L of future bars | Acceptable; bar-level granularity understates slippage |
| Fee | `fee_pct = fee_bps / 10_000` subtracted once per trade | Only one-way fee deducted; round-trip should subtract twice |
| SL exit PnL | `(sl - entry_price) / entry_price - fee_pct` | Correct for long; correct for short |
| Max hold | 50 bars hard cap | Reasonable; forces resolution |
| Rest period | 3-bar mandatory gap | Prevents chained overlapping trades |

**Lookahead bias:** Present but minor. Entry is taken at `close_arr[i]` (the current bar's close), but the trade would realistically only be executable at the next bar's open. This gives a slight artificial advantage to the backtest, particularly in trending markets where `close[i] > close[i+1]` rarely.

**Fee realism:** Only a single fee (4 bps) is deducted per trade. A realistic round-trip costs 2 × 4 bps = 8 bps. On short holding periods (5m timeframe), this is material — a 4 bps undercharge of fees per trade systematically overstates all performance metrics.

### Metric computation

- **Equity curve:** Multiplicative `equity *= (1 + outcome)` — correct.
- **Max drawdown:** Peak-to-trough on equity curve — correct formula.
- **Winrate:** `wins / n_trades` — correct.
- **Expectancy:** `WR × avg_win − (1−WR) × avg_loss` — correct formula.
- **Sharpe:** See Section 2.

---

## 2. Sharpe Ratio Analysis

### Current formula (exact code — both instances identical)

In `_backtest_strategy_real()` (line ~2146):
```python
sharpe = mean_pnl / (std_pnl + 1e-12) * (n_trades ** 0.5)
```

In `strict_trix_backtest_sharpe()` (line ~3587):
```python
sharpe = mean / (std + 1e-12) * (len(r) ** 0.5)
```

### Is it annualized correctly?

**No.** The standard annualized Sharpe ratio for a backtest over `D` days is:

```
Sharpe_annualized = (mean_trade_return / std_trade_return) × sqrt(252 / backtest_days)
```

Or equivalently using per-period returns:
```
Sharpe_annualized = (mean_period_return / std_period_return) × sqrt(trading_periods_per_year)
```

The code uses `sqrt(N_trades)` as the scaling factor. This is not a standard formulation. It is a variant that scales with the square root of the number of trades, making Sharpe proportional to both return quality **and** trade frequency. Its interpretation is:

- A strategy with 100 trades and Sharpe 0.5 using this formula has the same "score" as a strategy with 25 trades and Sharpe 1.0.
- The optimizer will therefore prefer higher-frequency configurations, even if they have lower per-trade quality.

### Impact of the bug

1. **Optimizer bias toward frequency:** Module 18 selects the "best" SL/TP config using `_opt_score()` which includes this Sharpe. Configs with more trades (tighter SL = more SL hits = more trade completions) will score higher on this Sharpe metric even if they lose more often.

2. **STRICT incomparability:** The STRICT walk-forward uses the same formula. A configuration found optimal over 120 days with many trades will report a higher Sharpe than an equivalent config over 30 days, making cross-window comparison meaningless.

3. **Circuit breaker uses backtest Sharpe indirectly:** Since `max_drawdown` is stored from the same biased backtest, the circuit breaker threshold is also derived from an overfitted run.

4. **Reported Sharpe values are misleading:** A Sharpe of 1.5 from `_backtest_strategy_real()` with 50 trades corresponds to a per-trade information ratio of `1.5 / sqrt(50) ≈ 0.21` — which is barely above zero.

---

## 3. Walk-Forward Validation

### STRICT TRIX Walk-Forward (Module STRICT)

**How it works:**
1. Fetches 120 days of 5m candles (`STRICT_IN_SAMPLE_DAYS=120`).
2. Splits the data into 30-day sub-periods (`STRICT_SUBPERIOD_DAYS=30`) → up to 4 periods.
3. Runs `STRICT_RANDOM_ITERS=300` random parameter searches over the grid `trix_len ∈ [5,51]`, `signal_len ∈ [5,51]`, `trend_ma_len ∈ {100,200,...,800}`.
4. For each candidate, evaluates `strict_trix_backtest_sharpe()` on each sub-period.
5. Scores robustness via `_robust_score()`: requires `STRICT_ROBUST_MIN_PERIODS=2` periods to have Sharpe ≥ `STRICT_SHARPE_FLOOR=0.30`.
6. Applies Gaussian smoothing to the 2D heatmap (`trix_len × signal_len`) and picks top-3 zone centers.
7. Recalibrates every `STRICT_RECALIB_DAYS=120` days.

**Quality assessment:**

| Aspect | Score | Comment |
|---|---|---|
| Sub-period cross-validation idea | Good | Splitting in-sample data into 4 chunks is a reasonable robustness check |
| True OOS testing | Absent | All 120 days are used for both search and validation; no held-out period |
| Parameter space coverage | Weak | 300 random iters over 47×47×8×2 = 353,792 combinations = 0.08% coverage |
| Sharpe formula | Flawed | Same `sqrt(N_trades)` issue applies here |
| Fallback cascade (relaxed → ultra-relaxed → best-effort) | Risky | Silently accepting "best-effort" configs with no robustness constraint is worse than emitting no signal |
| Recalibration frequency | Reasonable | 120-day recalib on 120-day window means each recalib sees entirely new data |

The sub-period structure is conceptually a walk-forward, but since both search and scoring happen on the same 120-day window, it is more accurately described as **cross-period validation within the in-sample window** — not a true walk-forward (which requires a distinct OOS holdout).

### Main OPT (Module 18)

**Does it use walk-forward?** No.

Module 18 fetches 60 days of 5m candles, tests 7 SL/TP configurations on all 60 days, and picks the best composite score. There is no temporal split. The entire 60-day window is both the training and evaluation set.

**Risk of in-sample overfitting:** Moderate-to-high.
- With only 2 free parameters (atr_mult and tp_ratios), overfitting risk is lower than for STRICT.
- However, the "combined" score (0.5×Sharpe + 0.3×Expectancy + 0.2×(1+MaxDD)) is computed on the same data used for selection.
- Over a 60-day in-sample window on 5m data (~17,280 bars), the actual number of trades per configuration is moderate (likely 50–300), which limits overfitting somewhat.
- The main risk is **regime dependence**: the "best" config for the last 60 days of a bull trend will differ completely from the best config in a choppy or bear regime. Reapplying without OOS confirmation causes silent regime mismatch.

### Recommended improvements

1. Reserve the last 20% of the fetched history (e.g., 12 days out of 60) as a strict holdout; only select configs that pass both in-sample and OOS Sharpe thresholds.
2. Add a minimum trade count gate per configuration (currently `OPT_MIN_CANDLES=200` applies to bars, not to trades).
3. For STRICT: increase random iterations to 1,000+ or switch to Bayesian optimization given the large parameter space.

---

## 4. Overfitting Risk Assessment

### Module 18 (SL/TP optimization)

| Parameter | Values |
|---|---|
| `atr_mult` | 0.7, 1.0, 1.2, 1.5 (4 levels) |
| `tp_ratios` | (1.2,1.8,2.4) or (1.5,2.1,2.6) (2 levels) |
| `trailing` | False only (effectively fixed) |
| **Total configs** | 7 (non-exhaustive grid) |

Parameter space: 7 discrete points. Data: ~17,280 bars (60 days × 288 bars/day at 5m), yielding approximately 100–400 trades per configuration. With 7 candidates and ~200 trades per config, the risk of spurious Sharpe inflation is limited but non-zero given the Sharpe formula issue.

**Cross-validation or OOS testing:** None present. No held-out period, no bootstrap, no permutation testing.

### STRICT TRIX optimization

| Parameter | Range |
|---|---|
| `trix_len` | integers 5–51 (47 values) |
| `signal_len` | integers 5–51 (47 values) |
| `trend_ma_len` | {100,200,300,400,500,600,700,800} (8 values) |
| `signal_ma` | {ema, sma} (2 values) |
| **Total space** | 47 × 47 × 8 × 2 = 353,792 combinations |

With 300 random iterations, only 0.085% of the space is sampled. While the 2D smoothing and robust-period requirement provide partial regularization, the sparse sampling means high-scoring regions may be found by chance. The sub-period validation (4 × 30-day chunks from the same 120-day window) reduces but does not eliminate this risk.

**Overall overfitting verdict:** The STRICT system has a meaningful overfitting risk due to the large parameter space and small OOS window. Module 18 risk is lower due to the small config count, but remains unvalidated.

---

## 5. Drawdown Control

### Circuit Breaker (`circuit_breaker_monitor()`, lines 2394–2455)

**How it works:**
Every `CB_CHECK_INTERVAL=3600` seconds (1 hour), for each symbol:
1. Takes the last 20 closed signals from `signal_history`.
2. Computes cumulative PnL: `cum_pnl = np.cumsum(pnl_list)`.
3. Computes drawdown: `drawdown = min(cum_pnl - max.accumulate(cum_pnl))`.
4. Retrieves `max_drawdown` from `_best_results_2025` (the last Module 18 result).
5. Threshold: `allowed_dd = max_drawdown_backtest × MAX_DD_MULTIPLIER` (where `MAX_DD_MULTIPLIER=1.3`).
6. If `drawdown < allowed_dd` (i.e., live DD exceeds 130% of backtest DD) → triggers `optimise_strategies_year()` for that symbol.

**Bug — unit mismatch:**
- Backtest `max_drawdown` is computed on a multiplicative equity curve (equity starts at 1.0; drawdown is e.g. -0.08 meaning -8% from peak).
- Live drawdown uses `np.cumsum(pnl_list)` where `pnl` values are stored as normalized per-trade returns. The cumsum produces additive return, not a multiplicative curve. For small PnL values the difference is small, but for larger drawdowns the two measures diverge: -8% additive ≠ -8% multiplicative. More importantly, the scale of the live cumsum depends entirely on how many trades are in the last-20 window and their average size, making the comparison unstable.

**Minimum sample gate:** The check requires at least 5 closed trades in the last-20 window. With `signal_history` capped at 500 entries but `pnl` only populated since v8, early runs may not have enough closed trades.

**Response action:** Triggering `optimise_strategies_year()` during a drawdown period re-optimizes on the same recent data that caused the drawdown — potentially selecting a configuration that fits the current adverse regime rather than a robust one. This is a design concern.

### Max Drawdown Tracking

Implemented correctly within the backtest (`_backtest_strategy_real()` line ~2156):
```python
eq_arr = np.array(eq_curve, dtype=float)
peak   = np.maximum.accumulate(eq_arr)
dd     = (eq_arr / (peak + 1e-12)) - 1.0
max_dd = float(dd.min())
```
This is the standard multiplicative peak-to-trough drawdown. Correctly implemented.

### Position Sizing

**No dynamic position sizing is implemented in the dashboard.** The system is a signal generator, not an execution engine. SL/TP levels are provided to the user, but no capital allocation, lot sizing, or Kelly criterion is applied. The `.env` reference to `CAPITAL_EUR` and `RISK_PCT` (mentioned in the CLAUDE.md) does not appear to be used in the v10 source code. This means position sizing is left entirely to the user, which is a significant operational gap if the dashboard is used for live trading decisions.

---

## 6. Module 18 Optimization (SL/TP configs)

### Configurations tested

**Standard symbols (BTC, ETH, SOL) — 7 configs:**

| # | atr_mult | tp_ratios | trailing |
|---|---|---|---|
| 1 | 0.7 | (1.2, 1.8, 2.4) | False |
| 2 | 0.7 | (1.5, 2.1, 2.6) | False |
| 3 | 1.0 | (1.2, 1.8, 2.4) | False |
| 4 | 1.0 | (1.5, 2.1, 2.6) | False |
| 5 | 1.2 | (1.2, 1.8, 2.4) | False |
| 6 | 1.2 | (1.5, 2.1, 2.6) | False |
| 7 | 1.5 | (1.2, 1.8, 2.4) | False |

**PAXG/USDT (Gold) — 12 configs:** atr_mult in {0.8, 1.0, 1.2, 1.3, 1.5} × tp_ratios in {(0.8,1.2,1.6), (1.0,1.5,2.0), (1.2,1.8,2.4)}.

### Selection criterion

Default: `OPT_SCORE_CRITERIA = "combined"` which computes:
```
score = 0.5 × Sharpe + 0.3 × Expectancy + 0.2 × (1 + max_drawdown)
```
Where all three components are derived from the same in-sample window.

The `_opt_score()` function also supports `"sharpe"` and `"expectancy"` as single-criterion modes.

### OOS Validation

**No.** There is no out-of-sample validation step. The optimization loop:
1. Fetches 60 days of history.
2. Runs all configs on the full 60 days.
3. Selects the best composite score.
4. Injects the result directly into `_best_results_2025` for live use.

No portion of the 60-day window is held out for validation. No statistical significance test is performed on the Sharpe difference between configurations.

---

## 7. Recommendations

### P0: Critical fixes needed now

**P0-1 — Fix the Sharpe formula in both backtest functions.**

Replace:
```python
sharpe = mean_pnl / (std_pnl + 1e-12) * (n_trades ** 0.5)
```
With the standard annualized formula (requires knowing the number of trading days in the sample):
```python
# backtest_days = number of calendar days in df
# periods_per_day = 288 for 5m, 48 for 30m, etc.
annualization_factor = (periods_per_day * 252) ** 0.5
sharpe = (mean_period_return / (std_period_return + 1e-12)) * annualization_factor
```
Or if using trade-level returns and you know the holding period:
```python
avg_hold_periods = backtest_days * periods_per_day / n_trades
sharpe = (mean_pnl / (std_pnl + 1e-12)) * (252 * periods_per_day / avg_hold_periods) ** 0.5
```
This must be fixed before Module 18 or STRICT results can be trusted.

**P0-2 — Add OOS validation to Module 18.**

Reserve the last 15 days (25%) of the 60-day fetch as a holdout. Evaluate the in-sample winner on holdout before accepting. Reject any config whose OOS Sharpe is more than 0.5 below its in-sample Sharpe (overfitting signal).

**P0-3 — Fix round-trip fee accounting.**

Change `- fee_pct` to `- 2 * fee_pct` in the PnL computation inside `_backtest_strategy_real()`, or equivalently deduct fee at entry and exit separately. At 5m with many trades, the 4 bps undercharge compunds meaningfully.

### P1: Important improvements

**P1-1 — Fix circuit breaker unit mismatch.**

Replace the additive cumsum approach with a multiplicative equity curve for the live drawdown calculation:
```python
equity = 1.0
eq_live = [1.0]
for p in pnl_list:
    equity *= (1 + p)
    eq_live.append(equity)
eq_arr = np.array(eq_live)
peak = np.maximum.accumulate(eq_arr)
drawdown = float(np.min(eq_arr / peak - 1.0))
```
This makes the comparison with the backtest `max_drawdown` (which uses the same multiplicative formula) valid.

**P1-2 — Add a minimum trade count requirement in Module 18.**

`OPT_MIN_CANDLES=200` checks bars, not trades. Add a guard:
```python
if res.get("trades", 0) < 30:
    res["_score"] = -1e18  # insufficient trades, discard
```

**P1-3 — Add position sizing guidance.**

If the dashboard is used for live execution decisions, implement a `risk_per_trade` calculator:
```
qty = (capital × risk_pct) / abs(entry - sl)
```
and surface it in the signal output. This is the single most important missing risk management feature for live use.

**P1-4 — Disable the "best-effort" fallback in STRICT calibration.**

The cascade `strict → relaxed → ultra-relaxed → best-effort` means the system will always produce a TRIX configuration, even when there is no statistically valid one. Emitting a "no valid calibration" state is safer than silently using a best-effort config that has no robustness guarantee.

### P2: Nice to have

**P2-1 — Increase STRICT random search coverage.**

Raise `STRICT_RANDOM_ITERS` from 300 to 1,000, or implement Bayesian optimization (e.g., via `scipy.optimize`) over the continuous parameter space. Current 0.085% grid coverage makes the heatmap unreliable as a representation of the true performance surface.

**P2-2 — Add a permutation test for Sharpe significance.**

Before applying Module 18 results, verify the best config's Sharpe exceeds the 95th percentile of Sharpe values obtained by randomly shuffling trade outcomes (Monte Carlo). This distinguishes genuine edge from noise.

**P2-3 — Separate in-sample / OOS date ranges in the dashboard UI.**

Surface the OOS Sharpe alongside the in-sample Sharpe in `/api/optim/results` so users can compare and detect overfitting visually.

**P2-4 — Persist per-symbol equity curves.**

Currently, circuit breaker operates on a rolling 20-trade window from `signal_history`. A persistent equity curve (stored in a lightweight time-series file per symbol) would give a more reliable and longer-horizon drawdown measurement.

---

*End of Performance Audit*
