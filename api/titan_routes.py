"""api/titan_routes.py — Routes FastAPI pour l'assistant Titan.

Endpoints :
  GET  /assistant/          → Sert la page HTML de l'avatar
  GET  /assistant/{file}    → Fichiers statiques (JS, CSS, VRM)
  WS   /titan/ws            → WebSocket pour les blendshapes en temps réel
  POST /titan/speak         → Faire parler Titan via API
  GET  /titan/status        → État de l'assistant
  POST /titan/command       → Envoyer une commande textuelle à Titan
  POST /titan/clear-history → Effacer l'historique de conversation
"""
from __future__ import annotations
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request as FARequest
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from api.auth import require_admin

from assistant.config import TITAN_WEB_DIR, TITAN_ASSISTANT_DIR, TITAN_ENABLED

logger = logging.getLogger(__name__)
router = APIRouter(tags=["titan"])
_ADMIN = [Depends(require_admin)]

# Ajouter le type MIME pour les fichiers VRM
mimetypes.add_type("model/gltf-binary", ".vrm")
mimetypes.add_type("model/gltf-binary", ".glb")


# ── Fichiers statiques avatar ─────────────────────────────────────────────────

@router.get("/assistant/")
async def avatar_page():
    """Sert la page principale de l'avatar VRM (injecte le nom du fichier VRM)."""
    from assistant.config import TITAN_AVATAR_FILE
    index = TITAN_WEB_DIR / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>Titan — Page non trouvée</h1>"
            "<p>Vérifier que assistant/web/index.html existe.</p>",
            status_code=404,
        )
    # Injecter le nom du VRM dans la meta tag
    html = index.read_text(encoding="utf-8")
    html = html.replace(
        'content="VRoid_V110_Male_v1.1.3.vrm"',
        f'content="{TITAN_AVATAR_FILE}"',
    )
    return HTMLResponse(html)


@router.get("/assistant/{file_path:path}")
async def avatar_static(file_path: str):
    """Sert les fichiers statiques de l'assistant (JS, CSS, VRM…)."""
    # Sécurité : pas de traversal
    if ".." in file_path:
        raise HTTPException(403, "Accès refusé")

    # Chercher dans web/ d'abord, puis dans assistant/
    candidates = [
        TITAN_WEB_DIR / file_path,
        TITAN_ASSISTANT_DIR / file_path,
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            return FileResponse(str(path), media_type=media_type)

    raise HTTPException(404, f"Fichier non trouvé: {file_path}")


# ── WebSocket blendshapes ─────────────────────────────────────────────────────

@router.websocket("/titan/ws")
async def titan_ws(ws: WebSocket):
    """WebSocket pour les mises à jour de blendshapes en temps réel."""
    from assistant.avatar_renderer import ws_titan_connect, ws_titan_disconnect

    await ws.accept()
    await ws_titan_connect(ws)

    try:
        while True:
            # Garder la connexion ouverte — le client peut envoyer des pings
            msg = await ws.receive_text()
            logger.debug("[TITAN/WS] Message reçu: %s", msg[:100])
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("[TITAN/WS] Déconnecté: %s", e)
    finally:
        await ws_titan_disconnect(ws)


# ── API Titan ─────────────────────────────────────────────────────────────────

@router.post("/titan/speak", dependencies=_ADMIN)
async def titan_speak_api(request: FARequest):
    """Fait parler Titan avec un texte arbitraire.

    Body JSON: {"text": "...", "expression": "neutral|happy|thinking"}
    """
    if not TITAN_ENABLED:
        raise HTTPException(503, "TITAN_ENABLED=0")

    try:
        body       = await request.json()
        text       = str(body.get("text", "")).strip()
        expression = str(body.get("expression", "neutral"))

        if not text:
            raise HTTPException(422, "Champ 'text' requis")

        # Déclencher en arrière-plan pour ne pas bloquer la réponse HTTP
        import asyncio
        from assistant.popup_manager import titan_speak
        asyncio.create_task(titan_speak(text, expression=expression))

        return JSONResponse({"status": "speaking", "text": text[:80]})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TITAN/API] speak: %s", e)
        raise HTTPException(500, str(e))


@router.post("/titan/command", dependencies=_ADMIN)
async def titan_command_api(request: FARequest):
    """Envoie une commande textuelle à Titan et retourne la réponse.

    Body JSON: {"command": "quel est le signal BTC ?"}
    Répond AUSSI vocalement si TITAN_ENABLED=1.
    """
    try:
        body    = await request.json()
        command = str(body.get("command", "")).strip()
        speak   = bool(body.get("speak", True))

        if not command:
            raise HTTPException(422, "Champ 'command' requis")

        import aiohttp
        from assistant.titan_agent import ask_titan

        async with aiohttp.ClientSession() as session:
            response = await ask_titan(command, session=session)

        if speak and TITAN_ENABLED:
            import asyncio
            from assistant.popup_manager import titan_speak
            asyncio.create_task(titan_speak(response))

        return JSONResponse({"status": "ok", "command": command, "response": response})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TITAN/API] command: %s", e)
        raise HTTPException(500, str(e))


@router.get("/titan/status")
async def titan_status():
    """État complet de l'assistant Titan."""
    from assistant.tts_engine import get_tts
    from assistant.popup_manager import get_popup_manager
    from assistant.avatar_renderer import _titan_ws_clients

    tts     = get_tts()
    popup   = get_popup_manager()

    return JSONResponse({
        "enabled":         TITAN_ENABLED,
        "speaking":        popup.is_speaking,
        "tts_available":   tts.available,
        "ws_clients":      len(_titan_ws_clients),
        "avatar_path":     str(TITAN_ASSISTANT_DIR),
    })


@router.post("/titan/clear-history", dependencies=_ADMIN)
async def titan_clear_history():
    """Efface l'historique de conversation de Titan."""
    from assistant.titan_agent import clear_history
    clear_history()
    return JSONResponse({"status": "ok", "message": "Historique effacé"})
