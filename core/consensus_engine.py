"""Consensus read-only entre CONFLUENCE, SCORING /16 et ÉMOTION.

Le module ne connaît aucun exécuteur et n'expose aucune capacité de décision. Les
preuves corrélées sont rabattues dans des familles plafonnées avant agrégation.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from core import closed_bars


VERSION = "consensus-detection-1.0.0"
# ÉQUILIBRE COMMUN (décision Florent + calibration Hermes, 21/07/2026) : les cinq familles
# pèsent AUTANT. L'ancienne hiérarchie (structure 30 % + localisation 25 % = 55 %) était
# assumable pour un moteur structurel, mais ce n'est pas l'équilibre voulu : chaque élément
# du noyau de calcul est une pièce du puzzle, aucune ne domine, aucune n'est décorative.
FAMILY_WEIGHTS = {
    "structure": 0.20,
    "location_liquidity": 0.20,
    "timing": 0.20,
    "participation_regime": 0.20,
    "behavioral": 0.20,
}

# PLAFOND TRANSVERSAL DE L'ÉMOTION. À poids de familles ÉGAUX, l'émotion nourrit DEUX
# familles (arousal → participation/régime, valence → comportemental) : seule, elle pourrait
# donc piloter 40 % du score et redevenir le pilier décisionnaire par la bande — exactement
# ce que Florent a écarté. Seule preuve d'une famille, elle n'en porte donc que la MOITIÉ
# (0.20 × 0.5 = 10 % par famille, soit 20 % agrégés au maximum). Accompagnée de preuves
# INDÉPENDANTES, la famille peut atteindre son poids plein : l'émotion reste significative,
# jamais décorative, mais ne peut ni créer une entrée seule ni dominer le consensus.
_SOLO_ENGINE_CAP = {"emotion": 0.5}
_EPS = 1e-12
CRYPTO_BASES = {"BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "SOL", "DOGE", "BNB"}

LAST_RESULTS: dict[str, dict] = {}
RECENT: deque = deque(maxlen=200)
HEARTBEAT = {
    "last_cycle_at": None, "last_cycle_ok": None, "duration_ms": None,
    "n_results": 0, "n_errors": 0, "n_orders": 0,
}


def scoring_symbol(symbol: str) -> str:
    """Traduit uniquement les CFD crypto explicitement reconnus vers Binance."""
    sym = str(symbol or "").strip().upper()
    if "/" in sym:
        return sym
    if sym.endswith("USD") and sym[:-3] in CRYPTO_BASES:
        return f"{sym[:-3]}/USDT"
    return sym


def _direction(value) -> int:
    if value in (1, "ACHAT", "BUY", "LONG", "long"):
        return 1
    if value in (-1, "VENTE", "SELL", "SHORT", "short"):
        return -1
    return 0


def _ratio(criteria: dict, names: tuple[str, ...]) -> float:
    """Moyenne bornée d'un cluster corrélé : plusieurs indicateurs != plusieurs poids."""
    values = [1.0 if criteria.get(name) is True else 0.0 for name in names]
    return sum(values) / len(values) if values else 0.0


def _emotion_dict(value) -> dict:
    if isinstance(value, dict):
        out = dict(value)
    else:
        fields = ("available", "valence", "arousal", "label", "confidence", "stale",
                  "contrarian", "filter_block")
        out = {name: getattr(value, name, None) for name in fields}
    available = bool(out.get("available")) and not bool(out.get("stale"))
    confidence = out.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence)) if math.isfinite(confidence) else 0.0

    explicit = _direction(out.get("direction"))
    if not explicit:
        explicit = _direction(out.get("contrarian"))
    if not explicit:
        blocked = _direction(out.get("filter_block"))
        explicit = -blocked if blocked else 0
    if not explicit and available and confidence >= 0.5:
        try:
            valence = float(out.get("valence", 0.0))
        except (TypeError, ValueError):
            valence = 0.0
        if math.isfinite(valence) and abs(valence) >= 20.0:
            explicit = 1 if valence > 0 else -1
    out.update({"available": available, "confidence": round(confidence, 3),
                "direction": explicit if available else 0})
    return out


