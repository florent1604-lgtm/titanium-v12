"""core/scoring_engine.py — Scoring /14 SMC avec poids adaptatifs et régime marché.

Critères (14) :
  1. EMA200_H4       — Biais H4 avec distance significative (>0.3% de l'EMA)
  2. STRUCT_H2H1     — Break of Structure H2 ou H1
  3. OB_FVG_30M      — Order Block / FVG aligné 30m
  4. OB_FVG_15M_CONF — Double confirmation 15m
  5. REJET_15M       — Bougie de rejet 5m/15m
  6. TRIX_5M         — TRIX signal cross
  7. ALIGN_H2H1      — Bonus H2+H1 alignés
  8. EMA200_1D       — Macro daily bias
  9. DELTA_VOL       — Pression acheteur/vendeur
 10. LIQ_SWEEP       — Liquidity sweep
 11. ADX_REGIME      — Régime TREND uniquement (RANGE ne valide plus)
 12. RSI_DIVERGENCE  — Divergence RSI haussière/baissière
 13. VOL_SPIKE       — Pic de volume confirmant l'entrée
 14. DISPLACEMENT    — Sweep + bougie d'impulsion (displacement)
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import math
import pandas as pd
from utils.config import (
    SCORE_CRITERIA, SCORE_MIN_REQUIRED, ADX_TREND_THRESHOLD,
    RSI_ENTRY_LONG, RSI_ENTRY_SHORT, ACTIVE_TF,
    get_sym_override,
    SPECTRAL_REGIME_FILTER, SPECTRAL_CYCLE_CRITERIA, SPECTRAL_DEPONDERATION_FACTOR,
)
from core.smc_engine import detect_sweep_with_displacement
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
    orderbook_analysis: Optional[Any] = None,
    spectral_features: Optional[Any] = None,
) -> Tuple[int, str, List[str], Dict[str, Any]]:
    """Scoring multi-timeframe SMC — score /16.

    Returns: (score_int, side, confirmations_list, context_dict)
    """
    weights   = dict(scoring_w or {c: 1.0 for c in SCORE_CRITERIA})

    # ── Phase 1 spectrale — dépondération des critères de cycle si pas de cycle net ──
    # Override par symbole (validé walk-forward indépendamment par actif — voir SYM_OVERRIDES),
    # fallback sur le flag global SPECTRAL_REGIME_FILTER pour tout symbole non couvert.
    # Ne casse rien tant que le flag résolu est à 0 (défaut) ou qu'aucun spectral_features
    # n'est fourni. N'ajoute aucun point au score max — pondère seulement les critères existants.
    spectral_filter_enabled = get_sym_override(sym, "spectral_regime_filter", SPECTRAL_REGIME_FILTER)
    if spectral_filter_enabled and spectral_features is not None and not spectral_features.has_cycle:
        for crit in SPECTRAL_CYCLE_CRITERIA:
            if crit in weights:
                weights[crit] = weights[crit] * SPECTRAL_DEPONDERATION_FACTOR

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

    if spectral_features is not None:
        ctx["spectral_phase_zone"] = spectral_features.phase_zone
        ctx["spectral_has_cycle"]  = spectral_features.has_cycle
        ctx["spectral_dominant_cycle"] = spectral_features.dominant_cycle

    def add(criterion: str, ok: bool, label: str) -> None:
        if ok:
            w = weights.get(criterion, 1.0)
            nonlocal weighted_score
            weighted_score += w
            confs.append(label)
        ctx[criterion] = ok

    # 1. EMA200_H4 — Distance significative (>0.3% de l'EMA)
    ema_distance_pct = abs(price - ema200_h4) / ema200_h4 if ema200_h4 > 0 else 0
    ema_distance_ok = ema_distance_pct > 0.003  # prix significativement au-dessus/en-dessous
    add("EMA200_H4", ema_distance_ok, f"EMA200-H4 {'haussier' if side == 'ACHAT' else 'baissier'} (dist={ema_distance_pct:.2%})")
    ctx["ema200_h4_distance_pct"] = round(ema_distance_pct * 100, 3)

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
    liq_sweep_ok = detect_liquidity_sweep(sweep_df, side)
    add("LIQ_SWEEP", liq_sweep_ok, "Liquidity sweep")

    # 9. ADX_REGIME — Uniquement TREND valide (RANGE ne confirme plus)
    regime = get_market_regime(_df(df_m30, df30), adx_threshold=adx_th)
    adx_ok = regime == "TREND"  # [FIX] RANGE ne valide plus — trop permissif
    add("ADX_REGIME", adx_ok, f"ADX régime {regime}")
    ctx["regime"] = regime
    ctx["adx"]    = compute_adx(_df(df_m30, df30))

    # ── 10. RSI_DIVERGENCE — Divergence haussière/baissière ──────────────────
    rsi_long_ok, rsi_short_ok, rsi_val = rsi_signal(df_entry, rsi_long, rsi_short)
    ctx["rsi"] = rsi_val
    rsi_div = rsi_divergence(df_entry)
    ctx["rsi_divergence"] = rsi_div
    rsi_div_ok = (
        (side == "ACHAT" and rsi_div == "bullish")
        or (side == "VENTE" and rsi_div == "bearish")
    )
    add("RSI_DIVERGENCE", rsi_div_ok, f"RSI divergence {rsi_div}")

    # ── 11. VOL_SPIKE — Pic de volume confirmant l'entrée ──────────────────
    vol_spike_ok = detect_volume_spike(df_entry)
    ctx["volume_spike"] = vol_spike_ok
    add("VOL_SPIKE", vol_spike_ok, "Volume spike")

    # ── 12. DISPLACEMENT — Sweep + bougie d'impulsion ─────────────────────
    displacement_ok = detect_sweep_with_displacement(sweep_df, side) if liq_sweep_ok else False
    add("DISPLACEMENT", displacement_ok, "Sweep + displacement")

    # ── 13. ORDERBOOK_IMBALANCE — Déséquilibre bid/ask institutionnel L2 ──
    ob_imb_ok = False
    ob_imb_label = "OB L2 n/a"
    if orderbook_analysis is not None:
        imb = orderbook_analysis.weighted_imbalance
        if side == "ACHAT" and imb > 1.5:
            ob_imb_ok = True
        elif side == "VENTE" and imb < 0.67:
            ob_imb_ok = True
        ob_imb_label = f"OB L2 imbalance {imb:.2f}"
        ctx["orderbook_imbalance"] = round(imb, 3)
    add("ORDERBOOK_IMBALANCE", ob_imb_ok, ob_imb_label)

    # ── 14. ORDERBOOK_WALL — Mur de liquidité confirmant la direction ─────
    ob_wall_ok = False
    ob_wall_label = "OB wall n/a"
    if orderbook_analysis is not None:
        if orderbook_analysis.wall_detected:
            wall_s = orderbook_analysis.wall_side
            wall_p = orderbook_analysis.wall_price
            # Mur bid + ACHAT = support | Mur ask + VENTE = résistance
            if (side == "ACHAT" and wall_s == "bid"):
                ob_wall_ok = True
            elif (side == "VENTE" and wall_s == "ask"):
                ob_wall_ok = True
            # Bonus : absorption = signal encore plus fort
            if orderbook_analysis.absorption_detected:
                ob_wall_ok = True
            ob_wall_label = f"OB wall {wall_s} @ {wall_p:.0f}"
        # Pénalité spoofing
        if orderbook_analysis.spoofing_score > 0.7:
            ob_wall_ok = False
            ob_wall_label += " [SPOOF]"
        ctx["orderbook_wall"] = orderbook_analysis.wall_side if orderbook_analysis.wall_detected else "none"
        ctx["orderbook_l2"] = orderbook_analysis.to_dict()
    add("ORDERBOOK_WALL", ob_wall_ok, ob_wall_label)

    # ── Score final ──────────────────────────────────────────────────────────
    score_max = len(SCORE_CRITERIA)
    raw_score = int(round(weighted_score))
    score = min(score_max, max(0, raw_score))

    ctx["score"]     = score
    ctx["score_max"] = score_max
    ctx["weighted"]  = round(weighted_score, 3)
    ctx["confs"]     = confs

    logger.debug("[SCORE] %s %s score=%d/%d (%s)", sym, side, score, score_max, ", ".join(confs))
    return score, side, confs, ctx


def get_score_min(sym: str) -> int:
    """Score minimum requis pour émettre un signal (override par symbole)."""
    return get_sym_override(sym, "score_min", SCORE_MIN_REQUIRED)
