"""api/opportunity_routes.py — Scan d'opportunités périodique (cron in-app).

GET  /opportunities/status → dernier scan, classement, nouvelles opportunités, alerte
POST /opportunities/run    → force un scan immédiat (asynchrone, tourne en fond)
POST /opportunities/ack    → acquitte l'alerte sonore (une fois jouée)
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.auth import require_admin

from core.opportunity_scan import ack_alert, get_status, opp_state, run_scan_once
from utils.config import OPP_SCAN_ENABLED
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/opportunities", tags=["opportunities"])
_ADMIN = [Depends(require_admin)]


@router.get("/status")
async def opportunities_status() -> JSONResponse:
    return JSONResponse({"enabled": OPP_SCAN_ENABLED, **get_status()})


@router.post("/run", dependencies=_ADMIN)
async def opportunities_run() -> JSONResponse:
    if opp_state.get("running"):
        return JSONResponse({"status": "already_running"})
    # lancer en tâche de fond : le scan complet dure plusieurs minutes
    asyncio.create_task(run_scan_once(manual=True))
    return JSONResponse({"status": "started",
                         "note": "scan lancé en fond — suivre /opportunities/status"})


@router.post("/ack", dependencies=_ADMIN)
async def opportunities_ack() -> JSONResponse:
    ack_alert()
    return JSONResponse({"status": "acked"})
