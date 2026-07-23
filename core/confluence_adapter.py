"""core/confluence_adapter.py — Adaptateur détecteurs → contrat `feats` des portes ET.

La GLUE entre les détecteurs (bougies, VPOC, Fib OTE, S/R, SMC, émotion) et
core/confluence_gate.evaluate(). Produit le dict `feats` attendu par les portes.

⚠️ PRÉPARATION — NON CÂBLÉ au pipeline de décision. On attend :
  (1) le vert de Codex sur la re-review (lot 1..4 + ce lot correctif) ;
  (2) le durcissement lot 2 (VPOC/Fib/SR, ob_status touch→break) ;
  (3) le go prod de Florent.
Tant que ces 3 conditions ne sont pas remplies, aucun appelant de production.

Contrat d'entrée : df_ltf (TF d'entrée), df_htf (TF supérieure), prix courant, symbole,
venue. FAIL-CLOSED de bout en bout (red-team Codex 17/07) :
  · closed_bars.closed_only  → retire la bougie en formation (jamais de repaint) ;
  · closed_bars.validate_frame → index monotone/unique, OHLC finies/cohérentes, fraîcheur ;
  · cohérence temporelle : `decided_at` commun, as-of par pilier, alignement HTF/LTF ;
  · un détecteur en échec → pilier absent (donc BLOCK côté portes), jamais fausse validation.

Le `edge_ok` n'est PAS forcé à True (c'était un fail-OPEN) : il vaut None (inconnu) tant
que le LABO n'a pas mesuré l'edge. En PROD les portes bloquent sans edge prouvé ; en
DÉMO/EXPLORE (require_edge=False) on prend le trade sur MT5 pour MESURER (consigne Florent).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

import pandas as pd

from core import closed_bars, volume_profile, fib_ote, sr_levels, candlestick_engine as ce
from core import smc_engine as smc

ADAPTER_VERSION = "1.2.0"


def _weekend_block(now: datetime, venue: str) -> bool:
    """Frais du vendredi soir / hold week-end (règle Florent). Crypto spot = 24/7,
    aucun swap → jamais bloqué. CFD/MT5 → vendredi soir + week-end."""
    if venue == "crypto":
        return False
    wd = now.weekday()                 # 0=lundi … 6=dimanche
    if wd in (5, 6):
        return True
    return wd == 4 and now.hour >= 20  # vendredi ≥ 20h UTC


def _trend(df_htf: pd.DataFrame) -> int:
    try:
        ema = smc.compute_ema200(df_htf["close"])
        px = float(df_htf["close"].iloc[-1])
        return 1 if px > ema else (-1 if px < ema else 0)
    except Exception:
        return 0


def _fvg_actionnable(df: pd.DataFrame, side: str, price: float, tol: float) -> bool:
    """Une FVG ne compte que si elle est ACTIVE et PROCHE du prix courant.

    Le bug d'origine (revue Codex 22/07) : `bool(detect_fvg(df, side))` était vrai
    dès qu'UNE FVG existait N'IMPORTE OÙ dans l'historique. Un historique mature en
    contient des deux sens → bull ET bear vrais → pilier toujours à 0 (0/20 mesuré).
    Ici, la porte n'est franchie que si le prix INTERAGIT avec la zone maintenant.
    """
    if not (price > 0) or not (tol > 0):
        return False
    for bot, top in smc.detect_fvg(df, side):
        lo, hi = (bot, top) if bot <= top else (top, bot)
        if (lo - tol) <= price <= (hi + tol):
            return True
    return False


def _liquidity(df: pd.DataFrame, price: float, atr: float) -> int:
    """Liquidité : +1 (haussier), −1 (baissier), 0 (aucun/ambigu).

    Deux signaux directionnels, chacun RÉCENT et NORMALISÉ :
      · sweep de liquidité (mèche + reconquête), tampon en fraction d'ATR ;
      · FVG ACTIVE au contact du prix (pas une FVG quelconque de l'historique).
    L'OB n'entre PAS ici : il appartient au pilier OTE/OB (pas de double comptage).
    """
    try:
        tol = smc.compute_fib_tolerance(df.tail(min(50, len(df))), price, atr) if price > 0 else 0.0
        bull = smc.detect_liquidity_sweep(df, "ACHAT", atr) or _fvg_actionnable(df, "ACHAT", price, tol)
        bear = smc.detect_liquidity_sweep(df, "VENTE", atr) or _fvg_actionnable(df, "VENTE", price, tol)
        if bull and not bear:
            return 1
        if bear and not bull:
            return -1
        return 0
    except Exception:
        return 0


def _ote_ob(df: pd.DataFrame, price: float, fib_ctx: dict) -> int:
    """Pilier OTE/OB : +1 / −1 / 0. Le NOM promet deux conditions, on les exige.

    Le bug d'origine (revue Codex 22/07) : la porte « ote_ob » ne testait que
    `fib_ctx.in_ote` — aucun Order Block, malgré son nom. Ici, le prix doit être
    dans la golden zone OTE [0.618–0.786] NON invalidée ET aligné sur un OB actif
    (non cassé) du même côté. `has_ob_or_fvg_alignment` porte le statut de l'OB ;
    on n'accepte QUE les statuts d'OB (intact/tested), la FVG restant au pilier
    liquidité pour ne pas compter deux fois la même zone.
    """
    try:
        if not (price > 0) or not fib_ctx.get("available") or not fib_ctx.get("in_ote"):
            return 0
        if fib_ctx.get("invalidated"):
            return 0
        direction = int(fib_ctx.get("direction") or 0)
        if direction == 0:
            return 0
        smc_side = "ACHAT" if direction > 0 else "VENTE"
        aligned, status, _q = smc.has_ob_or_fvg_alignment(df, smc_side, price)
        if aligned and status in ("intact", "tested"):
            return direction
        return 0
    except Exception:
        return 0


def _emotion_feats(symbol: str) -> dict:
    try:
        from emotion.market_context import emotion_for
        st = emotion_for(symbol)
        if not st.available:
            return {"filter_block": None, "stale": True, "confidence": 0.0, "wait": True}
        fb = {"long": 1, "short": -1}.get(st.filter_block)
        return {"filter_block": fb, "stale": st.stale,
                "confidence": st.confidence, "wait": bool(st.stale)}
    except Exception:
        return {"filter_block": None, "stale": True, "confidence": 0.0, "wait": True}


def _last_close_time(df: pd.DataFrame, timeframe: str) -> Optional[pd.Timestamp]:
    """Heure de CLÔTURE de la dernière bougie (index = heure d'ouverture UTC)."""
    try:
        dur = closed_bars.bar_duration_minutes(timeframe)
        last_open = pd.Timestamp(df.index[-1])
        if last_open.tzinfo is None:
            last_open = last_open.tz_localize("UTC")
        return last_open + pd.Timedelta(minutes=dur) if dur else last_open
    except Exception:
        return None


def _setup_side(sr_ctx: dict) -> Optional[int]:
    """Sens porté par le SETUP (conseil archi Codex : le side vient du setup, la tendance
    reste un contexte). Sur un SUPPORT → setup long ; sur une RÉSISTANCE → setup
    short. La bougie et l'OTE restent des portes ET indépendantes : elles ne doivent pas
    servir à inventer le setup qu'elles sont ensuite censées confirmer."""
    if not sr_ctx.get("available") or sr_ctx.get("on_level") is None:
        return None
    kind = sr_ctx.get("on_level_kind")
    if kind == "support":
        return +1
    if kind == "resistance":
        return -1
    return None


def _setup_family(setup_side: Optional[int], trend: int) -> Optional[str]:
    """Famille explicite du setup produit par l'adaptateur.

    Une direction alignée sur la tendance est une continuation ; une direction opposée
    (ou une tendance encore indéterminée) est reviewée comme reversal, avec la tendance
    conservée dans la trace comme contexte et non comme interdiction d'expérimenter.
    """
    if setup_side not in (-1, 1):
        return None
    return "continuation" if trend in (-1, 1) and setup_side == trend else "reversal"


def build_feats(df_ltf: Optional[pd.DataFrame], df_htf: Optional[pd.DataFrame], *,
                price: float, symbol: str, timeframe: str, htf_timeframe: str,
                venue: str = "crypto", now: Optional[datetime] = None,
                run_emotion: bool = True) -> dict:
    """Détecteurs → dict `feats` pour confluence_gate.evaluate(). FAIL-CLOSED sur les
    données non clôturées, invalides, gelées ou temporellement incohérentes."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # (1) Bougies clôturées uniquement, puis (2) sanité + fraîcheur (red-team Codex).
    ltf = closed_bars.closed_only(df_ltf, timeframe, now)
    htf = closed_bars.closed_only(df_htf, htf_timeframe, now)
    if ltf is None or htf is None or len(ltf) < 20 or len(htf) < 20:
        return {"data_valid": False, "reason": "CLOSED_BARS_UNAVAILABLE"}
    ok_l, code_l = closed_bars.validate_frame(ltf, timeframe, now=now, min_len=20)
    ok_h, code_h = closed_bars.validate_frame(htf, htf_timeframe, now=now, min_len=20)
    if not ok_l or not ok_h:
        return {"data_valid": False, "reason": f"LTF:{code_l} HTF:{code_h}"}

    # (3) Cohérence temporelle : as-of par TF, alignement HTF/LTF, prix de référence closed-bar.
    ltf_close = _last_close_time(ltf, timeframe)
    htf_close = _last_close_time(htf, htf_timeframe)
    decided_at = ltf_close or pd.Timestamp(now)
    htf_ltf_aligned = True
    if ltf_close is not None and htf_close is not None:
        # la HTF clôturée ne doit pas être « en avance » sur la LTF (incohérence de flux)
        htf_ltf_aligned = htf_close <= ltf_close + pd.Timedelta(minutes=1)
    if not htf_ltf_aligned:
        return {"data_valid": False, "reason": "HTF_LTF_MISALIGNED"}
    ref_price = float(ltf["close"].iloc[-1])          # prix de décision = dernière clôture LTF

    trend = _trend(htf)

    # S/R (TF haute) + juste-prix (VPOC, TF haute) : zones structurantes.
    vprof = volume_profile.compute_profile(htf, window=min(300, len(htf)))
    sr_ctx = sr_levels.entry_context(htf, ref_price, volume_profile=vprof)
    vp_ctx = volume_profile.entry_context(htf, ref_price, window=min(300, len(htf)))

    # ATR LTF : sert à normaliser le sweep et la tolérance de proximité FVG/OB.
    atr_ltf = smc.compute_atr(ltf)

    # OTE (impulsion TF d'entrée) + OB actif requis (le nom « ote_ob » l'exige).
    fib_ctx = fib_ote.entry_context(ltf, ref_price)
    ote_dir = _ote_ob(ltf, ref_price, fib_ctx)

    cndl = ce.net_bias_on_df(ltf, uptrend=(trend > 0) if trend != 0 else None)
    candle_dir = int(cndl.get("direction") or 0)

    liquidity = _liquidity(ltf, ref_price, atr_ltf)
    emo = (_emotion_feats(symbol) if run_emotion
           else {"filter_block": None, "stale": False, "confidence": 1.0, "wait": False})

    setup_side = _setup_side(sr_ctx)
    setup_family = _setup_family(setup_side, trend)
    feats = {
        "data_valid": True,
        "trend": trend,
        "setup_side": setup_side,
        "setup_family": setup_family,
        "on_sr_level": bool(sr_ctx.get("on_level")) if sr_ctx.get("available") else False,
        "fair_value": bool(vp_ctx.get("on_fair_price_zone")) if vp_ctx.get("available") else False,
        "liquidity": liquidity,
        "ote": ote_dir,
        "candle": candle_dir,
        "emotion": emo,
        "cost": {"edge_ok": None,            # ⚠️ INCONNU tant que le LABO n'a pas mesuré (plus de fail-open)
                 "weekend_block": _weekend_block(now, venue)},
        "strengths": {
            "trend_sr": round(float(sr_ctx.get("on_level_strength", 0.0)), 3),
            "fair_value": 0.5 if vp_ctx.get("on_fair_price_zone") else 0.0,
            "liquidity": 0.6 if liquidity != 0 else 0.0,
            "ote_ob": 0.7 if ote_dir != 0 else 0.0,
            "candle_confirmed": abs(float(cndl.get("score", 0.0))),
        },
        # trace explicable (dashboard bougie-par-bougie) : reason-codes stables + horodatage.
        "_trace": {
            "version": ADAPTER_VERSION,
            "symbol": symbol, "venue": venue,
            "decided_at": decided_at.isoformat(),
            "ref_price": ref_price, "price_input": float(price),
            "timeframes": {"ltf": timeframe, "htf": htf_timeframe},
            "as_of": {"ltf_close": ltf_close.isoformat() if ltf_close is not None else None,
                      "htf_close": htf_close.isoformat() if htf_close is not None else None,
                      "htf_ltf_aligned": htf_ltf_aligned},
            "setup": {"side": setup_side, "family": setup_family, "trend_context": trend},
            "pillars": {"sr": sr_ctx, "vpoc": vp_ctx, "fib": fib_ctx,
                        "candle": cndl, "liquidity": liquidity, "trend": trend},
        },
    }
    return feats
