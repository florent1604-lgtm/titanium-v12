"""core/scoring_engine.py — Scoring /11 SMC avec poids adaptatifs et régime marché."""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import math
import pandas as pd
from utils.config import (
    SCORE_CRITERIA, SCORE_MIN_REQUIRED, ADX_TREND_THRESHOLD,
    RSI_ENTRY_LONG, RSI_ENTRY_SHORT, ACTIVE_TF,
    get_sym_override,
)
from utils.logger import get_logger
from core.smc_engine import (
    compute_ema200, has_ob_or_fvg_alignment, detect_liquidity_sweep,
    detect_rejection_candle, detect_bos, detect_volume_spike,
)
from indicators.rsi import rsi_signal, rsi_divergence
from indicators.adx import get_market_regime, compute_adx
from indicators.trix import trix_signal

logger = get_logger(__name__)


def score_setup(
    sym: str,
    df_h4: pd.DataFrame,
    df_1m: pd.DataFrame,
    df30: pd.DataFrame,
    df_h2: Optional[pd.DataFrame] = None,
    df_h1: Optional[pd.DataFrame] = None,
    df_m30: Optional[pd.DataFrame] = None,
    df_m15: Optional[pd.DataFrame] = None,
    df_m5:  Optional[pd.DataFrame] = None,
    df_1d:  Optional[pd.DataFrame] = None,
    strict_params: Optional[dict] = None,
    scoring_w: Optional[Dict[str, float]] = None,
    delta_vol_state: Optional[dict] = None,
    futures_data_state: Optional[dict] = None,
) -> Tuple[int, str, List[str], Dict[str, Any]]:
    """Scoring multi-timeframe SMC — score /11.

    Returns: (score_int, side, confirmations_list, context_dict)
    """
    weights   = scoring_w or {c: 1.0 for c in SCORE_CRITERIA}
    rsi_long  = get_sym_override(sym, "rsi_long",  RSI_ENTRY_LONG)
    rsi_short = get_sym_override(sym, "rsi_short", RSI_ENTRY_SHORT)
    adx_th    = get_sym_override(sym, "adx_threshold", ADX_TREND_THRESHOLD)

    # ── Prix courant ─────────────────────────────────────────────────────────
    price = 0.0
    if df30 is not None and not df30.empty:
        price = float(df30["close"].iloc[-1])
    elif df_m5 is not None and not df_m5.empty:
        price = float(df_m5["close"].iloc[-1])
    if price <= 0:
        return 0, "NEUTRE", [], {"error": "price_zero"}

    # ── EMA200 H4 — Biais directeur ──────────────────────────────────────────
    side     = "NEUTRE"
    ema200_h4 = float("nan")
    if df_h4 is not None and len(df_h4) >= 200:
        ema200_h4 = compute_ema200(df_h4["close"])
        if not math.isnan(ema200_h4):
            side = "ACHAT" if price > ema200_h4 else "VENTE"
    if side == "NEUTRE":
        return 0, "NEUTRE", [], {"ema200_h4": ema200_h4}

    confs: List[str]       = []
    ctx:   Dict[str, Any] = {"side": side, "price": price, "ema200_h4": ema200_h4}
    weighted_score = 0.0

    def add(criterion: str, ok: bool, label: str) -> None:
        if ok:
            w = weights.get(criterion, 1.0)
            nonlocal weighted_score
            weighted_score += w
            confs.append(label)
        ctx[criterion] = ok

    # 1. EMA200_H4
    add("EMA200_H4", True, f"EMA200-H4 {'haussier' if side == 'ACHAT' else 'baissier'}")

    # 2. STRUCT_H2H1 — Break of Structure
    bos_h2 = detect_bos(df_h2, side) if df_h2 is not None else False
    bos_h1 = detect_bos(df_h1, side) if df_h1 is not None else False
    add("STRUCT_H2H1", bos_h2 or bos_h1, "BOS H2/H1")

    # 2b. ALIGN_H2H1 — Bonus H2+H1 alignés
    add("ALIGN_H2H1", bos_h2 and bos_h1, "H2+H1 alignés")

    def _df(a, b):
        """Retourne a si non-None et non-vide, sinon b."""
        return a if (a is not None and not a.empty) else b

    # 3. OB_FVG_30M
    aligned_30m, ob_status_30m, ob_quality_30m = has_ob_or_fvg_alignment(_df(df_m30, df30), side, price)
    add("OB_FVG_30M", aligned_30m, f"OB/FVG 30m ({ob_status_30m})")
    ctx["ob_quality"] = ob_quality_30m

    # 3b. OB_FVG_15M_CONFIRM — Double confirmation
    if df_m15 is not None:
        aligned_15m, _, _ = has_ob_or_fvg_alignment(df_m15, side, price)
    else:
        aligned_15m = False
    add("OB_FVG_15M_CONFIRM", aligned_30m and aligned_15m, "OB/FVG double conf 15m")

    # 4. REJET_15M — Bougie de rejet
    df_entry = df_m5 if df_m5 is not None else df30
    add("REJET_15M", detect_rejection_candle(df_entry, side), "Rejet 5m/15m")

    # 5. TRIX_5M — TRIX signal
    add("TRIX_5M", trix_signal(_df(df_m5, df30), strict_params, side), "TRIX 5m")

    # 6. EMA200_1D — Biais macro journalier
    ema200_1d = float("nan")
    ema200_1d_ok = False
    if df_1d is not None and len(df_1d) >= 200:
        ema200_1d = compute_ema200(df_1d["close"])
        ema200_1d_ok = (
            (side == "ACHAT" and price > ema200_1d)
            or (side == "VENTE" and price < ema200_1d)
        ) if not math.isnan(ema200_1d) else False
    add("EMA200_1D", ema200_1d_ok, "EMA200-1D aligné")
    ctx["ema200_1d"] = ema200_1d

    # 7. DELTA_VOL — Pression acheteur/vendeur
    delta_ok = False
    if delta_vol_state:
        delta_ok = (
            (side == "ACHAT" and delta_vol_state.get("bullish", False))
            or (side == "VENTE" and delta_vol_state.get("bearish", False))
        )
    add("DELTA_VOL", delta_ok, "Delta volume confirme")

    # 8. LIQ_SWEEP — Liquidity sweep
    sweep_df = _df(df_m30, df30)
    add("LIQ_SWEEP", detect_liquidity_sweep(sweep_df, side), "Liquidity sweep")

    # 9. ADX_REGIME — Régime marché
    regime = get_market_regime(_df(df_m30, df30), adx_threshold=adx_th)
    adx_ok = regime in ("TREND", "RANGE")
    add("ADX_REGIME", adx_ok, f"ADX régime {regime}")
    ctx["regime"] = regime
    ctx["adx"]    = compute_adx(_df(df_m30, df30))

    # ── RSI divergence (bonus contexte, pas de score) ──────────────────────
    rsi_long_ok, rsi_short_ok, rsi_val = rsi_signal(df_entry, rsi_long, rsi_short)
    ctx["rsi"] = rsi_val
    ctx["rsi_divergence"] = rsi_divergence(df_entry)

    # ── Volume spike (bonus contexte) ─────────────────────────────────────────
    ctx["volume_spike"] = detect_volume_spike(df_entry)

    # ── Score final ──────────────────────────────────────────────────────────
    raw_score = int(round(weighted_score))
    # Normaliser sur /11 si les poids ont divergé
    score = min(11, max(0, raw_score))

    ctx["score"]    = score
    ctx["weighted"] = round(weighted_score, 3)
    ctx["confs"]    = confs

    logger.debug("[SCORE] %s %s score=%d/11 (%s)", sym, side, score, ", ".join(confs))
    return score, side, confs, ctx


def get_score_min(sym: str) -> int:
    """Score minimum requis pour émettre un signal (override par symbole)."""
    return get_sym_override(sym, "score_min", SCORE_MIN_REQUIRED)
