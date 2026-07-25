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


def decide(symbol: str, df_ltf: Optional[pd.DataFrame], df_htf: Optional[pd.DataFrame], *,
           ltf_tf: str, htf_tf: str, venue: str, now: Optional[datetime] = None,
           run_emotion: bool = True):
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
                           venue=venue, now=now, run_emotion=run_emotion)
    decision = cg.evaluate(feats, require_edge=False)   # DÉMO/EXPLORE : on teste pour mesurer
    return decision, feats


def _summary(symbol: str, ltf_tf: str, htf_tf: str, venue: str,
             decision, feats: dict, placed: Optional[dict],
             levels: Optional[dict] = None, reference: Optional[dict] = None,
             aggressive: Optional[dict] = None) -> dict:
    """Résumé sérialisable d'une décision (pour la route/dashboard)."""
    tr = feats.get("_trace") or {}
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
                   entry_gate: Optional[Callable] = None) -> dict:
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
            df_ltf = await asyncio.to_thread(rates_fn, symbol, ltf_tf, _N_BARS)
            df_htf = await asyncio.to_thread(rates_fn, symbol, htf_tf, _N_BARS)
            # FLUIDITÉ : `decide` (build_feats = indicateurs/SMC/émotion, pandas) et `_atr`
            # sont du calcul LOURD. Les exécuter inline gelait la boucle asyncio pendant tout
            # le cycle (27 symboles) → cortex/dashboard/JARVIS/flux temps réel bloqués plusieurs
            # secondes. On les déporte comme le font déjà consensus (_scan_one) et lead/lag.
            decision, feats = await asyncio.to_thread(
                decide, symbol, df_ltf, df_htf, ltf_tf=ltf_tf,
                htf_tf=htf_tf, venue=venue, now=now)

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
            if decision.entered:
                if atr is None:
                    placed = {"sent": False, "reason": "ATR_UNAVAILABLE"}
                elif not gate.allow:
                    placed = {"sent": False, "reason": "BRAIN_GATE_BLOCK", "gate": gate_info}
                else:
                    side = "long" if gate.side > 0 else "short"
                    res = await place_fn(symbol, side, atr,
                                         sl_atr_mult=sl_atr_mult, tp_atr_mult=tp_atr_mult,
                                         engine="confluence", size_factor=gate.conviction)
                    placed = res if isinstance(res, dict) else {"sent": False, "reason": "DEMO_DISARMED"}
                    if placed.get("sent"):
                        placed["gate"] = gate_info
                        report["placed"].append({"symbol": symbol, "side": side, "atr": atr,
                                                  "lot": placed.get("lot"), "price": placed.get("price"),
                                                  "gate_source": gate.source})

            # AGRESSIF (phase de test) : setup structuré incomplet, hors veto émotion/coût.
            # Détecté TOUJOURS (data) ; exécuté seulement si `aggressive_exec` ET feu vert cerveau.
            aggressive = _aggressive_eligible(decision, feats, aggressive_min)
            if aggressive:
                aggressive["gate"] = gate_info
            if aggressive and aggressive_exec and atr is not None and (placed is None or not placed.get("sent")):
                if not gate.allow:
                    aggressive["placed"] = {"sent": False, "reason": "BRAIN_GATE_BLOCK", "gate": gate_info}
                else:
                    aside = "long" if gate.side > 0 else "short"
                    ares = await place_fn(symbol, aside, atr, sl_atr_mult=sl_atr_mult,
                                          tp_atr_mult=tp_atr_mult, engine="confluence-aggr",
                                          size_factor=gate.conviction)
                    aggressive["placed"] = ares if isinstance(ares, dict) else {"sent": False, "reason": "DEMO_DISARMED"}
                    if aggressive["placed"].get("sent"):
                        report["placed"].append({"symbol": symbol, "side": aside, "atr": atr,
                                                  "lot": aggressive["placed"].get("lot"),
                                                  "price": aggressive["placed"].get("price"),
                                                  "mode": "aggressive", "gate_source": gate.source})

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
    return {
        "heartbeat": dict(HEARTBEAT),
        "symbols": LAST_DECISION,
        "recent": list(RECENT)[-50:],
    }
