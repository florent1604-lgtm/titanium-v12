"""core/confluence_demo_engine.py — MODIFICATIONS pour intégrer DecisionKernel

LIGNE ~150-270 : Modifier run_once() pour appeler DecisionKernel
"""

# ============================================================================
# À AJOUTER en haut du fichier (après imports existants) :
# ============================================================================

"""
from core.decision_kernel import build_verdict, cache_verdict
"""

# ============================================================================
# À MODIFIER dans run_once() - section placement (ligne ~234-250) :
# ============================================================================

"""
AVANT (logique locale) :
    placed = None
    if decision.entered:
        if atr is None:
            placed = {"sent": False, "reason": "ATR_UNAVAILABLE"}
        elif not gate.allow:  # brain_gate appelé ici localement
            placed = {"sent": False, "reason": "BRAIN_GATE_BLOCK", "gate": gate_info}
        else:
            res = await place_fn(symbol, side, atr, ...)
            placed = res

APRÈS (via DecisionKernel) :
"""

async def run_once(symbols_cfg, *, now: Optional[datetime] = None,
                   rates_fn: Optional[Callable] = None,
                   place_fn: Optional[Callable[..., Awaitable]] = None,
                   notify_fn: Optional[Callable[..., Awaitable]] = None,
                   ref_fn: Optional[Callable] = None,
                   sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.0,
                   tp_ladder=(1.5, 2.5, 4.0),
                   aggressive_min: int = 4, aggressive_exec: bool = False,
                   entry_gate: Optional[Callable] = None) -> dict:
    """Un passage sur tous les symboles configurés — AVEC DecisionKernel."""
    
    now = now or datetime.now(timezone.utc)
    t0 = time.monotonic()

    # ... setup existant ...

    report = {"ts": now.isoformat(), "decisions": [], "placed": []}
    n_errors = 0
    
    from core.decision_kernel import build_verdict, cache_verdict

    for cfg in symbols_cfg:
        symbol = cfg.get("symbol")
        ltf_tf = cfg.get("ltf", "M15")
        htf_tf = cfg.get("htf", "H4")
        venue = cfg.get("venue", "cfd")
        try:
            # ... data loading existant ...
            df_ltf = await asyncio.to_thread(rates_fn, symbol, ltf_tf, _N_BARS)
            df_htf = await asyncio.to_thread(rates_fn, symbol, htf_tf, _N_BARS)
            
            decision, feats = await asyncio.to_thread(
                decide, symbol, df_ltf, df_htf, ltf_tf=ltf_tf,
                htf_tf=htf_tf, venue=venue, now=now)
            
            atr = await asyncio.to_thread(_atr, df_ltf, ltf_tf, now)
            entry = (feats.get("_trace") or {}).get("ref_price")
            levels = _levels(entry, decision.side, atr, sl_atr=sl_atr_mult, tp_ladder=tp_ladder)
            
            # ... reference binance existant ...
            reference = None
            if ref_fn is not None and venue == "crypto":
                try:
                    bp = await asyncio.to_thread(ref_fn, symbol)
                    # ... code existant ...
                except Exception:
                    reference = None
            
            # ========== NOUVELLE : DÉCISION KERNEL ==========
            verdict = build_verdict(
                symbol,
                confluence_result={
                    "available": bool(feats.get("data_valid")),
                    "side": int(decision.side or 0),
                    "criteria": {g.name: g.passed for g in (decision.gates or [])},
                },
                scoring_result=None,  # confluence n'a pas scoring
                emotion=feats.get("emotion"),
                strategy="confluence",
                notional_eur=atr * 100 if atr else 0,
                engine_equity=1000,  # Défaut si indisponible
            )
            
            # Sauvegarder pour dashboard
            cache_verdict(symbol, verdict)
            
            # ========== PLACEMENT (via verdict du Kernel) ==========
            placed = None
            if verdict.allow and verdict.side != 0:
                # Kernel autorise → placer l'ordre
                if atr is None:
                    placed = {"sent": False, "reason": "ATR_UNAVAILABLE"}
                else:
                    side = "long" if verdict.side > 0 else "short"
                    res = await place_fn(
                        symbol, side, atr,
                        sl_atr_mult=sl_atr_mult,
                        tp_atr_mult=tp_atr_mult,
                        engine="confluence",
                        size_factor=verdict.conviction
                    )
                    placed = res if isinstance(res, dict) else {"sent": False, "reason": "DEMO_DISARMED"}
                    
                    if placed.get("sent"):
                        report["placed"].append({
                            "symbol": symbol,
                            "side": side,
                            "atr": atr,
                            "lot": placed.get("lot"),
                            "price": placed.get("price"),
                            "conviction": verdict.conviction,
                            "kernel_source": "confluence",
                        })
            else:
                # Kernel refuse → journaliser
                reason = verdict.reason_codes[0] if verdict.reason_codes else "UNKNOWN"
                placed = {
                    "sent": False,
                    "reason": f"KERNEL_BLOCK:{reason}",
                }
            
            # ... rest of existing code for summary/notification ...
            summary = _summary(symbol, ltf_tf, htf_tf, venue, decision, feats, placed,
                               levels, reference, aggressive)
            summary["kernel"] = {
                "allow": verdict.allow,
                "side": verdict.side,
                "conviction": verdict.conviction,
                "reason_codes": list(verdict.reason_codes),
            }
            
        except Exception as exc:
            n_errors += 1
            summary = {"symbol": symbol, "verdict": "ERROR", "error": repr(exc),
                       "decided_at": now.isoformat()}
        
        # ... rest of loop ...
        LAST_DECISION[symbol] = summary
        RECENT.append(summary)
        report["decisions"].append(summary)
        
        try:
            await notify_fn(symbol, summary)
        except Exception:
            pass
    
    # ... return report ...
    return report
