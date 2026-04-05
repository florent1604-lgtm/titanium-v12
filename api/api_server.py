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
from utils.config import (
    UVICORN_HOST, UVICORN_PORT, UVICORN_LOG_LEVEL,
    HTTP_POOL_SIZE, HTTP_CONNECT_LIMIT, HTTP_TIMEOUT_TOTAL,
    SYMBOLS, FUNDAMENTALS_ENABLED,
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
    ]
    if FUNDAMENTALS_ENABLED:
        tasks.append(asyncio.create_task(fundamentals_loop(session), name="fundamentals"))

    logger.info("[APP] Titanium v12 démarré — %d tâches actives", len(tasks))
    yield

    # Arrêt propre
    for t in tasks:
        t.cancel()
    await session.close()
    logger.info("[APP] Titanium v12 arrêté proprement")


app = FastAPI(title="Titanium v12", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

from api.fundamentals_routes import router as fundamentals_router
app.include_router(fundamentals_router)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Sert le dashboard HTML v11 tel quel."""
    if _DASHBOARD_HTML.exists():
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Titanium v12</h1><p>Dashboard HTML non trouvé.</p>")


@app.get("/api/state")
async def api_state():
    """État complet : signaux, poids, historique, optimisation."""
    return JSONResponse({
        "signals":         get_all_signals(),
        "scoring_weights": scoring_weights,
        "delta_vol":       {s: {k: v for k, v in delta_vol[s].items() if k != "trades"} for s in SYMBOLS},
        "futures":         futures_store,
        "best_config":     get_opt_results(),
        "ts":              datetime.now(timezone.utc).isoformat(),
        "ws_clients":      get_client_count(),
        "version":         "v12",
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
