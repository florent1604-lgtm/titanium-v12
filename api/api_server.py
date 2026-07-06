"""api/api_server.py — FastAPI : routes REST + WebSocket + dashboard HTML."""
from __future__ import annotations
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request as FARequest
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from utils.config import (
    UVICORN_HOST, UVICORN_PORT, UVICORN_LOG_LEVEL,
    HTTP_POOL_SIZE, HTTP_CONNECT_LIMIT, HTTP_TIMEOUT_TOTAL,
    SYMBOLS, FUNDAMENTALS_ENABLED, TRADING_MODE,
)
from utils.logger import get_logger
from api.websocket import broadcast, ws_connect, ws_disconnect, get_client_count
from execution.signal_manager import get_all_signals
from engine.optimizer import get_opt_results
from engine.learning_engine import scoring_weights, signal_history
from data.binance_ws import delta_vol
from data.futures_data import futures_store
from vision.ollama_vision import ollama_vision_analyze, check_ollama_available

logger = get_logger(__name__)

# Chemin du dashboard HTML v12
_DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "titanium_v12_dashboard.html"


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
    from data.binance_ws import ws_binance
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
from assistant.alexa_connector import router as alexa_router

app.include_router(fundamentals_router)
app.include_router(paper_router)
app.include_router(webhook_router)
app.include_router(titan_router)
app.include_router(services_router)
app.include_router(cockpit_router)
app.include_router(alexa_router)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Sert le dashboard HTML v11 tel quel."""
    if _DASHBOARD_HTML.exists():
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium v12</h1><p>Dashboard HTML non trouvé.</p>")


_DASHBOARD_V13 = Path(__file__).resolve().parent.parent / "titanium_v13_dashboard.html"
_APP_START_TS = datetime.now(timezone.utc)


@app.get("/v13", response_class=HTMLResponse)
async def dashboard_v13():
    """Dashboard v13 — un écran : santé, capital, vision."""
    if _DASHBOARD_V13.exists():
        return HTMLResponse(_DASHBOARD_V13.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium v13</h1><p>Dashboard v13 non trouvé.</p>")


def _health_snapshot() -> dict:
    """Santé du système : feed de données, scan prêt, uptime."""
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
    paper_state = executor.get_state() if TRADING_MODE != "disabled" else {}
    from data.spread_tracker import spread_tracker
    from fundamentals.external_feeds import get_external_snapshot
    return JSONResponse({
        "health":          _health_snapshot(),
        "external":        get_external_snapshot(),
        "signals":         get_all_signals(),
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


@app.post("/api/optim/run")
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


# ── WebSocket ─────────────────────────────────────────────────────────────────

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