def _family(name: str, votes: dict[str, float]) -> dict:
    weight = FAMILY_WEIGHTS[name]
    clean = {engine: max(-1.0, min(1.0, float(vote)))
             for engine, vote in votes.items() if math.isfinite(float(vote))}
    nonzero = [v for v in clean.values() if abs(v) > 1e-12]
    net = sum(clean.values()) / len(clean) if clean else 0.0
    # Une preuve isolée ne reçoit que 60 % de la famille ; deux moteurs concordants
    # peuvent saturer la famille, jamais la dépasser.
    redundancy = 1.0 if len(nonzero) >= 2 else (0.6 if len(nonzero) == 1 else 0.0)
    contribution = max(-weight, min(weight, weight * net * redundancy))
    # Plafond transversal : si UNE SEULE source porte la famille et qu'elle est plafonnée
    # (l'émotion), elle n'en emporte qu'une fraction — voir _SOLO_ENGINE_CAP.
    solo = {engine for engine, value in clean.items() if abs(value) > _EPS}
    if len(solo) == 1:
        cap = _SOLO_ENGINE_CAP.get(next(iter(solo)))
        if cap is not None:
            limit = weight * cap
            contribution = max(-limit, min(limit, contribution))
    signs = {1 if value > 0 else -1 for value in nonzero}
    return {
        "weight": weight,
        "engines": sorted(clean),
        # `directional` = la famille porte-t-elle une PREUVE SIGNÉE non nulle ? Un moteur
        # qui répond « zéro » est DISPONIBLE mais n'apporte aucune évidence : distinction
        # indispensable pour ne pas transformer de la présence en taille de position.
        "directional": bool(nonzero),
        "votes": {k: round(v, 3) for k, v in clean.items()},
        "redundancy": round(redundancy, 3),
        "conflict": len(signs) > 1,
        "weighted_contribution": round(contribution, 4),
    }


