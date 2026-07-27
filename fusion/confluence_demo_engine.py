"""core/confluence_demo_engine.py — Moteur de CONFLUENCE en DÉMO MT5.

Câble la stack de détection (confluence_adapter → confluence_gate, mode EXPLORE) sur
l'exécuteur DÉMO MT5, pour OUVRIR de vraies positions sur le compte DÉMO et observer
la méthode de Florent en direct (dashboard « pourquoi » + appli MT5 iOS).

Sûr par construction :
  · désarmé par défaut (`CONFLUENCE_DEMO_ENABLED=0`) ; la boucle ne tourne pas ;
  · les ordres passent par `execution.demo_bridge.place_demo_async`, lui-même
    désarmé tant que `DEMO_EXEC_ENABLED≠1` et protégé par le MUR démo↔réel
    (refus absolu si le login n'est pas le compte démo attendu) ;
  · mode EXPLORE (`require_edge=False`) : on prend le trade pour MESURER (décision
    Florent), mais la confluence complète + l'émotion + le coût (week-end) restent
    exigés ; jamais d'entrée sur données non clôturées/incohérentes ;
  · `decide()` est PUR et testable ; `run_once()` a ses dépendances INJECTABLES
    (données, placement) → aucun accès réseau/MT5 dans les tests ;
  · fail-safe : une erreur sur un symbole est journalisée, les autres continuent.

RIEN n'est câblé au compte RÉEL. `run_once` ne place un ordre que si la décision est
ENTER ET que le pont démo est armé ET que le mur démo↔réel passe.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import pandas as pd

from core import confluence_adapter as ca
from core import confluence_gate as cg
from core import closed_bars, smc_engine

# Dernières décisions par symbole + historique récent (pour le dashboard « pourquoi »).
LAST_DECISION: dict = {}
RECENT: "deque" = deque(maxlen=200)
# Battement de cœur (réserve P1 Codex) : distingue « aucun signal » d'une boucle morte.
HEARTBEAT: dict = {"last_cycle_at": None, "last_cycle_ok": None, "duration_ms": None,
                   "n_decisions": 0, "n_placed": 0, "n_errors": 0}

_N_BARS = 300


def _atr(df_ltf: pd.DataFrame, timeframe: str, now: datetime) -> Optional[float]:
    """ATR (unités de prix) sur les bougies CLÔTURÉES uniquement. None si indisponible."""
    closed = closed_bars.closed_only(df_ltf, timeframe, now)
    if closed is None or len(closed) < 15:
        return None
    try:
        atr = float(smc_engine.compute_atr(closed))
        return atr if atr > 0 else None
    except Exception:
        return None


def _levels(entry, side, atr, *, sl_atr: float, tp_ladder) -> Optional[dict]:
    """Plan de trade : point d'ENTRÉE, SL et LADDER de TP (multiples d'ATR, orienté par
    le sens). R:R par TP = mult_TP / sl_atr. None si pas de direction/ATR/entrée valides."""
    try:
        entry = float(entry); atr = float(atr); side = int(side)
    except (TypeError, ValueError):
        return None
    if not (atr > 0) or side == 0 or not (entry > 0):
        return None
    sign = 1 if side > 0 else -1
    dec = 2 if entry >= 100 else 5                         # précision d'affichage indicative
    sl = round(entry - sign * sl_atr * atr, dec)
    tps = [{"n": i, "price": round(entry + sign * m * atr, dec), "atr_mult": m,
            "rr": round(m / sl_atr, 2) if sl_atr else None}
           for i, m in enumerate(tp_ladder, 1)]
    return {"side": "long" if side > 0 else "short", "entry": round(entry, dec),
            "sl": sl, "atr": round(atr, dec), "sl_atr": sl_atr, "tps": tps}


def _aggressive_eligible(decision, feats: dict, aggressive_min: int) -> Optional[dict]:
    """Un setup incomplet (`BLOCK_PILLAR_MISSING`) mais STRUCTURÉ (≥ aggressive_min piliers
    ∧ trend_sr ∧ direction) est agressif-éligible SEULEMENT si les MODÉRATEURS de veto ne
    s'y opposent pas : émotion `filter_block` (veto actif de ce côté) et coût week-end.
    P0 red-team Codex : ne JAMAIS exécuter en contournant l'émotion ; `WAIT_EMOTION_TIMING`
    (5/5 bloqué par le timing émotionnel) n'est PAS éligible. Retourne le dict `aggressive`
    ou None. PUR/testable."""
    side = int(getattr(decision, "side", 0) or 0)
    if getattr(decision, "entered", False) or side == 0:
        return None
    if getattr(decision, "code", "") != "BLOCK_PILLAR_MISSING":
        return None                       # émotion/coût WAIT ou BLOCK → non éligible
    gates = getattr(decision, "gates", []) or []
    gate_by = {g.name: g.passed for g in gates}
    n_pillars = sum(1 for g in gates if g.passed and g.name != "data_valid")
    if n_pillars < aggressive_min or not gate_by.get("trend_sr"):
        return None
    emo = feats.get("emotion") or {}
    cost = feats.get("cost") or {}
    fb = emo.get("filter_block")
    if fb is not None and int(fb) == side:
        return None                       # l'émotion s'oppose activement à ce côté → veto
    if cost.get("weekend_block"):
        return None
    return {"ready": True, "n_pillars": n_pillars, "side": side, "placed": None}


def _structure_size_factor(n_pillars: int, base_conviction: float) -> float:
    """Taille du lot selon la QUALITÉ DE STRUCTURE du point d'entrée (Florent 25/07) :
    plus le setup est structuré (piliers alignés), plus le lot est gros. Renvoie un
    facteur ∈ [0.20, 1.0] = le MEILLEUR entre la structure et la conviction cerveau.
    Le plafond de risque absolu reste DEMO_MIN_LOT_MAX_RISK_PCT (côté exécuteur)."""
    ladder = {0: 0.20, 1: 0.25, 2: 0.35, 3: 0.55, 4: 0.80, 5: 1.0}
    try:
        n = int(n_pillars)
    except (TypeError, ValueError):
        n = 0
    try:
        conv = float(base_conviction or 0.0)
    except (TypeError, ValueError):
        conv = 0.0
    struct = ladder.get(n, 1.0 if n >= 5 else 0.20)
    return max(0.20, min(1.0, max(struct, conv)))


def _counter_trend_block(feats: dict, side_int: int, df_htf, atr,
                         min_atr_dist: float) -> bool:
    """True si le setup FADE une tendance H4 NETTE → à ne PAS exécuter (Florent 25/07).

    La tendance est l'ORIENTATION immédiate du marché ; sur une tendance, le bot doit
    ANTICIPER les retournements (calcul geometrix), pas fader bêtement (Florent 27/07). Donc on
    ne bloque une contre-tendance QUE si :
      · tendance H4 non neutre (trend != 0) ET side == -trend (contre le sens) ET
      · AUCUN retournement prédit par geometrix (rupture topologique / dérive de Fisher / horizon
        de Lyapunov court = régime qui change) — sinon c'est un RETOURNEMENT ANTICIPÉ, on le PREND ET
      · prix nettement au-delà de l'EMA200 H4 (≥ min_atr_dist × ATR) = tendance VRAIMENT nette.
    Range (trend=0), continuation (side==trend) et retournement prédit restent autorisés. Fail-safe → False."""
    try:
        trend = int(feats.get("trend") or 0)
        side_int = int(side_int or 0)
        if trend == 0 or side_int == 0 or side_int == trend:
            return False
        # RETOURNEMENT PRÉDIT (geometrix) : une contre-tendance adossée à une rupture de régime
        # n'est PAS un fade — c'est un retournement anticipé → on ne bloque pas.
        geo = feats.get("geometric") if isinstance(feats.get("geometric"), dict) else {}
        import os as _os
        _fish_th = float(_os.getenv("REVERSAL_FISHER_TH", "1.0"))
        _lyap_th = int(_os.getenv("REVERSAL_LYAPUNOV_TH", "20"))
        _lyap = int(geo.get("lyapunov") or 999)
        if (bool(geo.get("topology_alert"))
                or float(geo.get("fisher") or 0.0) >= _fish_th
                or (0 < _lyap <= _lyap_th)):
            return False
        if df_htf is None or atr is None or float(atr) <= 0:
            return False
        from core import smc_engine as smc
        ema = smc.compute_ema200(df_htf["close"])
        if ema != ema:                       # NaN (< 200 barres) → tendance non fiable
            return False
        px = float(df_htf["close"].iloc[-1])
        return abs(px - float(ema)) >= float(min_atr_dist) * float(atr)
    except Exception:
        return False


def decide(symbol: str, df_ltf: Optional[pd.DataFrame], df_htf: Optional[pd.DataFrame], *,
           ltf_tf: str, htf_tf: str, venue: str, now: Optional[datetime] = None,
           run_emotion: bool = True,
           freshness_frames: Optional[dict] = None):
    """Décision de confluence en mode EXPLORE (démo). PUR. Retourne (Decision, feats)."""
    now = now or datetime.now(timezone.utc)
    price = None
    try:
        if df_ltf is not None and len(df_ltf):
            price = float(df_ltf["close"].iloc[-1])
    except Exception:
        price = None
    feats = ca.build_feats(df_ltf, df_htf, price=price if price is not None else 0.0,
                           symbol=symbol, timeframe=ltf_tf, htf_timeframe=htf_tf,
                           venue=venue, now=now, run_emotion=run_emotion,
                           freshness_frames=freshness_frames)
    decision = cg.evaluate(feats, require_edge=False)   # DÉMO/EXPLORE : on teste pour mesurer
    return decision, feats


def _summary(symbol: str, ltf_tf: str, htf_tf: str, venue: str,
             decision, feats: dict, placed: Optional[dict],
             levels: Optional[dict] = None, reference: Optional[dict] = None,
             aggressive: Optional[dict] = None) -> dict:
    """Résumé sérialisable d'une décision (pour la route/dashboard)."""
    tr = feats.get("_trace") or {}
    market_reason = str(feats.get("reason") or "")
    freshness = (tr.get("freshness") or {}) if isinstance(tr, dict) else {}
    freshness_codes = list((freshness.get("by_tf") or {}).values())
    if not feats.get("data_valid", False):
        if market_reason == "CLOSED_BARS_UNAVAILABLE":
            market_state = "closed"
        elif freshness_codes and all(code == "STALE" for code in freshness_codes):
            market_state = "closed"
        elif "STALE" in freshness_codes:
            market_state = "thin"
        else:
            market_state = "unavailable"
    elif decision.verdict == "ENTER":
        market_state = "open"
    elif decision.code == "WAIT_NO_SETUP":
        market_state = "open"
    else:
        market_state = "open"
    return {
        "symbol": symbol, "ltf": ltf_tf, "htf": htf_tf, "venue": venue,
        "reference": reference,    # ajustement Binance (prix + divergence) pour le crypto
        "aggressive": aggressive,  # setup agressif (incomplet mais structuré) — phase de test
        "verdict": decision.verdict, "side": decision.side, "code": decision.code,
        "mode": decision.mode, "setup_family": getattr(decision, "setup_family", ""),
        "rank": decision.rank, "decision_id": decision.decision_id,
        "decided_at": decision.decided_at,
        "reasons": list(decision.reasons),
        "gates": [{"name": g.name, "passed": g.passed, "code": g.code} for g in decision.gates],
        "data_valid": bool(feats.get("data_valid")),
        "market_status": {
            "state": market_state,
            "reason": market_reason or None,
            "freshness": (freshness.get("by_tf") or None),
            "forced": bool(freshness.get("forced")),
            "open": market_state == "open",
        },
        "levels": levels,          # point d'entrée + SL + ladder de TP
        "trace": tr,
        "placed": placed,
    }


