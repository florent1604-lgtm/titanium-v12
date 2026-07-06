"""
scoring_update.py — SMC Audit Fix File #4
==========================================
Scoring system fixes for titanium_dashboard_v10.py:

  1. compute_annualized_sharpe         — correct annualised Sharpe formula
  2. walk_forward_split                — temporal train/test split
  3. compute_profit_factor             — gross profit / gross loss
  4. OPT_CONFIGURATIONS_EXTENDED       — 15-config candidate set (was 7)
  5. apply_reversal_confidence_bonus   — adds bonus points for high-confidence reversals
  6. get_effective_score_min           — per-symbol score_min lookup with fallback

Python 3.9+, numpy only (no external deps).
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Annualised Sharpe ratio
# ---------------------------------------------------------------------------

def compute_annualized_sharpe(
    pnl_array: "np.ndarray | List[float]",
    backtest_days: int,
    trading_days_per_year: int = 252,
) -> float:
    """Compute the correct annualised Sharpe ratio for a backtest PnL series.

    PROBLEM with the existing formula
    ----------------------------------
    The original code uses:
        sharpe = mean / std * sqrt(n_trades)
    This scales by the square root of the NUMBER OF TRADES, not by calendar time.
    A strategy with more trades will always appear better, creating a trade-count
    bias.  It is NOT the standard Sharpe Ratio used in quantitative finance.

    Correct formula
    ---------------
    Annualised Sharpe = (mean_per_trade / std_per_trade) × sqrt(252 / backtest_days)

    This normalises for the amount of time tested:
      - If backtest_days = 252 → multiplier = 1.0  (1 year = standard)
      - If backtest_days = 30  → multiplier = sqrt(8.4) ≈ 2.9  (short test penalised)
      - If backtest_days = 60  → multiplier = sqrt(4.2) ≈ 2.05

    Note: This gives a per-trade Sharpe (each trade is one "period").  For strategies
    with very different trade frequencies this may still need adjustment, but it is
    vastly more correct than scaling by raw trade count.

    Parameters
    ----------
    pnl_array              : array-like of float  Per-trade PnL values (as fractions, e.g. 0.02 = +2%)
    backtest_days          : int                  Duration of the backtest in calendar days
    trading_days_per_year  : int                  Convention: 252 for crypto/futures, 365 for 24/7

    Returns
    -------
    float — Annualised Sharpe ratio.
            Returns -1e9 (sentinel) if fewer than 2 trades or std = 0.
    """
    arr = np.asarray(pnl_array, dtype=float)
    n   = len(arr)

    if n < 2:
        return float(-1e9)

    mean_pnl = float(arr.mean())
    std_pnl  = float(arr.std(ddof=1))

    if std_pnl < 1e-12:
        # Zero-variance → Sharpe undefined.  Return large positive if profitable,
        # large negative if losing, to preserve correct rank ordering.
        return float(1e9) if mean_pnl > 0 else float(-1e9)

    if backtest_days <= 0:
        return float(-1e9)

    # Annualisation factor: sqrt(trading_days_per_year / backtest_days)
    annualisation = float(np.sqrt(trading_days_per_year / backtest_days))

    sharpe = (mean_pnl / std_pnl) * annualisation
    return float(sharpe)


# ---------------------------------------------------------------------------
# 2. Walk-forward temporal split
# ---------------------------------------------------------------------------

def walk_forward_split(
    df: pd.DataFrame,
    train_ratio: float = 0.7,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split a time-series dataframe into train and test sets temporally.

    IMPORTANT: No shuffle is applied.  Shuffling a time series destroys its
    temporal structure and leads to look-ahead bias in backtesting.

    The split is made at ``train_ratio × len(df)`` index position.  All rows
    before the split point are "in-sample" (train); all rows after are
    "out-of-sample" (test).

    Parameters
    ----------
    df          : pd.DataFrame  OHLCV or any time-indexed dataframe.
                                Must be sorted by index ascending (oldest first).
    train_ratio : float         Fraction of data to use for training.
                                Default 0.7 = 70% train / 30% test.

    Returns
    -------
    Tuple[pd.DataFrame, pd.DataFrame] : (df_train, df_test)
        Both retain the original index (datetime).

    Raises
    ------
    ValueError  if df has fewer than 4 rows (not enough to split meaningfully)
    ValueError  if train_ratio is not in (0.0, 1.0) exclusive
    """
    if df is None or len(df) < 4:
        raise ValueError(f"walk_forward_split: need at least 4 rows, got {len(df) if df is not None else 0}")

    if not (0.0 < train_ratio < 1.0):
        raise ValueError(f"walk_forward_split: train_ratio must be in (0, 1), got {train_ratio}")

    n_total  = len(df)
    n_train  = max(2, int(n_total * train_ratio))
    n_test   = n_total - n_train

    if n_test < 2:
        raise ValueError(
            f"walk_forward_split: test set has only {n_test} row(s) with "
            f"train_ratio={train_ratio} on {n_total} rows.  Lower train_ratio."
        )

    df_train = df.iloc[:n_train].copy()
    df_test  = df.iloc[n_train:].copy()

    return df_train, df_test


# ---------------------------------------------------------------------------
# 3. Profit factor
# ---------------------------------------------------------------------------