def build_consensus(symbol: str, confluence: dict, scoring: dict, emotion) -> dict:
    """Agrège trois sorties déjà calculées. Fonction pure et non décisionnelle."""
    conf = dict(confluence or {})
    score = dict(scoring or {})
    emo = _emotion_dict(emotion or {})
    cc = dict(conf.get("criteria") or {})
    sc = dict(score.get("criteria") or {})
    cside_raw = _direction(conf.get("side")) if conf.get("available") else 0
    sside_raw = _direction(score.get("side")) if score.get("available") else 0
    eside = _direction(emo.get("direction")) if emo.get("available") else 0
    confluence_pillars = sum(bool(cc.get(name)) for name in
                             ("trend_sr", "fair_value", "liquidity", "ote_ob",
                              "candle_confirmed"))
    confluence_confirmed = bool(cside_raw and cc.get("trend_sr") and confluence_pillars >= 4)
    try:
        score_strength = float(score.get("score", 0)) / max(1.0, float(score.get("score_max", 16)))
    except (TypeError, ValueError):
        score_strength = 0.0
    scoring_confirmed = bool(sside_raw and score_strength >= 0.50)
    # Les votes par famille gardent la direction brute pour montrer les preuves faibles ;
    # l'accord inter-MOTEURS exige en revanche 4/5 structurels et >= 8/16.
    cside = cside_raw
    sside = sside_raw

    families = {}
    votes = {}
    if conf.get("available"):
        votes["confluence"] = cside * _ratio(cc, ("trend_sr",))
    if score.get("available"):
        votes["scoring"] = sside * _ratio(sc, ("EMA200_H4", "STRUCT_H2H1",
                                                     "ALIGN_H2H1", "EMA200_1D"))
    families["structure"] = _family("structure", votes)

    votes = {}
    if conf.get("available"):
        votes["confluence"] = cside * _ratio(cc, ("fair_value", "liquidity", "ote_ob"))
    if score.get("available"):
        votes["scoring"] = sside * _ratio(sc, ("OB_FVG_30M", "OB_FVG_15M_CONFIRM",
                                                     "LIQ_SWEEP", "DISPLACEMENT"))
    families["location_liquidity"] = _family("location_liquidity", votes)

    votes = {}
    if conf.get("available"):
        votes["confluence"] = cside * _ratio(cc, ("candle_confirmed",))
    if score.get("available"):
        votes["scoring"] = sside * _ratio(sc, ("REJET_15M", "TRIX_5M", "RSI_DIVERGENCE"))
    families["timing"] = _family("timing", votes)

    votes = {}
    if score.get("available"):
        votes["scoring"] = sside * _ratio(sc, ("ADX_REGIME", "DELTA_VOL", "VOL_SPIKE",
                                                     "ORDERBOOK_IMBALANCE", "ORDERBOOK_WALL"))
    if emo.get("available"):
        try:
            energy = min(1.0, max(0.0, float(emo.get("arousal", 0.0)) / 100.0))
        except (TypeError, ValueError):
            energy = 0.0
        votes["emotion"] = eside * emo["confidence"] * energy
    families["participation_regime"] = _family("participation_regime", votes)

    votes = {}
    if emo.get("available"):
        try:
            intensity = min(1.0, abs(float(emo.get("valence", 0.0))) / 100.0)
        except (TypeError, ValueError):
            intensity = 0.0
        votes["emotion"] = eside * emo["confidence"] * max(0.25, intensity)
    families["behavioral"] = _family("behavioral", votes)

    # DISPONIBILITÉ vs PREUVE — distinction introduite le 21/07/2026 (audit Hermes).
    # `available_weight` compte une famille dès qu'un moteur RÉPOND, même en votant zéro :
    # c'est une mesure de SANTÉ, elle ne dit rien de l'évidence. `directional_weight` ne
    # compte que les familles portant une preuve SIGNÉE non nulle : c'est elle, et elle
    # seule, qui a le droit de se transformer en TAILLE de position (cf. core/brain_gate).
    available_weight = sum(row["weight"] for row in families.values() if row["engines"])
    directional_weight = sum(row["weight"] for row in families.values() if row["directional"])
    n_directional_families = sum(1 for row in families.values() if row["directional"])
    net = sum(row["weighted_contribution"] for row in families.values())
    consensus_score = int(round(100.0 * net / available_weight)) if available_weight else 0
    consensus_score = max(-100, min(100, consensus_score))
    final_side = 1 if consensus_score > 0 else (-1 if consensus_score < 0 else 0)

    engine_directions = {
        "confluence": cside if confluence_confirmed else 0,
        "scoring": sside if scoring_confirmed else 0,
        "emotion": eside,
    }
    engine_directions = {k: v for k, v in engine_directions.items() if v}
    agreeing = sorted(k for k, v in engine_directions.items() if v == final_side)
    opposing = sorted(k for k, v in engine_directions.items() if final_side and v == -final_side)
    conflict = bool(opposing) or any(row["conflict"] for row in families.values())
    agreement = len(agreeing) >= 2 and not conflict
    total_weight = sum(FAMILY_WEIGHTS.values())
    coverage = round(available_weight / total_weight, 3)                      # disponibilité
    directional_coverage = round(directional_weight / total_weight, 3)        # PREUVE → taille
    if not final_side:
        status = "INSUFFICIENT"
    elif conflict:
        status = "CONFLICT"
    elif agreement and coverage >= 0.60:
        status = "CONFIRMED"
    else:
        status = "UNCONFIRMED"

    return {
        "version": VERSION,
        "symbol": symbol,
        "scoring_symbol": scoring_symbol(symbol),
        "status": status,
        "side": "long" if final_side > 0 else ("short" if final_side < 0 else "neutral"),
        "consensus_score": consensus_score,
        "coverage": coverage,                              # DISPONIBILITÉ (santé/observation)
        "directional_coverage": directional_coverage,      # PREUVE signée → sert à la TAILLE
        "n_directional_families": n_directional_families,  # nb de preuves indépendantes
        "agreement": agreement,
        "conflict": conflict,
        "agreeing_engines": agreeing,
        "opposing_engines": opposing,
        "engine_directions": engine_directions,
        "engine_confirmation": {
            "confluence": {"confirmed": confluence_confirmed,
                            "pillars": confluence_pillars, "minimum": 4,
                            "requires_trend_sr": True},
            "scoring": {"confirmed": scoring_confirmed,
                        "strength": round(score_strength, 3), "minimum": 0.50},
            "emotion": {"confirmed": bool(eside),
                        "confidence": emo.get("confidence", 0.0)},
        },
        "families": families,
        "m2_required": True,
        "decision_capability": False,
        "orders_capability": False,
    }


def _resample(df: Optional[pd.DataFrame], rule: str) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "v" in df.columns:
        agg["v"] = "sum"
    return df.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["open", "high", "low", "close"])


def _run_confluence(symbol, ltf, htf, *, ltf_tf, htf_tf, venue, now):
    from core.confluence_demo_engine import decide
    return decide(symbol, ltf, htf, ltf_tf=ltf_tf, htf_tf=htf_tf, venue=venue,
                  now=now, run_emotion=False)


