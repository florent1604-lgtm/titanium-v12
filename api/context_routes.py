"""api/context_routes.py — Pack de connaissance expert Titanium pour JARVIS.

GET  /context/expert → le contexte expert (markdown vivant) — pour injection
                       dans le prompt système de JARVIS.
POST /context/regen  → régénère C:\\Program Files\\JARVIS\\knowledge\\TITANIUM_CONTEXT.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse

from api.auth import require_admin

from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/context", tags=["context"])
_ADMIN = [Depends(require_admin)]


@router.get("/expert")
async def context_expert(fmt: str = "text"):
    """Contexte expert Titanium (markdown vivant). ?fmt=json pour l'envelopper."""
    from tools.gen_jarvis_knowledge import build_markdown
    md = build_markdown()
    if fmt == "json":
        return JSONResponse({"markdown": md, "chars": len(md)})
    return PlainTextResponse(md)


@router.post("/regen", dependencies=_ADMIN)
async def context_regen() -> JSONResponse:
    """Régénère le fichier de connaissance dans le dossier JARVIS."""
    from tools.gen_jarvis_knowledge import write
    try:
        p = write()
        return JSONResponse({"status": "ok", "path": str(p), "bytes": p.stat().st_size})
    except Exception as e:
        logger.warning("[CONTEXT] régénération échouée: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)
