"""core/state_builder.py — mappe la sortie du chemin de confluence vers le socle N0.
Réorg Phase 1.4 (27/07/2026) : premier point d'ADOPTION du SystemState + journal unifié.

`build_system_state(...)` est un mapper PUR (feats dict + objet decision → SystemState) ; il
n'importe aucun module métier (invariant #6 : il ne connaît que `core.state`). `journal_cycle(...)`
assemble l'état, le journalise (signal accepté/refusé, décision, fill, fantôme) et le retourne.

But : que le chemin de décision RÉEL commence à écrire dans le socle, sans changer sa logique.
Fail-safe : tout est défensif ; journaliser ne doit jamais casser un cycle.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.state import SystemState, TFFrame, new_state


def _passed_pillars(decision) -> int:
    gates = getattr(decision, "gates", None) or []
    return sum(1 for g in gates if getattr(g, "passed", False)
               and getattr(g, "name", "") != "data_valid")


def _emotion_block(feats: Dict[str, Any]):
    emo = feats.get("emotion") if isinstance(feats, dict) else None
    if not isinstance(emo, dict):
        return {}
    return {
        "available": bool(emo.get("available", True)),
        "label": emo.get("label"),
        "valence": emo.get("valence"),
        "arousal": emo.get("arousal"),
        "intensity": emo.get("intensity"),
        "would_block": bool(emo.get("would_block") or emo.get("filter_block") or False),
        "would_fade": bool(emo.get("would_fade") or emo.get("contrarian_bias") or False),
    }


def build_system_state(*, symbol: str, venue: str, ltf: str, feats: Dict[str, Any],
                       decision, correlation_id: Optional[str] = None,
                       atr: Optional[float] = None, price: Optional[float] = None) -> SystemState:
    """Mapper PUR : construit un SystemState à partir des features + de la décision confluence."""
    feats = feats or {}
    corr = correlation_id or str(getattr(decision, "decision_id", None) or f"{symbol}-{id(decision)}")
    if price is None:
        try:
            price = float((feats.get("_trace") or {}).get("ref_price"))
        except (TypeError, ValueError):
            price = None

    st = new_state(corr, symbol=symbol, venue=venue)
    st.market.price = price
    st.market.operational_tf = ltf
    if ltf:
        st.market.frames[ltf] = TFFrame(tf=ltf, last_close=price, atr=atr)

    st.scoring.n_pillars = _passed_pillars(decision)
    st.scoring.side = int(getattr(decision, "side", 0) or 0)
    st.scoring.score = float(st.scoring.n_pillars)

    st.regime.trend = int(feats.get("trend") or 0)
    # Pôle geometrix (Phase 5) : mapper les VRAIES clés de feats["geometric"]
    # (branch/curvature/lyapunov/fisher/topology_alert), pas des clés inexistantes.
    geo = feats.get("geometric") if isinstance(feats.get("geometric"), dict) else {}
    st.regime.geo_available = bool(geo.get("available"))
    st.regime.regime = geo.get("branch")
    st.regime.curvature = geo.get("curvature")
    st.regime.lyapunov_horizon = geo.get("lyapunov")
    st.regime.fisher_distance = geo.get("fisher")
    st.regime.topology_alert = bool(geo.get("topology_alert"))
    st.regime.dominant_cycle_bars = geo.get("lyapunov")          # horizon ≈ échelle dominante locale

    for k, v in _emotion_block(feats).items():
        setattr(st.emotion, k, v)

    # FLUX AFFÉRENTS CONTINUS (Florent 27/07) : alimente fondamentaux / exposition / equity /
    # coût aller-retour → le RiskGate décide enfin sur des données VIVANTES. Cache TTL (core/flux)
    # → pas de martelage. Fail-safe : jamais bloquant.
    try:
        from core import flux
        f = flux.fundamentals()
        st.fundamentals.risk_score = f.get("risk_score")
        st.fundamentals.level = f.get("level")
        st.fundamentals.would_block = bool(f.get("would_block"))
        st.fundamentals.would_reduce = bool(f.get("would_reduce"))
        ex = flux.exposure()
        st.risk.gross_exposure_pct = ex.get("gross_pct")
        st.risk.net_exposure_pct = ex.get("net_pct")
        st.risk.equity = (flux.account() or {}).get("equity")
        c = flux.roundtrip_cost(symbol, price)
        if c is not None:
            st.notes["roundtrip_cost"] = str(c)
    except Exception:
        pass

    st.pole_status = {
        "smc": "online", "spectral": "online" if geo.get("available") else "degraded",
        "emotion": "online" if st.emotion.available else "offline",
        "fundamentals": "online" if st.fundamentals.risk_score is not None else "degraded",
    }
    return st


def journal_cycle(*, symbol: str, venue: str, ltf: str, feats: Dict[str, Any], decision,
                  gate_allow: bool, gate_reason: str = "", placed: Optional[dict] = None,
                  aggressive: Optional[dict] = None, atr: Optional[float] = None,
                  price: Optional[float] = None) -> Optional[SystemState]:
    """Assemble le SystemState et le journalise dans le journal unifié. Fail-safe absolu."""
    try:
        st = build_system_state(symbol=symbol, venue=venue, ltf=ltf, feats=feats,
                                decision=decision, atr=atr, price=price)
        from core.journal import get_journal
        j = get_journal()

        placed_sent = bool((placed or {}).get("sent"))
        aggr = (aggressive or {}).get("placed") or {}
        aggr_sent = bool(aggr.get("sent"))
        accepted = placed_sent or aggr_sent

        j.record_signal(st, accepted=accepted)

        if accepted:
            verdict, reason = "ALLOW", "OK"
        elif not gate_allow:
            verdict, reason = "DENY", (gate_reason or "BRAIN_GATE_BLOCK")
        else:
            verdict = "DENY"
            reason = str((placed or {}).get("reason") or (aggr.get("reason")) or getattr(decision, "code", "") or "NO_TRADE")
        j.record_decision(st.correlation_id, verdict, reason=reason, symbol=symbol,
                          extra={"side": st.scoring.side, "n_pillars": st.scoring.n_pillars})

        if accepted:
            fill = placed if placed_sent else aggr
            # RATIONALE EXACT (Florent 27/07) : POURQUOI cette position a été prise — TOUS les
            # flux corrélés associés à la prise de position (piliers en place + tendance + régime
            # geometrix + fondamentaux + coût + émotion). Journalisé + mémorisé (Cloe) pour affiner.
            pillars_passed = [getattr(g, "name", "") for g in (getattr(decision, "gates", None) or [])
                              if getattr(g, "passed", False) and getattr(g, "name", "") != "data_valid"]
            rationale = {
                "why": f"{'LONG' if st.scoring.side > 0 else 'SHORT'} sur {symbol} : "
                       f"{len(pillars_passed)} piliers [{', '.join(pillars_passed)}]",
                "pillars": pillars_passed, "n_pillars": st.scoring.n_pillars, "side": st.scoring.side,
                "trend_h4": st.regime.trend, "regime_geo": st.regime.regime,
                "lyapunov": st.regime.lyapunov_horizon, "topo_alert": st.regime.topology_alert,
                "fundamentals": {"score": st.fundamentals.risk_score, "level": st.fundamentals.level},
                "roundtrip_cost": st.notes.get("roundtrip_cost"),
                "exposure_gross_pct": st.risk.gross_exposure_pct, "equity": st.risk.equity,
                "emotion": {"label": st.emotion.label, "valence": st.emotion.valence,
                            "would_fade": st.emotion.would_fade},
                "engine": "aggressive" if (aggr_sent and not placed_sent) else "confluence",
                "lot": fill.get("lot"), "price": fill.get("price"),
                "sl": fill.get("sl"), "tp": fill.get("tp"), "ticket": fill.get("ticket") or fill.get("order"),
            }
            j.record_fill(st.correlation_id, symbol=symbol, payload=rationale)
            # Cloe MÉMORISE le rationale (accumulation → débrief après clôture, cf. tools/position_debrief).
            try:
                from core.cloe import get_cloe
                get_cloe().log_analysis(
                    f"ENTREE {rationale['why']} | trend={st.regime.trend} regime={st.regime.regime} "
                    f"fond={st.fundamentals.level} cout={st.notes.get('roundtrip_cost')} "
                    f"emotion={st.emotion.label} lot={fill.get('lot')}",
                    meta={"kind": "entry_rationale", "symbol": symbol, "ticket": rationale["ticket"],
                          "correlation_id": st.correlation_id})
            except Exception:
                pass
        else:
            # Trade FANTÔME : on garde la trace d'un signal directionnel REFUSÉ (dataset non censuré).
            if st.scoring.side != 0:
                j.record_ghost(st.correlation_id, symbol=symbol,
                               payload={"side": st.scoring.side, "reason": reason,
                                        "price": price, "n_pillars": st.scoring.n_pillars})
        return st
    except Exception:
        return None
