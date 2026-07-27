"""api/api_server.py — FastAPI : routes REST + WebSocket + dashboard HTML."""
from __future__ import annotations
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
import aiohttp
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request as FARequest
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from api.auth import require_admin
from starlette.middleware.gzip import GZipMiddleware
from starlette.websockets import WebSocketState
from fastapi.middleware.cors import CORSMiddleware
from utils.config import (
    UVICORN_HOST, UVICORN_PORT, UVICORN_LOG_LEVEL,
    HTTP_POOL_SIZE, HTTP_CONNECT_LIMIT, HTTP_TIMEOUT_TOTAL,
    SYMBOLS, FUNDAMENTALS_ENABLED, TRADING_MODE, SCORE_CRITERIA,
)
from utils.logger import get_logger
from api.websocket import broadcast, ws_connect, ws_disconnect, get_client_count
from execution.signal_manager import get_all_signals
from api.json_contract import serialize_signal_states
from engine.optimizer import get_opt_results
from engine.learning_engine import scoring_weights, signal_history
from data.binance_ws import delta_vol
from data.futures_data import futures_store
from vision.ollama_vision import ollama_vision_analyze, check_ollama_available

logger = get_logger(__name__)

# Chemin du dashboard HTML v12
_DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "titanium_v12_dashboard.html"
_DASHBOARD_V13  = Path(__file__).resolve().parent.parent / "titanium_v13_dashboard.html"