def _blocked_gate():
    """Porte fermée par défaut si le cerveau est illisible (fail-safe : pas de trade)."""
    from core.brain_gate import BrainGate
    return BrainGate(False, 0, 0.0, "BRAIN", None, ("BRAIN_GATE_ERROR",))


async def run_once(symbols_cfg, *, now: Optional[datetime] = None,
                   rates_fn: Optional[Callable] = None,
                   place_fn: Optional[Callable[..., Awaitable]] = None,
                   notify_fn: Optional[Callable[..., Awaitable]] = None,
                   shadow_observer: Optional[Callable[..., object]] = None,
                   ref_fn: Optional[Callable] = None,
                   sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.0,
                   tp_ladder=(1.5, 2.5, 4.0),
                   aggressive_min: int = 4, aggressive_exec: bool = False,
                   entry_gate: Optional[Callable] = None,
                   refine_enabled: bool = False, refine_ltf: str = "M5",
                   refine_micro_tf: str = "M1", refine_sl_floor_frac: float = 0.6,
                   trend_align: bool = False, trend_align_min_atr: float = 0.25,
                   riskgate_enabled: bool = False) -> dict:
    """Un passage sur tous les symboles configurés.
    `symbols_cfg` : liste de dicts {symbol, ltf, htf, venue}.
    `rates_fn(symbol, tf, n) -> df|None` : défaut `mt5_provider.get_ohlcv` (données MT5).
    `place_fn(symbol, side, atr, sl_atr_mult, tp_atr_mult, engine) -> awaitable` :
       défaut `demo_bridge.place_demo_async` (armé seulement si DEMO_EXEC_ENABLED=1).
    `entry_gate(symbol, proposed_side) -> BrainGate` : PORTE NEURONALE (défaut
       `brain_gate.gate_entry`) — le CERVEAU (consensus) décide, le MASTER (Florent) prime.
       Aucune position n'est exécutée sans son feu vert ; l'observation, elle, continue.
    Retourne un rapport {ts, decisions:[...], placed:[...]}. Fail-safe par symbole."""
    now = now or datetime.now(timezone.utc)
    t0 = time.monotonic()

    if rates_fn is None:
        from data.mt5_provider import get_ohlcv as _get
        rates_fn = lambda s, tf, n: _get(s, tf, n)                       # noqa: E731
    if place_fn is None:
        from execution.demo_bridge import place_demo_async as _place
        place_fn = _place
    if notify_fn is None:
        from notifications.telegram import send_confluence_alert as _notify
        notify_fn = _notify
    if shadow_observer is None:
        try:
            from core.shadow_divergence import observe as _observe
            shadow_observer = _observe
        except Exception:
            shadow_observer = None
    if entry_gate is None:
        from core.brain_gate import gate_entry as entry_gate

    report = {"ts": now.isoformat(), "decisions": [], "placed": []}
    n_errors = 0

    for cfg in symbols_cfg:
        symbol = cfg.get("symbol")
        ltf_tf = cfg.get("ltf", "M15")
        htf_tf = cfg.get("htf", "H4")
        venue = cfg.get("venue", "cfd")
        try:
            freshness_tfs = ca.freshness_timeframes(ltf_tf, htf_tf)
            tf_frames = {}
            for tf in freshness_tfs:
                try:
                    tf_frames[tf] = await asyncio.to_thread(rates_fn, symbol, tf, _N_BARS)
                except Exception:
                    if tf in (ltf_tf, htf_tf):
                        raise
                    tf_frames[tf] = None
            df_ltf = tf_frames.get(ltf_tf)
            df_htf = tf_frames.get(htf_tf)
            # FLUIDITÉ : `decide` (build_feats = indicateurs/SMC/émotion, pandas) et `_atr`
            # sont du calcul LOURD. Les exécuter inline gelait la boucle asyncio pendant tout
            # le cycle (27 symboles) → cortex/dashboard/JARVIS/flux temps réel bloqués plusieurs
            # secondes. On les déporte comme le font déjà consensus (_scan_one) et lead/lag.
            decision, feats = await asyncio.to_thread(
                decide, symbol, df_ltf, df_htf, ltf_tf=ltf_tf,
                htf_tf=htf_tf, venue=venue, now=now, freshness_frames=tf_frames)

            # Plan de trade (entrée/SL/TP ladder) dès qu'un sens est défini, même en BLOCK :
            # Florent voit le point d'entrée et les TP projetés avant que ça devienne un trade.
            atr = await asyncio.to_thread(_atr, df_ltf, ltf_tf, now)
            entry = (feats.get("_trace") or {}).get("ref_price")
            levels = _levels(entry, decision.side, atr, sl_atr=sl_atr_mult, tp_ladder=tp_ladder)

            # Ajustement Binance (Florent : MT5 principal, ajusté à Binance). None hors crypto.
            reference = None
            if ref_fn is not None and venue == "crypto":
                try:
                    bp = await asyncio.to_thread(ref_fn, symbol)
                    bp = float(bp)
                    ep = float(entry)
                    if math.isfinite(bp) and bp > 0 and math.isfinite(ep) and ep > 0:
                        reference = {"source": "binance", "price": round(bp, 8),
                                     "divergence_pct": round((ep - bp) / bp * 100.0, 3)}
                except Exception:
                    reference = None

            # PORTE NEURONALE : le CERVEAU (consensus) décide, le MASTER (Florent) prime.
            # Gouverne les DEUX chemins de placement ci-dessous. L'observation continue quoi
            # qu'il arrive ; seule l'EXÉCUTION est conditionnée. Fail-safe (pas de gate = pas
            # de trade). `gate.side` = sens effectif (le master peut forcer le sens).
            try:
                gate = entry_gate(symbol, int(decision.side or 0))
            except Exception:  # noqa: BLE001 — cerveau illisible → on n'exécute pas
                gate = _blocked_gate()
            gate_info = {"allow": gate.allow, "source": gate.source, "verdict": gate.verdict,
                         "conviction": round(gate.conviction, 3), "reason_codes": list(gate.reason_codes)}

            placed = None
            # FILTRE DE TENDANCE (Florent 25/07) : ne pas EXÉCUTER un setup qui fade une tendance
            # H4 nette (cause des 6 shorts crypto stoppés pendant le rally). Master exempté.
            _eff_side = int(gate.side or decision.side or 0)
            counter_trend = bool(
                trend_align and gate.source != "MASTER"
                and _counter_trend_block(feats, _eff_side, df_htf, atr, trend_align_min_atr))
            # RISKGATE (N4, réorg) — PORTE UNIQUE consolidée, câblée en VETO ADDITIF (réversible
            # via flag). Elle reconsolide HALT / veto fondamentaux / circuit breaker / tendance /
            # coût / exposition en un seul verdict. Fail-OPEN sur erreur (un bug du RiskGate ne
            # casse jamais le trading : les gardes existants restent la sécurité). Master exempté.
            riskgate_deny = None
            riskgate_size = 1.0                       # correction de lot par piliers (barème RiskGate)
            if riskgate_enabled and gate.allow and gate.source != "MASTER" and atr is not None and _eff_side != 0:
                try:
                    from core.state_builder import build_system_state
                    from risk.riskgate import RiskGate
                    _rg_state = build_system_state(symbol=symbol, venue=venue, ltf=ltf_tf,
                                                   feats=feats, decision=decision, atr=atr, price=entry)
                    _rg_state.scoring.side = _eff_side
                    _rgd = RiskGate().evaluate(_rg_state)
                    riskgate_size = float(getattr(_rgd, "pillar_size", 1.0) or 1.0)
                    if _rgd.verdict == "DENY":
                        riskgate_deny = _rgd.reason
                except Exception:  # noqa: BLE001 — fail-open : gardes existants inchangés
                    riskgate_deny = None

            # Éligibilité AGRESSIVE calculée TÔT (pure, légère) : sert à savoir si un placement
            # est imminent, donc s'il vaut la peine de charger les TF inférieurs pour affiner.
            aggressive = _aggressive_eligible(decision, feats, aggressive_min)

            # RAFFINEMENT du point d'entrée par TF INFÉRIEURS (Florent 25/07). Chargé UNIQUEMENT
            # si un placement va réellement avoir lieu (setup complet, ou structuré + exécution
            # agressive armée) et cerveau OK. Affine le SL sur la micro-structure M5 → entrée plus
            # précise + lot plus gros à risque égal. N'INVERSE JAMAIS le sens (fail-safe).
            refine_info = None
            _rside = int(gate.side or decision.side or 0)
            _will_place = gate.allow and atr is not None and not counter_trend and not riskgate_deny and (
                decision.entered or bool(aggressive and aggressive_exec))
            if refine_enabled and _will_place and _rside != 0:
                try:
                    _m5 = await asyncio.to_thread(rates_fn, symbol, refine_ltf, _N_BARS)
                    _m1 = await asyncio.to_thread(rates_fn, symbol, refine_micro_tf, _N_BARS)
                    from core import entry_refine
                    refine_info = await asyncio.to_thread(
                        entry_refine.refine, symbol, _rside, _m5, _m1,
                        atr_ref=atr, ref_price=entry, base_sl_mult=sl_atr_mult,
                        sl_floor_frac=refine_sl_floor_frac)
                except Exception:  # noqa: BLE001 — raffinement non fatal : on garde le SL de base
                    refine_info = None
            _sl_mult = sl_atr_mult
            if isinstance(refine_info, dict) and refine_info.get("sl_mult"):
                _sl_mult = float(refine_info["sl_mult"])

            if decision.entered:
                if atr is None:
                    placed = {"sent": False, "reason": "ATR_UNAVAILABLE"}
                elif not gate.allow:
                    placed = {"sent": False, "reason": "BRAIN_GATE_BLOCK", "gate": gate_info}
                elif counter_trend:
                    placed = {"sent": False, "reason": "COUNTER_TREND_BLOCKED",
                              "trend": int(feats.get("trend") or 0), "side": _eff_side}
                elif riskgate_deny:
                    placed = {"sent": False, "reason": f"RISKGATE_DENY:{riskgate_deny}"}
                else:
                    side = "long" if gate.side > 0 else "short"
                    _npil = sum(1 for g in (getattr(decision, "gates", []) or [])
                                if g.passed and g.name != "data_valid")
                    res = await place_fn(symbol, side, atr,
                                         sl_atr_mult=_sl_mult, tp_atr_mult=tp_atr_mult,
                                         engine="confluence",
                                         size_factor=_structure_size_factor(_npil, gate.conviction) * riskgate_size,
                                         quality=_npil)
                    placed = res if isinstance(res, dict) else {"sent": False, "reason": "DEMO_DISARMED"}
                    if placed.get("sent"):
                        placed["gate"] = gate_info
                        if refine_info:
                            placed["refine"] = refine_info
                        report["placed"].append({"symbol": symbol, "side": side, "atr": atr,
                                                  "lot": placed.get("lot"), "price": placed.get("price"),
                                                  "sl_atr": _sl_mult, "gate_source": gate.source,
                                                  "refine_score": (refine_info or {}).get("refine_score")})

            # AGRESSIF (phase de test) : setup structuré incomplet, hors veto émotion/coût.
            # Détecté TOUJOURS (data) ; exécuté seulement si `aggressive_exec` ET feu vert cerveau.
            if aggressive:
                aggressive["gate"] = gate_info
            if aggressive and aggressive_exec and atr is not None and (placed is None or not placed.get("sent")):
                if not gate.allow:
                    aggressive["placed"] = {"sent": False, "reason": "BRAIN_GATE_BLOCK", "gate": gate_info}
                elif counter_trend:
                    aggressive["placed"] = {"sent": False, "reason": "COUNTER_TREND_BLOCKED",
                                            "trend": int(feats.get("trend") or 0), "side": _eff_side}
                elif riskgate_deny:
                    aggressive["placed"] = {"sent": False, "reason": f"RISKGATE_DENY:{riskgate_deny}"}
                else:
                    aside = "long" if gate.side > 0 else "short"
                    ares = await place_fn(symbol, aside, atr, sl_atr_mult=_sl_mult,
                                          tp_atr_mult=tp_atr_mult, engine="confluence-aggr",
                                          size_factor=_structure_size_factor(
                                              aggressive.get("n_pillars", 0), gate.conviction) * riskgate_size,
                                          quality=int(aggressive.get("n_pillars", 0)))
                    aggressive["placed"] = ares if isinstance(ares, dict) else {"sent": False, "reason": "DEMO_DISARMED"}
                    if refine_info:
                        aggressive["refine"] = refine_info
                    if aggressive["placed"].get("sent"):
                        report["placed"].append({"symbol": symbol, "side": aside, "atr": atr,
                                                  "lot": aggressive["placed"].get("lot"),
                                                  "price": aggressive["placed"].get("price"),
                                                  "sl_atr": _sl_mult, "mode": "aggressive",
                                                  "gate_source": gate.source,
                                                  "refine_score": (refine_info or {}).get("refine_score")})

            # Lot C2 (M2): observateur SHADOW additif sur chemin confluence_demo.
            # Zéro impact décision/exécution : best-effort, jamais bloquant.
            if shadow_observer is not None and int(decision.side or 0) != 0:
                try:
                    emitted = bool((placed or {}).get("sent")) or bool(((aggressive or {}).get("placed") or {}).get("sent"))
                    await asyncio.to_thread(
                        shadow_observer,
                        symbol,
                        int(decision.side or 0),
                        float(getattr(decision, "rank", 0.0) or 0.0),
                        emitted=emitted,
                        score_min=None,
                        extra={
                            "path": "confluence_demo",
                            "venue": venue,
                            "decision_code": getattr(decision, "code", ""),
                            "brain_source": gate.source,
                        },
                    )
                except Exception:
                    pass

            summary = _summary(symbol, ltf_tf, htf_tf, venue, decision, feats, placed,
                               levels, reference, aggressive)
            summary["brain"] = gate_info
            if refine_info:
                summary["refine"] = refine_info      # raffinement M5/M1 du point d'entrée

            # ADOPTION DU SOCLE N0 (réorg Phase 1.4) : le chemin de décision RÉEL écrit dans le
            # SystemState + le journal unifié (signal accepté/refusé, décision, fill, fantôme).
            # Additif et FAIL-SAFE : n'altère jamais la décision/exécution ci-dessus.
            try:
                from core.state_builder import journal_cycle
                journal_cycle(symbol=symbol, venue=venue, ltf=ltf_tf, feats=feats,
                              decision=decision, gate_allow=bool(gate.allow),
                              gate_reason=(gate_info.get("reason_codes") or [""])[0] if gate_info else "",
                              placed=placed, aggressive=aggressive, atr=atr, price=entry)
            except Exception:  # noqa: BLE001 — journaliser ne casse jamais un cycle
                pass
        except Exception as exc:  # noqa: BLE001 — fail-safe : un symbole ne casse pas le tour
            n_errors += 1
            summary = {"symbol": symbol, "verdict": "ERROR", "error": repr(exc),
                       "decided_at": now.isoformat()}

        LAST_DECISION[symbol] = summary
        RECENT.append(summary)
        report["decisions"].append(summary)
        try:
            await notify_fn(symbol, summary)          # Telegram (non fatal, gaté/anti-spam)
        except Exception:  # noqa: BLE001
            pass

    HEARTBEAT.update({
        "last_cycle_at": now.isoformat(),
        "last_cycle_ok": n_errors == 0,
        "duration_ms": round((time.monotonic() - t0) * 1000.0, 1),
        "n_decisions": len(report["decisions"]),
        "n_placed": len(report["placed"]),
        "n_errors": n_errors,
    })
    return report