def compute_profit_factor(
    pnl_array: "np.ndarray | List[float]",
) -> float:
    """Compute the Profit Factor: gross_profit / gross_loss.

    Profit Factor > 1.0 = strategy is profitable in aggregate.
    Common benchmarks:
      < 1.0 : losing strategy
      1.0–1.5 : marginal
      1.5–2.0 : good
      > 2.0   : excellent (but may indicate overfitting on small samples)

    Parameters
    ----------
    pnl_array : array-like of float  Per-trade PnL fractions.

    Returns
    -------
    float
        Gross profit / gross loss.
        Returns ``float('inf')`` if there are no losing trades.
        Returns 0.0 if there are no winning trades.
        Returns -1e9 (sentinel) if the array is empty.
    """
    arr = np.asarray(pnl_array, dtype=float)

    if len(arr) == 0:
        return float(-1e9)

    gross_profit = float(np.sum(arr[arr > 0]))
    gross_loss   = float(np.sum(np.abs(arr[arr < 0])))

    if gross_loss < 1e-12:
        # No losses: if there are wins, return inf; if no wins either, return 1.0
        return float("inf") if gross_profit > 1e-12 else 1.0

    if gross_profit < 1e-12:
        return 0.0

    return float(gross_profit / gross_loss)


# ---------------------------------------------------------------------------
# 4. Enhanced OPT_CONFIGURATIONS (15 configs)
# ---------------------------------------------------------------------------
# Replaces the existing 7-config set (~line 321 in titanium_dashboard_v10.py).
# Additions:
#   - atr_mult 0.6 and 0.8 (tighter SL tier for high-frequency scalp setups)
#   - tp_ratios (1.0, 1.5, 2.0) alongside the existing (1.2,1.8,2.4) and (1.5,2.1,2.6)
#   - All trailing=False (unchanged — trailing stop implementation not yet validated)
#
# The 15 configs cover the full {ATR_MULT} × {TP_RATIOS} matrix systematically:
#   ATR_MULT : 0.6, 0.8, 1.0, 1.2, 1.5
#   TP_RATIOS: (1.0,1.5,2.0), (1.2,1.8,2.4), (1.5,2.1,2.6)

OPT_CONFIGURATIONS_EXTENDED: List[Dict[str, Any]] = [
    # ── ATR×0.6 — very tight SL (scalping range) ───────────────────────────
    {"atr_mult": 0.6, "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 0.6, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 0.6, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},

    # ── ATR×0.8 — tight SL (reactive entries) ──────────────────────────────
    {"atr_mult": 0.8, "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 0.8, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 0.8, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},

    # ── ATR×1.0 — balanced (default / most common best config) ─────────────
    {"atr_mult": 1.0, "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},

    # ── ATR×1.2 — moderate SL (trending markets) ───────────────────────────
    {"atr_mult": 1.2, "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.2, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.2, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},

    # ── ATR×1.5 — wide SL (high-volatility / low-frequency) ────────────────
    {"atr_mult": 1.5, "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.5, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.5, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
]


# ---------------------------------------------------------------------------
# 5. Reversal confidence bonus for score_setup
# ---------------------------------------------------------------------------

def apply_reversal_confidence_bonus(
    score_raw: float,
    reversal_confidence: float,
) -> float:
    """Apply a score bonus when the reversal confidence pattern score is high.

    This integrates the output of ``compute_reversal_confidence()`` from
    new_reversal_patterns.py into the main score_setup scoring pipeline.

    Bonus schedule
    --------------
    reversal_confidence ≥ 90 : +1.0 point  (near-perfect multi-pattern confluence)
    reversal_confidence ≥ 80 : +0.5 point  (strong multi-factor agreement)
    below 80                 : no bonus

    The bonus is additive to the raw score (float).  The caller must apply the
    normal int() rounding and max-cap AFTER calling this function.

    Parameters
    ----------
    score_raw            : float  Raw score before bonus (e.g. 7.0)
    reversal_confidence  : float  Output of compute_reversal_confidence(), 0.0–100.0

    Returns
    -------
    float — Adjusted score (may be fractional; caller rounds to int if needed)

    Examples
    --------
    >>> apply_reversal_confidence_bonus(7.0, 92.0)
    8.0

    >>> apply_reversal_confidence_bonus(7.0, 83.0)
    7.5

    >>> apply_reversal_confidence_bonus(7.0, 75.0)
    7.0
    """
    rc = float(reversal_confidence)

    if rc >= 90.0:
        bonus = 1.0
    elif rc >= 80.0:
        bonus = 0.5
    else:
        bonus = 0.0

    return float(score_raw) + bonus


# ---------------------------------------------------------------------------
# 6. Per-symbol score_min lookup
# ---------------------------------------------------------------------------

def get_effective_score_min(
    sym: str,
    sym_overrides: Dict[str, Dict[str, Any]],
    global_min: int,
) -> int:
    """Return the effective minimum score for a symbol, with global fallback.

    Checks the per-symbol overrides dict first.  Falls back to the global
    SCORE_MIN_REQUIRED if no symbol-specific value is found.

    This resolves the issue where PAXG had a per-symbol score_min=5 but the
    logic was scattered across multiple call sites instead of being centralised.

    Parameters
    ----------
    sym           : str   Symbol string, e.g. "BTC/USDT"
    sym_overrides : dict  SYM_OVERRIDES dict (from config or config_adaptive_patch)
    global_min    : int   Global SCORE_MIN_REQUIRED value (e.g. 7)

    Returns
    -------
    int — Effective minimum score to apply for this symbol.

    Examples
    --------
    >>> overrides = {"PAXG/USDT": {"score_min": 5}}
    >>> get_effective_score_min("PAXG/USDT", overrides, 7)
    5
    >>> get_effective_score_min("BTC/USDT", overrides, 7)
    7
    """
    sym_data = sym_overrides.get(sym)
    if sym_data is None:
        return int(global_min)

    sym_min = sym_data.get("score_min")
    if sym_min is None:
        return int(global_min)

    return int(sym_min)
