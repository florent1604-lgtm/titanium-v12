"""core/signal_engine.py — Boucle principale de scan (5s/symbole) avec asyncio.Lock."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import aiohttp
from utils.config import (
    SYMBOLS, SCAN_INTERVAL, MIN_DF30_FOR_SCAN, ACTIVE_TF, ORDERBOOK_L2_ENABLED,
    SPECTRAL_ENABLED, SPECTRAL_TF,
    SPECTRAL_PMIN, SPECTRAL_PMAX, SPECTRAL_POWER_THRESHOLD, SPECTRAL_MIN_BARS,
)
from utils.logger import get_logger
from data.binance_rest import fetch_klines
from data.binance_ws import candle_store, delta_vol
from data.gold_provider import gold_store, fetch_gold_candles
from data.futures_data import futures_store, fetch_futures
from data.orderbook_ws import orderbook_store, get_orderbook
from data.spread_tracker import spread_tracker
from indicators.orderbook import analyze_orderbook_l2
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

try:
    from indicators.spectral import compute_spectral_features as _spectral_compute
except ImportError:
    _spectral_compute = None  # scipy absent — spectral désactivé silencieusement

# [FIX] asyncio.Lock() au lieu de flags booléens
_scan_locks: Dict[str, asyncio.Lock] = {s: asyncio.Lock() for s in SYMBOLS}

# État spectral courant par symbole (Phase 1) — consommé par le scoring et /spectral/state
spectral_state: Dict[str, Any] = {}


def get_spectral_state() -> Dict[str, Any]:
    """Retourne l'état spectral courant de tous les symboles (dashboard, backtest)."""
    return dict(spectral_state)


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

            # ── Mise à jour SL/TP prioritaire (avant toute vérification de données) ──
            # Permet de déclencher les SL/TP même si df30 est insuffisant (tokens faible volume)
            df30_early = candle_store.get(sym)
            if df30_early is not None and not df30_early.empty:
                early_price = float(df30_early["close"].iloc[-1])
                if early_price > 0:
                    await executor.update_price(sym, early_price)

            # ── Candle store 30s ─────────────────────────────────────────────
            df30 = df30_early
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

            # ── Analyse spectrale (Phase 0 — calcul ; Phase 1 — dépondération au scoring) ──
            if SPECTRAL_ENABLED and _spectral_compute is not None and len(df_h4) >= SPECTRAL_MIN_BARS:
                try:
                    feats = _spectral_compute(
                        df_h4["close"].values,
                        pmin=SPECTRAL_PMIN,
                        pmax=SPECTRAL_PMAX,
                        power_threshold=SPECTRAL_POWER_THRESHOLD,
                    )
                    spectral_state[sym] = feats
                    logger.info(
                        "[SPECTRAL] %s — cycle=%d H4, power=%.2f, zone=%s, has_cycle=%s",
                        sym, feats.dominant_cycle, feats.cycle_power, feats.phase_zone, feats.has_cycle,
                    )
                    from utils.event_bus import emit as _emit_event
                    _emit_event("SPECTRAL", {
                        "symbol": sym, "dominant_cycle": feats.dominant_cycle,
                        "cycle_power": feats.cycle_power, "phase_zone": feats.phase_zone,
                        "has_cycle": feats.has_cycle,
                    })
                except Exception as _spec_err:
                    logger.debug("[SPECTRAL] %s erreur: %s", sym, _spec_err)

            # ── Score ─────────────────────────────────────────────────────────
            strict_p  = get_strict_params(sym)
            weights   = get_weights(sym)
            dv_state  = delta_vol.get(sym, {})
            fut_state = futures_store.get(sym, {})

            # ── Order Book L2 (institutional) ──────────────────────────────
            ob_analysis = None
            if ORDERBOOK_L2_ENABLED:
                ob_state = get_orderbook(sym)
                if ob_state is not None:
                    # Mettre à jour le spread tracker avec le spread L2 temps réel
                    if ob_state.spread_bps > 0:
                        spread_tracker.update(sym, ob_state.spread_bps)
                    # Déterminer le side préliminaire pour l'analyse OB
                    # On utilise l'EMA200 H4 comme biais
                    from core.smc_engine import compute_ema200
                    import math
                    preliminary_side = "NEUTRE"
                    if df_h4 is not None and len(df_h4) >= 200:
                        ema_h4 = compute_ema200(df_h4["close"])
                        if not math.isnan(ema_h4):
                            p = float(df30["close"].iloc[-1]) if df30 is not None and not df30.empty else 0
                            if p > 0:
                                preliminary_side = "ACHAT" if p > ema_h4 else "VENTE"
                    if preliminary_side != "NEUTRE":
                        ob_analysis = analyze_orderbook_l2(ob_state, preliminary_side)
                        logger.debug("[SCAN] %s OB L2 imbalance=%.2f wall=%s spread=%.1fbps",
                                     sym,
                                     ob_analysis.weighted_imbalance if ob_analysis else 0,
                                     ob_analysis.wall_side if ob_analysis else "n/a",
                                     ob_state.spread_bps)

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
                orderbook_analysis=ob_analysis,
                spectral_features=spectral_state.get(sym),
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
            # Utilise signal_modulator.modulate() comme source unique de vérité
            effective_score = score
            if macro_active() and score > 0 and side != "NEUTRE":
                risk_score = get_macro_risk()
                ctx["macro_risk"] = round(risk_score, 1)
                # Construire un signal temporaire pour la modulation
                temp_signal = {"score": score, "side": side, "symbol": sym}
                modulated = macro_modulate(temp_signal, risk_score)
                if modulated is None:
                    logger.info("[SCAN] %s score bloqué par risque macro (%.1f)", sym, risk_score)
                    effective_score = 0
                else:
                    effective_score = modulated.get("score", score)
                    if "risk_factor" in modulated:
                        ctx["risk_factor"] = modulated["risk_factor"]

            # ── Filtre d'alignement momentum (strategy_lab V3, 08/07/2026) ────
            # Veto si le signal va CONTRE la pente EMA50-H1 : c'est le pattern
            # perdant observé en paper (31 trades 100 % SHORT, 81 % en SL).
            # Actif par symbole via MOMENTUM_ALIGN_SYMBOLS (BTC oui, PAXG non).
            from utils.config import MOMENTUM_ALIGN_SYMBOLS
            if (sym in MOMENTUM_ALIGN_SYMBOLS and side in ("ACHAT", "VENTE")
                    and effective_score > 0
                    and df_h1 is not None and len(df_h1) >= 60):
                try:
                    ema50_h1 = df_h1["close"].ewm(span=50, adjust=False).mean()
                    slope_up = float(ema50_h1.iloc[-1]) > float(ema50_h1.iloc[-6])
                    if (side == "ACHAT") != slope_up:
                        ctx["momentum_misaligned"] = True
                        logger.info("[SCAN] %s %s bloqué — pente EMA50-H1 opposée "
                                    "(filtre alignement)", sym, side)
                        effective_score = 0
                except Exception as e:
                    logger.debug("[SCAN] filtre alignement %s: %s", sym, e)

            # ── Emit signal ───────────────────────────────────────────────────
            signal = emit_signal(sym, effective_score, side, confs, ctx, levels)

            # Lot C M2-1: additive shadow observer, never affects emission.
            try:
                from core.shadow_divergence import observe
                await asyncio.to_thread(
                    observe,
                    sym,
                    side,
                    effective_score,
                    emitted=bool(signal),
                    score_min=get_score_min(sym),
                )
            except Exception:
                pass

            # ── Recherche web autonome si score élevé (non-bloquant) ──────────
            try:
                from assistant.config import BROWSER_AUTO_RESEARCH, BROWSER_AUTO_SCORE_MIN
                if BROWSER_AUTO_RESEARCH and effective_score >= BROWSER_AUTO_SCORE_MIN and side:
                    from assistant.browser_agent import research_context
                    asyncio.create_task(
                        _enrich_signal_with_news(sym, side, effective_score, signal)
                    )
            except Exception:
                pass

            # ── Mise à jour executor avec le prix précis du scan (raffinement) ──
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


async def _enrich_signal_with_news(sym: str, side: str, score: int, signal: dict) -> None:
    """Enrichit un signal avec du contexte web. Fire-and-forget, jamais d'exception."""
    try:
        from assistant.browser_agent import research_context
        base_sym = sym.split("/")[0]
        web_ctx = await research_context(base_sym, side)
        if web_ctx and signal is not None:
            signal["algo_context"] = signal.get("algo_context", {})
            signal["algo_context"]["web_context"] = web_ctx
            logger.info("[SCAN] %s score=%d web_context injecté (%d chars)", sym, score, len(web_ctx))
    except Exception as e:
        logger.debug("[SCAN] web enrichment échoué: %s", e)


async def scan_loop(session: aiohttp.ClientSession) -> None:
    """Boucle principale — scan tous les symboles toutes les SCAN_INTERVAL secondes."""
    logger.info("[SCAN] Démarrage boucle de scan — %s actifs, interval=%ds", len(SYMBOLS), SCAN_INTERVAL)
    while True:
        tasks = [scan_symbol(sym, session) for sym in SYMBOLS]
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(SCAN_INTERVAL)