def status_snapshot() -> dict:
    """État courant pour la route/dashboard : dernière décision par symbole + récents."""
    market_states = {"open": 0, "thin": 0, "closed": 0, "unavailable": 0}
    for summary in LAST_DECISION.values():
        state = ((summary or {}).get("market_status") or {}).get("state")
        if state in market_states:
            market_states[state] += 1
    return {
        "heartbeat": dict(HEARTBEAT),
        "symbols": LAST_DECISION,
        "recent": list(RECENT)[-50:],
        "market_status": {
            "state": (
                "mixed" if sum(1 for v in market_states.values() if v > 0) > 1
                else ("open" if market_states["open"] > 0
                      else "thin" if market_states["thin"] > 0
                      else "closed" if market_states["closed"] > 0
                      else "unavailable" if market_states["unavailable"] > 0
                      else "idle")
            ),
            "counts": market_states,
            "open_symbols": [sym for sym, summary in LAST_DECISION.items()
                              if ((summary or {}).get("market_status") or {}).get("state") == "open"],
            "thin_symbols": [sym for sym, summary in LAST_DECISION.items()
                              if ((summary or {}).get("market_status") or {}).get("state") == "thin"],
            "closed_symbols": [sym for sym, summary in LAST_DECISION.items()
                                if ((summary or {}).get("market_status") or {}).get("state") == "closed"],
            "unavailable_symbols": [sym for sym, summary in LAST_DECISION.items()
                                     if ((summary or {}).get("market_status") or {}).get("state") == "unavailable"],
        },
    }