async def _seed_candle_store(session: aiohttp.ClientSession) -> None:
    """Pré-charge candle_store via REST 1m pour éviter le warm-up de 5min.

    Fetche les 60 dernières bougies 1m (= 1h de données), les convertit en
    format identique aux barres 1s du WS, puis les resample en 30s pour
    alimenter immédiatement candle_store.
    """
    import pandas as pd
    from data.binance_rest import fetch_klines
    from data.binance_ws import candle_store, raw_1s
    from data.gold_provider import fetch_gold_candles, gold_store

    for sym in SYMBOLS:
        try:
            is_gold = sym in ("PAXG/USDT",)
            if is_gold:
                df_1m = await fetch_gold_candles(session, "1m")
            else:
                df_1m = await fetch_klines(session, sym, "1m", limit=60)

            if df_1m is None or df_1m.empty or len(df_1m) < 5:
                logger.warning("[SEED] %s — pas assez de données 1m REST", sym)
                continue

            # Resampler les bougies 1m en pseudo-30s (chaque bougie 1m → 2×30s)
            # On crée un DataFrame 30s directement lisible par signal_engine
            rows = []
            for ts, row in df_1m.iterrows():
                ts_pd = pd.Timestamp(ts)
                mid = (row["open"] + row["close"]) / 2
                vol_half = row.get("v", 0) / 2
                # Première moitié (seconde 0)
                rows.append({"open": row["open"], "high": row["high"],
                             "low": row["low"], "close": mid, "v": vol_half})
                # Deuxième moitié (seconde 30)
                rows.append({"open": mid, "high": row["high"],
                             "low": row["low"], "close": row["close"], "v": vol_half})

            df30 = pd.DataFrame(rows)
            # Créer un index temporel 30s aligné
            start = pd.Timestamp(df_1m.index[0])
            idx = pd.date_range(start=start, periods=len(df30), freq="30s", tz="UTC")
            df30.index = idx[:len(df30)]
            df30 = df30.tail(500)

            candle_store[sym] = df30
            logger.info("[SEED] %s — %d bougies 30s pré-chargées via REST (warm-up éliminé)",
                        sym, len(df30))
        except Exception as e:
            logger.warning("[SEED] %s — seed REST échoué: %s", sym, e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie FastAPI — démarre toutes les tâches asyncio."""
    from data.binance_ws import ws_binance, seed_candle_store
    from data.gold_provider import gold_refresh_loop
    from data.futures_data import futures_refresh_loop
    from core.signal_engine import scan_loop, set_broadcast_fn
    from engine.optimizer import optimisation_loop
    from engine.strict_engine import strict_recalib_loop
    from engine.learning_engine import learning_report_loop, load_state
    from execution.risk_manager import circuit_breaker_loop
    from fundamentals.fetcher_loop import fundamentals_loop
    from fundamentals.external_feeds import external_feeds_loop
    from data.orderbook_ws import start_orderbook_streams
    import asyncio

    # Charger l'état persisté
    load_state()

    # Session HTTP partagée
    connector = aiohttp.TCPConnector(
        limit=HTTP_POOL_SIZE,
        limit_per_host=HTTP_CONNECT_LIMIT,
    )
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_TOTAL)
    session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    app.state.http = session

    # Injecter le broadcast dans signal_engine
    set_broadcast_fn(broadcast)

    # Vérifier Ollama
    await check_ollama_available(session)

    # Démarrer les streams de carnet d'ordres L2
    await start_orderbook_streams()

    # ── Fix C3 : Seed REST → warm-up instantané ──────────────────────────
    # Pré-charger les bougies 1m via REST et les resampler en 30s pour
    # alimenter candle_store AVANT que le WS aggTrade ne s'accumule.
    # Élimine l'attente de ~5 min au démarrage.
    await _seed_candle_store(session)

    # Démarrer toutes les tâches en arrière-plan
    tasks = []
    # WebSocket aggTrade par symbole
    for sym in SYMBOLS:
        tasks.append(asyncio.create_task(ws_binance(sym), name=f"ws_{sym}"))

    tasks += [
        asyncio.create_task(gold_refresh_loop(session),             name="gold_refresh"),
        asyncio.create_task(futures_refresh_loop(session, SYMBOLS), name="futures_refresh"),
        asyncio.create_task(scan_loop(session),                     name="scan_loop"),
        asyncio.create_task(optimisation_loop(session),             name="optimizer"),
        asyncio.create_task(strict_recalib_loop(session),           name="strict_recalib"),
        asyncio.create_task(learning_report_loop(),                  name="learning"),
        asyncio.create_task(circuit_breaker_loop(get_opt_results()), name="circuit_breaker"),
        asyncio.create_task(external_feeds_loop(session),            name="external_feeds"),
    ]
    if FUNDAMENTALS_ENABLED:
        tasks.append(asyncio.create_task(fundamentals_loop(session), name="fundamentals"))

    # Moteur forex/or MT5-Axi (paper only, stratégie V3 validée par strategy_lab)
    from utils.config import FOREX_ENABLED
    if FOREX_ENABLED:
        try:
            from core.forex_engine import forex_engine_loop
            tasks.append(asyncio.create_task(forex_engine_loop(), name="forex_engine"))
        except Exception as e:
            logger.warning("[FOREX] Moteur non démarré: %s", e)

    # Moteur SWING (paper only — panier validé au tester natif MT5 : USTECH/NAS100/HSI)
    from utils.config import SWING_ENABLED
    if SWING_ENABLED:
        try:
            from core.swing_engine import swing_engine_loop
            tasks.append(asyncio.create_task(swing_engine_loop(), name="swing_engine"))
        except Exception as e:
            logger.warning("[SWING] Moteur non démarré: %s", e)

    # Scan d'opportunités périodique (cron in-app tous les N jours)
    from utils.config import OPP_SCAN_ENABLED
    if OPP_SCAN_ENABLED:
        try:
            from core.opportunity_scan import opportunity_scan_loop
            tasks.append(asyncio.create_task(opportunity_scan_loop(), name="opportunity_scan"))
        except Exception as e:
            logger.warning("[OPP] Scan non démarré: %s", e)

    # Forward-paper GELÉ XRP/LINK intraday (Binance, config pré-enregistrée) — boucle
    # horaire. Détecte les signaux sur la H1 clôturée, journalise + émotion observée,
    # et (si MIRROR) place un ordre sur le démo MT5 pour visibilité iOS. PAPER ONLY.
    from utils.config import FORWARD_PAPER_ENABLED, FORWARD_PAPER_MIRROR, FORWARD_PAPER_SECONDS
    if FORWARD_PAPER_ENABLED:
        async def _forward_paper_loop():
            from tools.forward_paper_intraday import run_once
            await asyncio.sleep(30)          # laisser le démarrage se stabiliser
            while True:
                try:
                    await asyncio.to_thread(run_once, FORWARD_PAPER_MIRROR)
                except Exception as e:
                    logger.warning("[FWD-PAPER] boucle: %s", e)
                await asyncio.sleep(FORWARD_PAPER_SECONDS)
        tasks.append(asyncio.create_task(_forward_paper_loop(), name="forward_paper"))
        logger.info("[FWD-PAPER] boucle activée (miroir démo=%s, %ss)",
                    FORWARD_PAPER_MIRROR, FORWARD_PAPER_SECONDS)

    # Moteur de CONFLUENCE en DÉMO MT5 (méthode Florent, mode EXPLORE). Câble la stack
    # de détection sur l'exécuteur démo pour ouvrir de vraies positions sur le compte
    # DÉMO et les observer (dashboard « pourquoi » + iOS). DÉSARMÉ par défaut ; les
    # ordres exigent EN PLUS DEMO_EXEC_ENABLED=1 + le mur démo↔réel.
    from utils.config import (CONFLUENCE_DEMO_ENABLED, CONFLUENCE_DEMO_SYMBOLS,
                              CONFLUENCE_DEMO_LTF, CONFLUENCE_DEMO_HTF,
                              CONFLUENCE_DEMO_SECONDS, CONFLUENCE_DEMO_SL_ATR,
                              CONFLUENCE_DEMO_TP_ATR, CONFLUENCE_DEMO_TP_LADDER,
                              CONFLUENCE_CRYPTO_ENABLED, CONFLUENCE_CRYPTO_SYMBOLS,
                              CONFLUENCE_AGGRESSIVE_MIN, CONFLUENCE_AGGRESSIVE_EXEC,
                              CONFLUENCE_ROTATE_BATCH, CONFLUENCE_DEMO_AUTO_UNIVERSE,
                              ENTRY_REFINE_ENABLED, ENTRY_REFINE_LTF,
                              ENTRY_REFINE_MICRO_TF, ENTRY_REFINE_SL_FLOOR_FRAC,
                              CONFLUENCE_TREND_ALIGN, CONFLUENCE_TREND_ALIGN_MIN_ATR,
                              RISKGATE_ENABLED)

    def _discover_cfd_universe(fallback):
        """Univers CFD COMPLET auto-découvert depuis MT5 (tout le tradable liquide hors
        actions), moins les symboles déjà couverts par la boucle crypto. Fail-safe :
        repli sur la liste `.env` si MT5/list_universe indisponible."""
        try:
            from tools.asset_optimizer import list_universe
            crypto_set = set(CONFLUENCE_CRYPTO_SYMBOLS) if CONFLUENCE_CRYPTO_ENABLED else set()
            syms = [u["symbol"] for u in list_universe() if u.get("symbol") not in crypto_set]
            if syms:
                logger.info("[CONFLUENCE-DEMO] univers AUTO-découvert: %d actifs MT5 (hors crypto)", len(syms))
                return syms
        except Exception as e:
            logger.warning("[CONFLUENCE-DEMO] auto-univers indisponible (%s) — repli liste .env", e)
        return fallback
    if CONFLUENCE_DEMO_ENABLED or CONFLUENCE_CRYPTO_ENABLED:
        async def _confluence_demo_loop():
            from core.confluence_demo_engine import run_once
            from data.binance_ohlcv import reference_close
            crypto = ([{"symbol": s, "ltf": CONFLUENCE_DEMO_LTF, "htf": CONFLUENCE_DEMO_HTF,
                        "venue": "crypto"} for s in CONFLUENCE_CRYPTO_SYMBOLS]
                      if CONFLUENCE_CRYPTO_ENABLED else [])
            batch = CONFLUENCE_ROTATE_BATCH
            idx = 0
            await asyncio.sleep(30)          # laisser le démarrage se stabiliser
            # Univers CFD : liste .env, ou univers MT5 COMPLET auto-découvert (après que MT5
            # soit prêt) si CONFLUENCE_DEMO_AUTO_UNIVERSE=1 → couvre les ~149 actifs.
            cfd_syms = CONFLUENCE_DEMO_SYMBOLS
            if CONFLUENCE_DEMO_ENABLED and CONFLUENCE_DEMO_AUTO_UNIVERSE:
                cfd_syms = await asyncio.to_thread(_discover_cfd_universe, CONFLUENCE_DEMO_SYMBOLS)
            cfd = ([{"symbol": s, "ltf": CONFLUENCE_DEMO_LTF, "htf": CONFLUENCE_DEMO_HTF,
                     "venue": "cfd"} for s in cfd_syms]
                   if CONFLUENCE_DEMO_ENABLED else [])
            while True:
                try:
                    # ROTATION : crypto (ouvert 24/7) scanné à CHAQUE cycle ; CFD (univers large)
                    # par lots rotatifs → couvre tout l'univers sans marteler MT5.
                    if batch > 0 and len(cfd) > batch:
                        cfd_batch = [cfd[(idx + j) % len(cfd)] for j in range(batch)]
                        idx = (idx + batch) % len(cfd)
                    else:
                        cfd_batch = cfd
                    # ref_fn=reference_close : ajustement Binance (None hors crypto). MT5 reste
                    # la source PRINCIPALE (données + exécution).
                    await run_once(crypto + cfd_batch, ref_fn=reference_close,
                                   sl_atr_mult=CONFLUENCE_DEMO_SL_ATR,
                                   tp_atr_mult=CONFLUENCE_DEMO_TP_ATR,
                                   tp_ladder=CONFLUENCE_DEMO_TP_LADDER,
                                   aggressive_min=CONFLUENCE_AGGRESSIVE_MIN,
                                   aggressive_exec=CONFLUENCE_AGGRESSIVE_EXEC,
                                   refine_enabled=ENTRY_REFINE_ENABLED,
                                   refine_ltf=ENTRY_REFINE_LTF,
                                   refine_micro_tf=ENTRY_REFINE_MICRO_TF,
                                   refine_sl_floor_frac=ENTRY_REFINE_SL_FLOOR_FRAC,
                                   trend_align=CONFLUENCE_TREND_ALIGN,
                                   trend_align_min_atr=CONFLUENCE_TREND_ALIGN_MIN_ATR,
                                   riskgate_enabled=RISKGATE_ENABLED)
                except Exception as e:
                    logger.warning("[CONFLUENCE-DEMO] boucle: %s", e)
                await asyncio.sleep(CONFLUENCE_DEMO_SECONDS)
        tasks.append(asyncio.create_task(_confluence_demo_loop(), name="confluence_demo"))
        logger.info("[CONFLUENCE-DEMO] boucle activée — CFD=%s crypto=%s (LTF=%s HTF=%s, %ss) — "
                    "MT5 principal, ajusté Binance ; ordres si DEMO_EXEC_ENABLED=1 + compte démo",
                    CONFLUENCE_DEMO_SYMBOLS if CONFLUENCE_DEMO_ENABLED else [],
                    CONFLUENCE_CRYPTO_SYMBOLS if CONFLUENCE_CRYPTO_ENABLED else [],
                    CONFLUENCE_DEMO_LTF, CONFLUENCE_DEMO_HTF, CONFLUENCE_DEMO_SECONDS)

        # GESTION DYNAMIQUE des positions démo (breakeven + trailing, Florent 26/07). La boucle
        # se désarme elle-même si DEMO_EXEC_ENABLED/DEMO_MANAGE_ENABLED != 1.
        from execution.demo_position_manager import manage_loop as _demo_manage_loop
        tasks.append(asyncio.create_task(_demo_manage_loop(), name="demo_manage"))

        # DÉBRIEF AUTOMATIQUE par position (Florent 27/07) : relie en continu chaque position
        # clôturée à son rationale d'entrée (piliers+flux) → résultat, mémorisé par Cloe pour
        # affiner. Non bloquant, fail-safe.
        async def _debrief_loop():
            import os as _os
            secs = int(_os.getenv("DEBRIEF_LOOP_SECONDS", "600"))
            await asyncio.sleep(120)
            while True:
                try:
                    from tools.position_debrief import debrief as _dbf
                    rep = await asyncio.to_thread(_dbf, 12)
                    if rep.get("n_debriefs"):
                        logger.info("[DEBRIEF] %s position(s) débriefées (%s avec rationale)",
                                    rep["n_debriefs"], rep.get("n_avec_rationale"))
                    # rafraîchit la base RAG de Cloe (mémoire + news/macro + findings) pour Open WebUI
                    from tools.cloe_knowledge_export import export as _kexport
                    await asyncio.to_thread(_kexport)
                except Exception as e:  # noqa: BLE001
                    logger.debug("[DEBRIEF] boucle: %r", e)
                await asyncio.sleep(secs)
        tasks.append(asyncio.create_task(_debrief_loop(), name="debrief"))

        # Consensus inter-moteurs AUTONOME : détection read-only, aucune injection dans
        # la confluence/l'exécuteur. Même univers/cadence et rotation bornée pour ne pas
        # augmenter sans limite la pression sur MT5. Pré-M2 : observation uniquement.
        async def _consensus_detection_loop():
            from core.consensus_engine import run_once as run_consensus_once
            cfd = ([{"symbol": s, "ltf": CONFLUENCE_DEMO_LTF, "htf": CONFLUENCE_DEMO_HTF,
                     "venue": "cfd"} for s in CONFLUENCE_DEMO_SYMBOLS]
                   if CONFLUENCE_DEMO_ENABLED else [])
            crypto = ([{"symbol": s, "ltf": CONFLUENCE_DEMO_LTF, "htf": CONFLUENCE_DEMO_HTF,
                        "venue": "crypto"} for s in CONFLUENCE_CRYPTO_SYMBOLS]
                      if CONFLUENCE_CRYPTO_ENABLED else [])
            batch = CONFLUENCE_ROTATE_BATCH
            idx = 0
            await asyncio.sleep(40)
            while True:
                try:
                    if batch > 0 and len(cfd) > batch:
                        cfd_batch = [cfd[(idx + j) % len(cfd)] for j in range(batch)]
                        idx = (idx + batch) % len(cfd)
                    else:
                        cfd_batch = cfd
                    await run_consensus_once(crypto + cfd_batch)
                except Exception as e:
                    logger.warning("[CONSENSUS] boucle de détection: %s", e)
                await asyncio.sleep(CONFLUENCE_DEMO_SECONDS)
        tasks.append(asyncio.create_task(_consensus_detection_loop(), name="consensus_detection"))
        logger.info("[CONSENSUS] détection 3 moteurs active — pré-M2, aucune décision/aucun ordre")

    # Concordance inter-actifs (lead/lag) — recherche EXPLORATOIRE pré-M2. Cherche quel
    # actif ANTICIPE quel autre + persistance ; débrief Telegram. Ne décide RIEN.
    from utils.config import (LEADLAG_ENABLED, LEADLAG_SYMBOLS, LEADLAG_SECONDS,
                              LEADLAG_MAX_LAG, LEADLAG_TFS)
    if LEADLAG_ENABLED:
        async def _lead_lag_loop():
            from core.lead_lag_engine import run_cycle
            await asyncio.sleep(45)
            while True:
                try:
                    await run_cycle(LEADLAG_SYMBOLS, tfs=tuple(LEADLAG_TFS),
                                    max_lag=LEADLAG_MAX_LAG)
                except Exception as e:
                    logger.warning("[LEADLAG] boucle: %s", e)
                await asyncio.sleep(LEADLAG_SECONDS)
        tasks.append(asyncio.create_task(_lead_lag_loop(), name="lead_lag"))
        logger.info("[LEADLAG] boucle de concordance activée (%d actifs, TF=%s, lag≤%d, %ss) — pré-M2",
                    len(LEADLAG_SYMBOLS), LEADLAG_TFS, LEADLAG_MAX_LAG, LEADLAG_SECONDS)

    # EventPlane MIROIR read-only (fusion Hermes B0/C0) : publie les faits des moteurs
    # dans core.event_plane. Observationnel STRICT — aucun ordre, aucun CommandGateway.
    from utils.config import EVENTPLANE_MIRROR_ENABLED, EVENTPLANE_MIRROR_SECONDS
    if EVENTPLANE_MIRROR_ENABLED:
        async def _eventplane_mirror_loop():
            from core.event_mirror import mirror_all_once   # C0b : confluence+consensus+leadlag
            import uuid as _uuid
            boot = _uuid.uuid4().hex[:12]
            await asyncio.sleep(50)
            while True:
                try:
                    await asyncio.to_thread(lambda: mirror_all_once(instance_id=boot))
                except Exception as e:
                    logger.warning("[EVENTPLANE] miroir: %s", e)
                await asyncio.sleep(EVENTPLANE_MIRROR_SECONDS)
        tasks.append(asyncio.create_task(_eventplane_mirror_loop(), name="eventplane_mirror"))
        logger.info("[EVENTPLANE] miroir read-only activé (%ss) — confluence+consensus+leadlag, "
                    "faits seulement, aucun ordre", EVENTPLANE_MIRROR_SECONDS)

    # Régénération périodique du pack de connaissance expert pour JARVIS (10 min)
    async def _knowledge_regen_loop():
        from tools.gen_jarvis_knowledge import write
        while True:
            try:
                await asyncio.to_thread(write)
            except Exception as e:
                logger.debug("[CONTEXT] regen: %s", e)
            await asyncio.sleep(600)
    tasks.append(asyncio.create_task(_knowledge_regen_loop(), name="knowledge_regen"))

    # Démarrer l'assistant Titan (si TITAN_ENABLED=1)
    from assistant.titan_core import start_titan
    await start_titan(session)

    # Démarrer les alertes vocales JARVIS
    try:
        from assistant.signal_alert import get_signal_alert_engine
        await get_signal_alert_engine().start()
    except Exception as e:
        logger.warning("[APP] Signal alert engine non démarré: %s", e)

    logger.info("[APP] Titanium v12 démarré — %d tâches actives", len(tasks))
    yield

    # Arrêt propre
    for t in tasks:
        t.cancel()
    from assistant.titan_core import stop_titan
    await stop_titan()
    try:
        from assistant.signal_alert import get_signal_alert_engine
        await get_signal_alert_engine().stop()
    except Exception:
        pass
    await session.close()
    logger.info("[APP] Titanium v12 arrêté proprement")


app = FastAPI(title="Titanium v12", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Assets de l'overlay JARVIS (orbe, boot, HUD vocal) — dashboard unifié.
# Le build Vite vit chez JARVIS ; on le sert aussi sur 8090 pour n'avoir
# qu'une seule version de l'interface.
from fastapi.staticfiles import StaticFiles
_JARVIS_ASSETS = Path(r"C:\Program Files\JARVIS\frontend\dist\assets")
if _JARVIS_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=str(_JARVIS_ASSETS)), name="jarvis_assets")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5174", "http://127.0.0.1:5174",
                   "http://localhost:8090", "http://127.0.0.1:8090"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

from api.fundamentals_routes import router as fundamentals_router
from api.paper_routes import router as paper_router
from api.webhook_routes import router as webhook_router
from api.titan_routes import router as titan_router
from api.services_routes import router as services_router
from api.cockpit_routes import router as cockpit_router
from api.latency_routes import router as latency_router
from api.forex_routes import router as forex_router
from api.swing_routes import router as swing_router
from api.opportunity_routes import router as opportunity_router
from api.context_routes import router as context_router
from api.emotion_routes import router as emotion_router
from api.snapshot_routes import (
    canonical_router as snapshot_canonical_router,
    router as snapshot_router,
)
from api.consensus_routes import router as consensus_router
from api.geometry_routes import router as geometry_router
from assistant.alexa_connector import router as alexa_router

app.include_router(fundamentals_router)
app.include_router(paper_router)
app.include_router(webhook_router)
app.include_router(titan_router)
app.include_router(services_router)
app.include_router(cockpit_router)
app.include_router(latency_router)
app.include_router(forex_router)
app.include_router(swing_router)
app.include_router(opportunity_router)
app.include_router(context_router)
app.include_router(emotion_router)
app.include_router(snapshot_router)
app.include_router(snapshot_canonical_router)
app.include_router(consensus_router)
app.include_router(geometry_router)
app.include_router(alexa_router)


# ── Routes ───────────────────────────────────────────────────────────────────

_DASHBOARD_ORBE_ROOT = Path(__file__).resolve().parent.parent / "titanium_orbe.html"


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Interface 4D HYPER-COCKPIT (07/2026) : cockpit 4D unifié. L'interface Orbe
    reste disponible sur /orbe et le classic sur /classic. HTML relu par requête."""
    if _DASHBOARD_4D.exists():
        return HTMLResponse(_DASHBOARD_4D.read_text(encoding="utf-8"))
    if _DASHBOARD_ORBE_ROOT.exists():
        return HTMLResponse(_DASHBOARD_ORBE_ROOT.read_text(encoding="utf-8"))
    if _DASHBOARD_HTML.exists():
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium v12</h1><p>Dashboard HTML non trouvé.</p>")


@app.get("/classic", response_class=HTMLResponse)
async def dashboard_classic():
    """Ancien dashboard v12 (préservé, réversible)."""
    if _DASHBOARD_HTML.exists():
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium v12</h1><p>Dashboard HTML non trouvé.</p>")


_DASHBOARD_V13 = Path(__file__).resolve().parent.parent / "titanium_v13_dashboard.html"
_APP_START_TS = datetime.now(timezone.utc)



_DASHBOARD_4D = Path(__file__).resolve().parent.parent / "titanium_4d_cockpit.html"


@app.get("/4d", response_class=HTMLResponse)
@app.get("/4d_cockpit", response_class=HTMLResponse)
async def dashboard_4d():
    """Interface 4D HYPER-COCKPIT (07/2026) : environnement WebGL 3D/4D unifié,
    graphe neuronal 3D avec surbrillance des nœuds bloquants du Cortex, carnet L2 3D,
    replay temporel 4D et télémétrie de l'Agent de Santé."""
    if _DASHBOARD_4D.exists():
        return HTMLResponse(_DASHBOARD_4D.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium 4D Cockpit</h1><p>titanium_4d_cockpit.html non trouvé.</p>", status_code=404)


@app.get("/v13", response_class=HTMLResponse)
async def dashboard_v13():
    """Dashboard v13 — un écran : santé, capital, vision."""
    if _DASHBOARD_V13.exists():
        return HTMLResponse(_DASHBOARD_V13.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium v13</h1><p>Dashboard v13 non trouvé.</p>")


@app.get("/eventplane/health")
async def eventplane_health(verifier: int = 0):
    """Santé de l'EventPlane (B0) : nb d'événements, dernier offset, échecs, intégrité.
    Lecture seule. Ne déclenche rien.

    L'intégrité vient de l'audit mutualisé (ré-haché au plus toutes les 10 min) et
    porte son âge. `?verifier=1` force un ré-audit complet immédiat.
    """
    from core.cortex import integrite_journal
    from core.event_plane import get_event_plane
    h = get_event_plane().health()
    h["integrity"] = integrite_journal(force=bool(verifier))
    return h


@app.get("/eventplane/read")
async def eventplane_read(after_offset: int = 0, limit: int = 50, event_type: str = ""):
    """Lit les FAITS après un offset (ordre de commit). Filtre optionnel par type.
    Lecture seule — un fait ne déclenche jamais rien."""
    from core.event_plane import get_event_plane
    types = tuple(t.strip() for t in event_type.split(",") if t.strip())
    evs = get_event_plane().read(after_offset=after_offset, limit=limit, event_types=types)
    return {"count": len(evs), "events": [{
        "global_offset": e.global_offset, "event_type": e.event_type,
        "occurred_at": e.occurred_at, "stream_id": e.stream_id, "stream_seq": e.stream_seq,
        "partition_key": e.partition_key, "payload": e.payload,
        "event_hash": e.event_hash[:16]} for e in evs]}


@app.get("/cortex/snapshot")
async def cortex_snapshot(full: bool = False):
    """CORTEX : état projeté UNIFIÉ (confluence + consensus + lead/lag) en un seul point.
    Lecture seule — ne décide rien. `?full=true` pour le détail complet de chaque moteur."""
    from core.cortex import snapshot
    return snapshot(full=full)


@app.get("/leadlag/status")
async def leadlag_status():
    """Concordance inter-actifs (lead/lag) : quelle relation anticipe quel actif, avec
    persistance. Lecture seule. EXPLORATOIRE pré-M2 — ne décide rien."""
    from core.lead_lag_engine import status_snapshot
    return status_snapshot()


_DASHBOARD_CONFLUENCE = Path(__file__).resolve().parent.parent / "titanium_confluence.html"


@app.get("/confluence", response_class=HTMLResponse)
async def dashboard_confluence():
    """Cockpit « analyse explicable » : les 5 piliers de la méthode par instrument,
    le verdict et les preuves. Se rafraîchit sur /confluence/demo/status."""
    if _DASHBOARD_CONFLUENCE.exists():
        return HTMLResponse(_DASHBOARD_CONFLUENCE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Confluence</h1><p>Page non trouvée.</p>", status_code=404)


@app.get("/confluence/demo/status")
async def confluence_demo_status():
    """État du moteur de confluence DÉMO : dernière décision par symbole + récents,
    avec la TRACE « pourquoi » (portes, reason-codes, piliers). Lecture seule."""
    from utils.config import (CONFLUENCE_DEMO_ENABLED, CONFLUENCE_DEMO_SYMBOLS,
                              CONFLUENCE_DEMO_LTF, CONFLUENCE_DEMO_HTF,
                              CONFLUENCE_CRYPTO_ENABLED, CONFLUENCE_CRYPTO_SYMBOLS)
    import os
    from core.confluence_demo_engine import status_snapshot
    snap = status_snapshot()
    watchlist = (list(CONFLUENCE_DEMO_SYMBOLS) if CONFLUENCE_DEMO_ENABLED else []) + \
                (list(CONFLUENCE_CRYPTO_SYMBOLS) if CONFLUENCE_CRYPTO_ENABLED else [])
    return {
        "enabled": CONFLUENCE_DEMO_ENABLED or CONFLUENCE_CRYPTO_ENABLED,
        "orders_armed": os.getenv("DEMO_EXEC_ENABLED", "0") == "1",
        "watchlist": watchlist,
        "crypto_enabled": CONFLUENCE_CRYPTO_ENABLED,
        "ltf": CONFLUENCE_DEMO_LTF, "htf": CONFLUENCE_DEMO_HTF,
        **snap,   # heartbeat + symbols (décisions) + recent
    }


@app.get("/health")
async def health_pyramid():
    """Santé de la PYRAMIDE (réorg Phase 2, `core/health.py`) : socle/journal non censuré,
    fusion N3 (heartbeat + pôles), risque N4, exécution N5 (equity/positions démo), ressources.
    Lecture seule, non bloquant. Complémentaire de /health/system (agent indépendant)."""
    import asyncio as _aio
    from core.health import health_snapshot
    return await _aio.to_thread(health_snapshot)


@app.get("/health/system")
async def health_system():
    """État produit par l'AGENT DE SANTÉ (`tools/health_agent.py`), lu depuis son fichier.

    ⚠️ On LIT seulement : l'agent est un processus INDÉPENDANT, à dessein. S'il tournait ici,
    il serait gelé en même temps que l'API le jour où celle-ci s'emballe — et ne signalerait
    rien (incident du 21/07/2026). Cette route n'est qu'une fenêtre sur son travail ; les
    alertes, elles, partent de lui directement en fenêtre Windows, sans dépendre d'ici."""
    from pathlib import Path as _P
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    f = _P(__file__).resolve().parent.parent / "data" / "health_status.json"
    try:
        etat = _json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"sante": "inconnue", "agent": "arrete",
                "note": "Agent de santé non démarré : venv\\Scripts\\python.exe tools\\health_agent.py"}
    except Exception as exc:  # noqa: BLE001
        return {"sante": "inconnue", "agent": "illisible", "detail": repr(exc)}
    # Un état figé est un état MENSONGER : si l'agent est mort, on le dit.
    try:
        age = (_dt.now(_tz.utc) - _dt.fromisoformat(etat["ts"])).total_seconds()
        etat["age_s"] = round(age, 1)
        if age > 180:
            etat["agent"] = "muet"
            etat["sante"] = "inconnue"
            etat["note"] = f"Aucune mise à jour depuis {age:.0f}s — l'agent de santé ne tourne plus."
        else:
            etat["agent"] = "actif"
    except Exception:  # noqa: BLE001
        etat["agent"] = "inconnu"
    return etat


@app.get("/brain/master")
async def brain_master_status():
    """PORTE NEURONALE — vue MASTER (Florent). Directives en cours + verdict EFFECTIF du
    cerveau par symbole (ce qui se passerait maintenant : entrée autorisée/bloquée et par qui).
    Lecture seule. Le cerveau décide en AUTO ; Florent prime en FORCE_LONG/FORCE_SHORT/BLOCK/PAUSE."""
    from core.brain_gate import all_masters, gate_entry, AUTO, FORCE_LONG, FORCE_SHORT, BLOCK, PAUSE
    from core.confluence_demo_engine import status_snapshot
    snap = status_snapshot()
    verdicts = {}
    for sym, s in (snap.get("symbols") or {}).items():
        try:
            g = gate_entry(sym, int(s.get("side") or 0))
            verdicts[sym] = {"allow": g.allow, "side": g.side, "source": g.source,
                             "verdict": g.verdict, "conviction": round(g.conviction, 3),
                             "reason_codes": list(g.reason_codes)}
        except Exception as exc:  # noqa: BLE001
            verdicts[sym] = {"allow": False, "conviction": 0.0, "source": "BRAIN",
                             "reason_codes": [repr(exc)]}
    return {"directives": all_masters(),
            "modes": [AUTO, FORCE_LONG, FORCE_SHORT, BLOCK, PAUSE],
            "note": "AUTO=le cerveau décide ; '*'=directive globale ; le master prime toujours.",
            "brain": verdicts}


@app.post("/brain/master", dependencies=[Depends(require_admin)])
async def brain_master_set(request: FARequest):
    """MASTER (Florent) pose/lève une directive : {symbol, mode}. `symbol='*'` = global.
    modes : AUTO (rend la main au cerveau), FORCE_LONG, FORCE_SHORT, BLOCK, PAUSE. Persisté."""
    body = await request.json()
    symbol = str(body.get("symbol") or "").strip()
    mode = str(body.get("mode") or "").strip().upper()
    if not symbol:
        raise HTTPException(400, "symbol requis (ou '*' pour global)")
    from core.brain_gate import set_master
    try:
        directives = set_master(symbol, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "symbol": symbol, "mode": mode, "directives": directives}


_DASHBOARD_ORBE = Path(__file__).resolve().parent.parent / "titanium_orbe.html"


_DASHBOARD_EMOTION = Path(__file__).resolve().parent.parent / "titanium_emotion.html"


@app.get("/emotions", response_class=HTMLResponse)
async def dashboard_emotion():
    """Carte d'ÉMOTION du marché — dôme valence×énergie, actifs crypto + MT5.
    Route au PLURIEL : /emotion/{symbole} est l'API JSON, /emotions est la vue.
    Relue à chaque requête (itérations HTML sans redémarrage). Read-only."""
    if _DASHBOARD_EMOTION.exists():
        return HTMLResponse(_DASHBOARD_EMOTION.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Émotion</h1><p>titanium_emotion.html non trouvé.</p>")


@app.get("/orbe", response_class=HTMLResponse)
async def dashboard_orbe():
    """Cockpit ORBE (refonte DASH 07/2026) — orbe JARVIS/Hermes au centre.
    Cahier des charges co-signé : collab/DASH_DESIGN.md. Relu à chaque requête
    (itérations HTML sans redémarrage)."""
    if _DASHBOARD_ORBE.exists():
        return HTMLResponse(_DASHBOARD_ORBE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Orbe</h1><p>titanium_orbe.html non trouvé.</p>")


@app.get("/nexus")
async def dashboard_nexus():
    """Acces lecture seule au registre GitNexus, sans remplacer l'orbe.

    Health-check résilient : GitNexus peut n'écouter que sur IPv6 (::1) ou
    IPv4 (127.0.0.1) selon l'environnement — on teste les deux avant de
    rediriger vers l'URL amie du navigateur (localhost)."""
    browser_target = "http://localhost:4747/"
    probes = ("http://127.0.0.1:4747/api/health",
              "http://localhost:4747/api/health")
    for probe in probes:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    probe, timeout=aiohttp.ClientTimeout(total=1.5)
                ) as response:
                    if response.status == 200:
                        return RedirectResponse(browser_target, status_code=307)
        except Exception:
            continue
    return HTMLResponse(
        "<h1>GitNexus indisponible</h1>"
        "<p>Le registre local localhost:4747 ne répond pas.</p>"
        "<p>Lancer <code>tools\\gitnexus_session.ps1</code>, puis recharger. "
        "L’orbe reste disponible sur <a href='/orbe'>/orbe</a>.</p>",
        status_code=503,
    )


_NEURAL_MAP = Path(__file__).resolve().parent.parent / "data" / "neural_map.json"


@app.get("/orbe/map")
async def orbe_neural_map():
    """Topologie RÉELLE du bot (modules + imports, gen_neural_map.py) pour le
    mode RÉSEAU NEURONAL de l'orbe. Lecture seule ; regénérer via
    `venv\\Scripts\\python.exe tools\\gen_neural_map.py` après refactor."""
    if _NEURAL_MAP.exists():
        return JSONResponse(json.loads(_NEURAL_MAP.read_text(encoding="utf-8")))
    return JSONResponse({"error": "neural_map.json absent — lancer tools/gen_neural_map.py"},
                        status_code=404)


def _health_snapshot() -> dict:
    """Santé du système : feed de données, scan prêt, uptime.

    Rendu en permanence dans le header du dashboard — le bot ne doit
    plus jamais 'tourner à vide' sans que ce soit visible d'un coup d'œil.
    """
    from data.binance_ws import candle_store
    from utils.config import MIN_DF30_FOR_SCAN
    candles = {}
    for sym in SYMBOLS:
        df = candle_store.get(sym)
        n = len(df) if df is not None else 0
        candles[sym] = {"bars": n, "ready": n >= MIN_DF30_FOR_SCAN}
    return {
        "candles":    candles,
        "scan_ready": all(c["ready"] for c in candles.values()),
        "uptime_sec": int((datetime.now(timezone.utc) - _APP_START_TS).total_seconds()),
    }


@app.get("/api/state")
async def api_state():
    """État complet : signaux, poids, historique, optimisation, paper trading."""
    from execution.executor import executor
    from fundamentals.external_feeds import get_external_snapshot
    paper_state = executor.get_state() if TRADING_MODE != "disabled" else {}
    from data.spread_tracker import spread_tracker
    from fundamentals.external_feeds import get_external_snapshot
    return JSONResponse({
        "health":          _health_snapshot(),
        "external":        get_external_snapshot(),
        "signals":         serialize_signal_states(get_all_signals(), SCORE_CRITERIA),
        "scoring_weights": scoring_weights,
        "delta_vol":       {s: {k: v for k, v in delta_vol[s].items() if k != "trades"} for s in SYMBOLS},
        "futures":         futures_store,
        "spreads":         {s: spread_tracker.get_stats(s) for s in SYMBOLS},
        "best_config":     get_opt_results(),
        "paper":           paper_state,
        "ts":              datetime.now(timezone.utc).isoformat(),
        "ws_clients":      get_client_count(),
        "version":         "v12",
        "trading_mode":    TRADING_MODE,
    })


@app.get("/api/optim/results")
async def api_optim_results():
    return JSONResponse(get_opt_results())


@app.post("/api/optim/run", dependencies=[Depends(require_admin)])
async def api_optim_run(request: FARequest):
    """Déclenche une optimisation manuelle."""
    from engine.optimizer import optimisation_loop
    import asyncio
    asyncio.create_task(optimisation_loop(request.app.state.http))
    return {"status": "started"}


@app.get("/api/delta-vol")
async def api_delta_vol():
    return JSONResponse({
        s: {k: v for k, v in delta_vol[s].items() if k != "trades"}
        for s in SYMBOLS
    })


@app.get("/api/futures/{symbol}")
async def api_futures(symbol: str):
    sym = symbol.replace("USDT", "/USDT")
    if sym not in SYMBOLS:
        raise HTTPException(404, "Symbole non trouvé")
    return JSONResponse(futures_store.get(sym, {}))


@app.get("/api/metrics")
async def api_metrics():
    return JSONResponse({
        "symbols":     SYMBOLS,
        "ws_clients":  get_client_count(),
        "signals":     {s: get_all_signals().get(s, {}).get("score", 0) for s in SYMBOLS},
        "ts":          datetime.now(timezone.utc).isoformat(),
    })


@app.post("/api/chat")
async def api_chat(request: FARequest):
    """Vision IA — analyse de chart par Ollama."""
    try:
        body        = await request.json()
        image_b64   = body.get("image", "")
        symbol      = body.get("symbol", SYMBOLS[0])
        timeframe   = body.get("timeframe", "5m")
        price       = float(body.get("price", 0))
        side_hint   = body.get("side_hint")
        algo_ctx    = body.get("algo_context")

        result = await ollama_vision_analyze(
            request.app.state.http,
            image_b64, symbol, timeframe, price, side_hint, algo_ctx,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("[API/chat] %s", e)
        raise HTTPException(500, str(e))


# ── Temps réel : ticks MT5 (ms) + carnet L2 Binance ──────────────────────────

# Watchlist MT5 poussée au dashboard (data-only). Inclut les indices validés.
RT_MT5_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAUEUR",
                  "BTCUSD", "USTECH", "NAS100.fs", "HSI.fs"]


def _clean_book(bids, asks, depth):
    """Assainit un carnet pour l'affichage : retire le dust (vieux niveaux
    micro non nettoyés par la resynchro diff) et garde-fou anti-croisement.
    Retourne (bids, asks, best_bid, best_ask, mid, spread_bps)."""
    sample = [q for _, q in (bids[:40] + asks[:40])]
    dust = (max(sample) * 0.01) if sample else 0.0
    b = [[p, q] for p, q in bids if q >= dust]
    a = [[p, q] for p, q in asks if q >= dust]
    if b and a:                                   # anti-croisement
        bb = b[0][0]
        a2 = [l for l in a if l[0] > bb]
        a = a2 or a
        ba = a[0][0]
        b2 = [l for l in b if l[0] < ba]
        b = b2 or b
    bb = b[0][0] if b else 0.0
    ba = a[0][0] if a else 0.0
    mid = (bb + ba) / 2 if (bb and ba) else 0.0
    spread = (ba - bb) / mid * 10000 if mid else 0.0
    trim = lambda rows: [[p, round(q, 4)] for p, q in rows[:depth]]
    return trim(b), trim(a), bb, ba, mid, spread


def _book_snapshot(sym: str, depth: int = 12) -> Dict[str, Any]:
    """Snapshot L2 (Binance) depuis orderbook_store, assaini pour le dashboard."""
    from data.orderbook_ws import orderbook_store
    st = orderbook_store.get(sym)
    if not st or st.ts <= 0:
        return {}
    bids, asks, bb, ba, mid, spread = _clean_book(st.bids, st.asks, depth)
    fb, fa, _, _, _, _ = _clean_book(st.futures_bids, st.futures_asks, depth)
    return {
        "symbol": sym, "source": "binance",
        "bids": bids, "asks": asks, "futures_bids": fb, "futures_asks": fa,
        "best_bid": round(bb, 2), "best_ask": round(ba, 2),
        "mid": round(mid, 2), "spread_bps": round(spread, 2), "ts": st.ts,
    }


@app.get("/mt5/ticks")
async def mt5_ticks() -> JSONResponse:
    """Fallback REST : ticks MT5 temps réel (poll rapide côté dashboard)."""
    import asyncio
    from data.mt5_provider import get_ticks_fast
    ticks = await asyncio.to_thread(get_ticks_fast, RT_MT5_SYMBOLS)
    return JSONResponse({"t": int(datetime.now(timezone.utc).timestamp() * 1000),
                         "ticks": ticks})


@app.get("/orderbook/{symbol}")
async def orderbook_snapshot(symbol: str) -> JSONResponse:
    sym = symbol.upper().replace("USDT", "/USDT")
    book = _book_snapshot(sym)
    if not book:
        raise HTTPException(404, f"Carnet indisponible pour {sym}")
    return JSONResponse(book)


# ── WebSocket ─────────────────────────────────────────────────────────────────

# --- Flux temps réel : garde-fous ANTI-EMBALLEMENT (incident du 21/07/2026) -------------
# Chaque connexion ouvrait SA PROPRE boucle 5 Hz appelant MT5 sous le `mt5_lock` partagé,
# sans plafond de clients ni nettoyage garanti. Les reconnexions du dashboard empilaient
# ces boucles : N clients = N×5 appels MT5/s en contention sur UN seul verrou → emballement
# CPU (34 372 s cumulées en 8 h) et TOUS les endpoints figés, connexion TCP acceptée mais
# aucune réponse. Trois remèdes ci-dessous.
_RT_CLIENTS: set = set()
_RT_MAX_CLIENTS = 8              # plafond dur : au-delà on refuse proprement
_RT_CACHE: Dict[str, Any] = {"at": 0.0, "ticks": None}
_RT_CACHE_TTL = 0.18             # < période d'envoi : les clients partagent LA MÊME lecture
_RT_FETCH_LOCK = None            # créé paresseusement (pas de boucle asyncio à l'import)


async def _rt_ticks():
    """Lecture MT5 MUTUALISÉE entre tous les clients du flux. Quel que soit le nombre de
    connexions, MT5 n'est interrogé qu'une fois par fenêtre : c'est ce qui supprime la
    contention sur `mt5_lock` qui faisait s'emballer le service."""
    import asyncio
    import time as _time
    global _RT_FETCH_LOCK
    if _RT_FETCH_LOCK is None:
        _RT_FETCH_LOCK = asyncio.Lock()
    async with _RT_FETCH_LOCK:
        now = _time.monotonic()
        if _RT_CACHE["ticks"] is None or (now - _RT_CACHE["at"]) > _RT_CACHE_TTL:
            from data.mt5_provider import get_ticks_fast
            _RT_CACHE["ticks"] = await asyncio.to_thread(get_ticks_fast, RT_MT5_SYMBOLS)
            _RT_CACHE["at"] = now
        return _RT_CACHE["ticks"]


@app.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    """Flux temps réel ~5 Hz : ticks MT5 (timestamp ms) + carnet L2 Binance.
    Symbole du carnet via query param ?book=BTCUSDT (défaut BTC/USDT)."""
    import asyncio
    # Réservation de la place AVANT le moindre await. Sur une boucle asyncio
    # mono-thread, test + insertion sans await entre les deux sont atomiques ;
    # tester puis `await ws.accept()` puis insérer laissait des handshakes
    # simultanés franchir le plafond ensemble (revue red-team Codex 22/07/2026).
    if len(_RT_CLIENTS) >= _RT_MAX_CLIENTS:
        logger.warning("[RT] connexion REFUSÉE : plafond atteint (%d clients). "
                       "Symptôme d'un client qui se reconnecte en boucle.", len(_RT_CLIENTS))
        await ws.close(code=1013)                      # « try again later »
        return
    _RT_CLIENTS.add(ws)
    try:
        await ws.accept()
        raw = ws.query_params.get("book", "BTC/USDT").upper().replace("USDT", "/USDT")
        book_sym = raw if raw in SYMBOLS else "BTC/USDT"
        while True:
            if (ws.client_state == WebSocketState.DISCONNECTED
                    or ws.application_state == WebSocketState.DISCONNECTED):
                break
            ticks = await _rt_ticks()
            try:
                await ws.send_json({
                    "t": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "ticks": ticks,
                    "book": _book_snapshot(book_sym),
                })
            except (WebSocketDisconnect, ConnectionError, OSError, RuntimeError):
                # Déconnexion attendue côté client : on sort proprement.
                break
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
    except Exception as exc:      # noqa: BLE001 — plus JAMAIS avalé en silence
        logger.warning("[RT] flux interrompu (%d clients) : %r", len(_RT_CLIENTS), exc)
    finally:
        _RT_CLIENTS.discard(ws)   # nettoyage GARANTI : plus de boucle orpheline


@app.websocket("/ws/{symbol}")
async def websocket_endpoint(ws: WebSocket, symbol: str):
    sym = symbol.upper().replace("USDT", "/USDT")
    if sym not in SYMBOLS:
        await ws.close(code=4000)
        return

    await ws_connect(sym, ws)
    try:
        # Envoyer l'état courant immédiatement
        current = get_all_signals().get(sym, {})
        if current:
            await ws.send_json(current)
        # Maintenir la connexion ouverte
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await ws_disconnect(sym, ws)


def run() -> None:
    uvicorn.run(
        "api.api_server:app",
        host=UVICORN_HOST,
        port=UVICORN_PORT,
        log_level=UVICORN_LOG_LEVEL,
        reload=False,
    )
