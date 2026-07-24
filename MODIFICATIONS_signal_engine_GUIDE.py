"""core/signal_engine.py — MODIFICATIONS pour intégrer DecisionKernel + DetectionCache

LIGNE ~30-40 : Ajouter imports
LIGNE ~95-150 : Modifier scan_symbol() pour appeler DecisionKernel + cache
"""

# ============================================================================
# À AJOUTER en haut du fichier (après imports existants) :
# ============================================================================

"""
from core.decision_kernel import build_verdict, cache_verdict
from core.detection_cache import get_or_detect
"""

# ============================================================================
# À MODIFIER dans scan_symbol() - remplacer la section score_setup() :
# ============================================================================

"""
AVANT (ligne ~100-120) :
    # Calculer le score
    score, side, ctx = score_setup(
        sym=sym, df_h4=df_h4, df_1m=df_1m, ...
    )
    
    # Directement émettre le signal
    if score >= SCORE_MIN_REQUIRED:
        emit_signal(sym, score, side, ...)

APRÈS :
"""

async def scan_symbol(sym: str, session: aiohttp.ClientSession) -> None:
    """Scan complet d'un symbole — AVEC DecisionKernel + DetectionCache."""
    
    async with _scan_locks[sym]:
        try:
            # ========== DATA LOADING ==========
            is_gold = sym in ("PAXG/USDT",)
            if is_gold:
                df_ltf = await _get_gold_df(session, ACTIVE_TF)
                df_htf = await _get_gold_df(session, "4h")
            else:
                df_ltf = candle_store.get(sym)
                df_htf = candle_store.get(sym)  # Simplifié, normalement autre TF
            
            if df_ltf is None or len(df_ltf) < MIN_DF30_FOR_SCAN:
                logger.warning(f"[SIGNAL] {sym} — données insuffisantes")
                return
            
            # ========== NOUVELLE : DÉTECTION CACHÉE ==========
            from core.detection_cache import get_or_detect
            
            detection = await asyncio.to_thread(
                get_or_detect, 
                sym, df_ltf, df_htf,
                ltf_tf=ACTIVE_TF,
                htf_tf="H4",
                venue="crypto",
                force_recompute=False
            )
            
            if detection is None:
                logger.debug(f"[SIGNAL] {sym} — detection failed (invalid data)")
                return
            
            score = detection.score
            side_raw = 1 if detection.side == "ACHAT" else (
                -1 if detection.side == "VENTE" else 0
            )
            criteria = detection.criteria
            
            # ========== NOUVELLE : DÉCISION KERNEL ==========
            from core.decision_kernel import build_verdict, cache_verdict
            
            # Construire le verdict via DecisionKernel
            verdict = build_verdict(
                sym,
                confluence_result=None,  # signal_engine n'a pas confluence
                scoring_result={
                    "side": "ACHAT" if side_raw > 0 else ("VENTE" if side_raw < 0 else "NEUTRE"),
                    "score": score,
                    "score_max": 16,
                    "criteria": criteria,
                },
                emotion=None,  # Peut ajouter emotion_for(sym) si souhaité
                strategy="signal_engine",
                notional_eur=score * 100,  # Approx
                engine_equity=executor.equity,
            )
            
            # Sauvegarder pour dashboard/debugging
            cache_verdict(sym, verdict)
            
            # ========== EMISSION SIGNAL (seulement si verdict OK) ==========
            # AVANT : if score >= SCORE_MIN_REQUIRED
            # APRÈS : if verdict.allow AND verdict.side != 0
            
            if not verdict.allow:
                logger.debug(f"[SIGNAL] {sym} BLOCKED: {verdict.reason_codes}")
                return
            
            if verdict.side == 0:
                logger.debug(f"[SIGNAL] {sym} NEUTRAL: no trade")
                return
            
            # Émettre le signal (avec conviction du Kernel)
            emit_signal(
                sym,
                score=score,
                side=verdict.side,
                conviction=verdict.conviction,
                # ... autres params
            )
            
            logger.info(
                f"[SIGNAL] {sym} ENTER {verdict.side}: "
                f"score={score} conviction={verdict.conviction:.2f} "
                f"reasons={verdict.reason_codes[:3]}"
            )
            
        except Exception as exc:
            logger.warning(f"[SIGNAL] {sym} error: {exc}")
