"""core/entry_refine.py — RAFFINEMENT du point d'entrée par timeframes INFÉRIEURS.

Florent (25/07/2026) : « on analyse les opportunités sur les timeframes inférieurs en
parallèle pour affiner le meilleur point d'entrée. »

Un setup est décidé en haut (piliers de confluence M15/H4). Ce module DESCEND en M5/M1
pour AFFINER l'entrée — SANS jamais re-décider la direction :

  1. ANCRE le SL sur la micro-structure : dernier swing M5 d'invalidation le plus proche
     → stop plus SERRÉ = point d'entrée plus précis, meilleur R:R, et — à budget de risque
     égal — LOT PLUS GROS (lot = risque / distance_SL). Rejoint « augmente la taille du lot
     selon ton meilleur point d'entrée structuré ».
  2. Mesure le TIMING micro : micro-BOS + bougie de rejet M5, momentum M1 aligné → refine_score.
  3. Repère la ZONE d'entrée micro : FVG M5 non comblée la plus proche (prix dedans = idéal).

GARDE-FOUS :
  · le SL n'est jamais RESSERRÉ sous un plancher (sl_floor_frac × base) ni ÉLARGI au-dessus
    de la base → le risque reste borné ;
  · fail-safe total : toute erreur/donnée manquante → refinement NEUTRE (SL de base inchangé) ;
  · n'INVERSE ni ne CRÉE jamais un sens : il affine un sens déjà validé.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def _side_str(side_int: int) -> str:
    """Convention des détecteurs SMC : 'ACHAT' (long) / 'VENTE' (short)."""
    return "ACHAT" if int(side_int) > 0 else "VENTE"


def _micro_sl_anchor(df: Optional[pd.DataFrame], side_int: int, ref_price: float) -> Optional[float]:
    """Dernier swing M5 d'INVALIDATION le plus proche au-delà de l'entrée :
      · long  → swing low le plus HAUT encore SOUS le prix (stop juste dessous) ;
      · short → swing high le plus BAS encore AU-DESSUS du prix.
    None si pas de swing exploitable."""
    if df is None or len(df) < 12 or not {"high", "low"}.issubset(df.columns):
        return None
    try:
        from core.fib_ote import _swings
        highs = df["high"].to_numpy(float)
        lows = df["low"].to_numpy(float)
        sh, sl = _swings(highs, lows, k=2)
        if int(side_int) > 0:
            cands = [float(lows[i]) for i in sl if float(lows[i]) < ref_price]
            return max(cands) if cands else None   # le plus proche SOUS le prix
        cands = [float(highs[i]) for i in sh if float(highs[i]) > ref_price]
        return min(cands) if cands else None       # le plus proche AU-DESSUS du prix
    except Exception:
        return None


def refine(symbol: str, side_int: int,
           m5_df: Optional[pd.DataFrame], m1_df: Optional[pd.DataFrame], *,
           atr_ref: float, ref_price: float, base_sl_mult: float,
           sl_floor_frac: float = 0.6) -> Dict[str, Any]:
    """Affine l'entrée d'un setup dirigé. Retourne un dict fail-safe :
      applied, sl_mult (multiple d'ATR à utiliser), refine_score∈[0,1], micro_confirm,
      at_zone, entry_zone, sl_anchor, ltf, notes."""
    out: Dict[str, Any] = {
        "applied": False, "sl_mult": base_sl_mult, "refine_score": 0.0,
        "micro_confirm": False, "at_zone": False, "entry_zone": None,
        "sl_anchor": None, "ltf": [], "notes": [],
    }
    try:
        side_int = int(side_int)
        atr_ref = float(atr_ref or 0.0)
        ref_price = float(ref_price or 0.0)
        base_sl_mult = float(base_sl_mult or 0.0)
        if side_int == 0 or atr_ref <= 0 or ref_price <= 0 or base_sl_mult <= 0:
            return out
        side_str = _side_str(side_int)
        from core.smc_engine import detect_bos, detect_rejection_candle, detect_fvg_unfilled

        score = 0.0

        # 1) SL ancré sur la micro-structure M5 (resserrement borné).
        anchor = _micro_sl_anchor(m5_df, side_int, ref_price)
        if anchor is not None:
            sl_dist = abs(ref_price - anchor) + 0.10 * atr_ref      # buffer 10% ATR au-delà du swing
            mult = sl_dist / atr_ref
            floor = base_sl_mult * float(sl_floor_frac)
            mult = max(floor, min(base_sl_mult, mult))              # on ne resserre pas sous le plancher, on n'élargit pas
            out["sl_mult"] = round(mult, 3)
            out["sl_anchor"] = round(float(anchor), 6)
            out["applied"] = True
            out["ltf"].append("M5")
            if mult < base_sl_mult - 1e-9:
                out["notes"].append(f"SL {base_sl_mult:.2f}->{out['sl_mult']:.2f} ATR (swing M5)")

        # 2) Timing micro M5 : micro-BOS + bougie de rejet dans le sens.
        try:
            bos = bool(detect_bos(m5_df, side_str, lookback=20)) if m5_df is not None else False
        except Exception:
            bos = False
        try:
            rej = bool(detect_rejection_candle(m5_df, side_str)) if m5_df is not None else False
        except Exception:
            rej = False
        if bos:
            score += 0.40; out["notes"].append("micro-BOS M5")
        if rej:
            score += 0.20; out["notes"].append("rejet M5")
        out["micro_confirm"] = bool(bos or rej)

        # 3) Zone d'entrée micro : FVG M5 non comblée la plus proche du prix.
        try:
            zones = detect_fvg_unfilled(m5_df, side_str, lookback=60) if m5_df is not None else []
        except Exception:
            zones = []
        if zones:
            best = min(zones, key=lambda z: abs((float(z[0]) + float(z[1])) / 2.0 - ref_price))
            lo, hi = sorted((float(best[0]), float(best[1])))
            out["entry_zone"] = [round(lo, 6), round(hi, 6)]
            near = (lo - 0.15 * atr_ref) <= ref_price <= (hi + 0.15 * atr_ref)
            out["at_zone"] = bool(near)
            if near:
                score += 0.25; out["notes"].append("prix dans zone FVG M5")

        # 4) Momentum M1 : dernière bougie close dans le sens.
        if m1_df is not None and len(m1_df) >= 2 and {"open", "close"}.issubset(m1_df.columns):
            try:
                c0 = float(m1_df["close"].iloc[-1]); o0 = float(m1_df["open"].iloc[-1])
                if (side_int > 0 and c0 > o0) or (side_int < 0 and c0 < o0):
                    score += 0.15
                    if "M1" not in out["ltf"]:
                        out["ltf"].append("M1")
                    out["notes"].append("momentum M1 aligné")
            except Exception:
                pass

        out["refine_score"] = round(min(1.0, score), 3)
    except Exception as exc:  # fail-safe absolu : jamais casser un placement
        out["notes"].append(f"refine_error:{exc!r}")
    return out
