"""api/latency_routes.py — Benchmark de latence multi-plateformes.

POST /latency/run   → lance un benchmark en tâche de fond
GET  /latency/status → idle | running | done
GET  /latency/report → dernier rapport (mémoire, sinon data/latency_report.json)
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FARequest
from fastapi.responses import JSONResponse

from api.auth import require_admin

from tools.latency_bench import (
    REPORT_PATH, latency_state, run_benchmark,
)
from utils.config import LATENCY_DEFAULT_SECONDS, LATENCY_SYMBOL
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/latency", tags=["latency"])
_ADMIN = [Depends(require_admin)]


@router.post("/run", dependencies=_ADMIN)
async def latency_run(request: FARequest) -> JSONResponse:
    """Body optionnel: {"duration_s": 60, "symbol": "BTC/USDT"}."""
    if latency_state["status"] == "running":
        raise HTTPException(409, "Un benchmark est déjà en cours")
    try:
        body = await request.json()
    except Exception:
        body = {}
    duration = int(body.get("duration_s", LATENCY_DEFAULT_SECONDS))
    duration = max(20, min(duration, 600))
    symbol   = body.get("symbol", LATENCY_SYMBOL)

    asyncio.create_task(
        run_benchmark(duration, symbol, request.app.state.http),
        name="latency_benchmark",
    )
    return JSONResponse({"status": "started", "duration_s": duration,
                         "symbol": symbol})


@router.get("/status")
async def latency_status() -> JSONResponse:
    return JSONResponse({
        "status":     latency_state["status"],
        "started_at": latency_state["started_at"],
    })


@router.get("/report")
async def latency_report() -> JSONResponse:
    if latency_state["report"]:
        return JSONResponse(latency_state["report"])
    if REPORT_PATH.exists():
        return JSONResponse(json.loads(REPORT_PATH.read_text(encoding="utf-8")))
    raise HTTPException(404, "Aucun rapport — lancer POST /latency/run d'abord")
