"""core/signal_engine.py — Boucle principale de scan (5s/symbole) avec asyncio.Lock."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import aiohttp
from utils.config import (
    SYMBOLS, SCAN_INTERVAL, MIN_DF30_FOR_SCAN, ACTIVE_TF,
    SPECTRAL_ENABLED, SPECTRAL_TF,
)
from utils.logger import get_logger
from data.binance_rest import fetch_klines
from data.binance_ws import candle_store, delta_vol
from data.gold_provider import gold_store, fetch_gold_candles
from data.futures_data import futures_store, fetch_futures
from core.scoring_engine import score_setup, get_score_min
from core.smc_engine import compute_atr
from execution.risk_manager import compute_adaptive_levels
from execution.signal_manager import emit_signal, has_changed, signals
from fundamentals.risk_scorer import get_current_score as get_macro_risk
from fundamentals.signal_modulator import modulate as macro_modulate, is_active as macro_active
from engine.strict_engine import get_strict_params
from engine.learning_engine import get_weights, record_signal
from notifications.telegram import send_signal_alert
from execution.executor import executor

logger = get_logger(__name__)

# [FIX] asyncio.Lock() au lieu de flags booléens
_scan_locks: Dict[str, asyncio.Lock] = {s: asyncio.Lock() for s in SYMBOLS}

# Throttle du log "df30 insuffisant" — une ligne / 30s / symbole au lieu
# d'une ligne par scan (3s), pour garder les logs lisibles
_wait_log_ts: Dict[str, float] = {}

# Broadcast callback — injecté par api/websocket.py
_broadcast_fn = None


def set_broadcast_fn(fn) -> None:
    global _broadcast_fn
    _broadcast_fn = fn


async def _get_gold_df(session: aiohttp.ClientSession, tf: str):
    """Récupère les bougies gold depuis le store ou en fetche."""
    df = gold_store.get(tf)
    if df is None or df.empty:
        df = await fetch_gold_candles(session, tf)
    return df


async def scan_symbol(sym: str, session: aiohttp.ClientSession) -> None:
    """Scan complet d'un symbole — calcule le score et émet le signal si qualifié."""

    async with _scan_locks[sym]:
        try:
            is_gold = sym in ("PAXG/USDT",)

            # ── Candle store 30s ─────────────────────────────────────────────
            df30 = candle_store.get(sym)
            if df30 is None or len(df30) < MIN_DF30_FOR_SCAN:
                now = datetime.now(timezone.utc).timestamp()
                if now - _wait_log_ts.get(sym, 0.0) >= 30.0:
                    _wait_log_ts[sym] = now
                    logger.info("[SCAN] %s — en attente de données : %d/%d bougies 30s "
                                "(seed REST + flux WS en cours d'accumulation)",
                                sym, len(df30) if df30 is not None else 0, MIN_DF30_FOR_SCAN)
                return

            # ── Fetch multi-timeframes ────────────────────────────────────────
            fetches = {}
            for tf in ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"):
                try:
                    if is_gold:
                        fetches[tf] = await _get_gold_df(session, tf)
                    else:
                        fetches[tf] = await fetch_klines(session, sym, tf)
                except Exception as e:
                    logger.debug("[SCAN] %s/%s fetch: %s", sym, tf, e)
                    fetches[tf] = None

            df_h4  = fetches.get("4h")
            df_h2  = fetches.get("2h")
            df_h1  = fetches.get("1h")
            df_m30 = fetches.get("30m")
            df_m15 = fetches.get("15m")
            df_m5  = fetches.get("5m")
            df_1m  = fetches.get("1m")
            df_1d  = fetches.get("1d")

            if df_h4 is None or df_h4.empty:
                logger.info("[SCAN] %s — H4 manquant (fetch échoué)", sym)
                return

            # ── Score ─────────────────────────────────────────────────────────
            strict_p  = get_strict_params(sym)
            weights   = get_weights(sym)
            dv_state  = delta_vol.get(sym, {})
            fut_state = futures_store.get(sym, {})

            score, side, confs, ctx = score_setup(
                sym=sym,
                df_h4=df_h4,
                df_1m=df_1m if (df_1m is not None and not df_1m.empty) else df30,
                df30=df30,
                df_h2=df_h2,
                df_h1=df_h1,
                df_m30=df_m30,
                df_m15=df_m15,
                df_m5=df_m5,
                df_1d=df_1d,
                strict_params=strict_p,
                scoring_w=weights,
                delta_vol_state=dv_state,
                futures_data_state=fut_state,
            )

            # ── Analyse spectrale (Phase 1 : instrumentation seulement) ──────
            # Exposé dans ctx → API → dashboard. NE MODIFIE PAS le score /16
            # tant que la validation walk-forward n'est pas faite (roadmap).
            if SPECTRAL_ENABLED:
                try:
                    from indicators.spectral import analyze as spectral_analyze
                    df_spec = fetches.get(SPECTRAL_TF)
                    if df_spec is not None and not df_spec.empty:
                        spec = spectral_analyze(df_spec["close"])
                        if spec:
                            ctx["spectral"] = spec
                            logger.info("[SPECTRAL] %s — cycle=%s barres power=%.2f phase=%s (%s°)",
                                        sym, spec["dominant_cycle"], spec["cycle_power"],
                                        spec["phase_zone"], spec["phase_deg"])
                except Exception as e:
                    logger.debug("[SPECTRAL] %s: %s", sym, e)

            # ── SL/TP ─────────────────────────────────────────────────────────
            price   = ctx.get("price", 0)
            df_atr  = next((d for d in (df_m5, df_m30, df30) if d is not None and not d.empty), df30)
            levels  = compute_adaptive_levels(df_atr, sym, side, price) if price > 0 else {}

            # ── Modulation macro-économique ───────────────────────────────────
            # Appliquée sur le score avant émission (filtre ou réduction)
            effective_score = score
            if macro_active() and score > 0 and side != "NEUTRE":
                risk_score = get_macro_risk()
                ctx["macro_risk"] = round(risk_score, 1)
                # Pré-modulation du score (modulate() sera rappelé sur le signal complet)
                from utils.config import FUNDAMENTALS_RISK_BLOCK, FUNDAMENTALS_RISK_REDUCE
                if risk_score >= FUNDAMENTALS_RISK_BLOCK:
                    logger.info("[SCAN] %s score bloqué par risque macro (%.1f)", sym, risk_score)
                    effective_score = 0   # force le signal à inactif
                elif risk_score > FUNDAMENTALS_RISK_REDUCE:
                    spread  = FUNDAMENTALS_RISK_BLOCK - FUNDAMENTALS_RISK_REDUCE
                    factor  = 1.0 - ((risk_score - FUNDAMENTALS_RISK_REDUCE) / spread) * 0.5
                    effective_score = max(0, int(score * factor))
                    ctx["risk_factor"] = round(factor, 3)

            # ── Emit signal ───────────────────────────────────────────────────
            signal = emit_signal(sym, effective_score, side, confs, ctx, levels)

            # ── Mise à jour executor (SL/TP/funding) à chaque scan ────────────
            if price > 0:
                await executor.update_price(sym, price)

            # ── Broadcast WS si changement ────────────────────────────────────
            if has_changed(sym) and _broadcast_fn is not None:
                await _broadcast_fn(sym, signals[sym])

            # ── Exécution paper + Telegram + learning ─────────────────────────
            if signal and signal.get("active"):
                await executor.execute(signal)
                await send_signal_alert(session, sym, signal)
                record_signal(sym, signal)

        except Exception as e:
            logger.error("[SCAN] %s erreur inattendue: %s", sym, e, exc_info=True)


async def scan_loop(session: aiohttp.ClientSession) -> None:
    """Boucle principale — scan tous les symboles toutes les SCAN_INTERVAL secondes."""
    logger.info("[SCAN] Démarrage boucle de scan — %s actifs, interval=%ds", len(SYMBOLS), SCAN_INTERVAL)
    while True:
        tasks = [scan_symbol(sym, session) for sym in SYMBOLS]
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(SCAN_INTERVAL)