def _run_scoring(symbol, frames):
    from core.scoring_engine import score_setup
    return score_setup(
        sym=scoring_symbol(symbol), df_h4=frames["H4"], df_1m=frames["M5"],
        df30=frames["M5"], df_h2=frames["H2"], df_h1=frames["H1"],
        df_m30=frames["M30"], df_m15=frames["M15"], df_m5=frames["M5"],
        df_1d=frames["D1"], delta_vol_state=None, futures_data_state=None,
        orderbook_analysis=None, spectral_features=None,
    )


def _scan_one(cfg: dict, rates_fn: Callable, emotion_fn: Callable, now: datetime) -> dict:
    symbol = str(cfg["symbol"])
    ltf_tf = str(cfg.get("ltf", "M15"))
    htf_tf = str(cfg.get("htf", "H4"))
    venue = str(cfg.get("venue", "cfd"))
    frames = {}
    for tf in ("M5", "M15", "H1", "H4", "D1"):
        raw = rates_fn(symbol, tf, 320)
        frames[tf] = closed_bars.closed_only(raw, tf, now)
        if frames[tf] is None or frames[tf].empty:
            raise ValueError(f"CLOSED_BARS_UNAVAILABLE:{tf}")
    frames["M30"] = _resample(frames["M15"], "30min")
    frames["H2"] = _resample(frames["H1"], "2h")

    decision, feats = _run_confluence(symbol, frames[ltf_tf], frames[htf_tf],
                                       ltf_tf=ltf_tf, htf_tf=htf_tf, venue=venue, now=now)
    score, side, confs, ctx = _run_scoring(symbol, frames)
    emotion = _emotion_dict(emotion_fn(scoring_symbol(symbol)))
    gates = {gate.name: bool(gate.passed) for gate in getattr(decision, "gates", [])}
    confluence = {"available": bool(feats.get("data_valid")),
                  "side": getattr(decision, "side", 0), "criteria": gates,
                  "verdict": getattr(decision, "verdict", "UNKNOWN"),
                  "code": getattr(decision, "code", "UNKNOWN")}
    criteria = {
        key: value for key, value in ctx.items()
        if isinstance(value, bool) and key.upper() == key
    }
    context = {
        key: value for key, value in ctx.items()
        if key not in criteria and key != "score_max"
    }
    scoring = {"available": side != "NEUTRE", "side": side, "score": score,
               "score_max": ctx.get("score_max", 16), "criteria": criteria,
               "context": context,
               "confirmations": list(confs)}
    result = build_consensus(symbol, confluence, scoring, emotion)
    result.update({"venue": venue, "ltf": ltf_tf, "htf": htf_tf,
                   "observed_at": now.isoformat(),
                   "engines": {"confluence": confluence, "scoring": scoring,
                               "emotion": emotion}})
    return result


async def run_once(symbols_cfg, *, now: Optional[datetime] = None,
                   rates_fn: Optional[Callable] = None,
                   emotion_fn: Optional[Callable] = None) -> dict:
    """Scanne un univers en lecture seule. Aucune dépendance de placement n'existe."""
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    if rates_fn is None:
        from data.mt5_provider import get_ohlcv
        rates_fn = get_ohlcv
    if emotion_fn is None:
        from emotion.market_context import emotion_for
        emotion_fn = emotion_for

    results = []
    errors = 0
    for cfg in symbols_cfg:
        symbol = str(cfg.get("symbol", ""))
        try:
            result = await asyncio.to_thread(_scan_one, cfg, rates_fn, emotion_fn, now)
        except Exception as exc:
            errors += 1
            result = {
                "version": VERSION, "symbol": symbol, "scoring_symbol": scoring_symbol(symbol),
                "status": "ERROR", "error": type(exc).__name__, "detail": str(exc)[:200],
                "observed_at": now.isoformat(), "m2_required": True,
                "decision_capability": False, "orders_capability": False,
            }
        LAST_RESULTS[symbol] = result
        RECENT.append(result)
        results.append(result)
    HEARTBEAT.update({
        "last_cycle_at": datetime.now(timezone.utc).isoformat(),
        "last_cycle_ok": errors == 0,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "n_results": len(results), "n_errors": errors, "n_orders": 0,
    })
    return {"results": results, "heartbeat": dict(HEARTBEAT)}


def status_snapshot() -> dict:
    return {
        "version": VERSION,
        "detection_only": True,
        "m2_required": True,
        "decision_capability": False,
        "orders_capability": False,
        "heartbeat": dict(HEARTBEAT),
        "symbols": dict(LAST_RESULTS),
        "recent": list(RECENT),
    }
