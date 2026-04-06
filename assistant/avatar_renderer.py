"""assistant/avatar_renderer.py — Gestion de la fenêtre popup + bridge WS vers Three.js.

Architecture :
  - PyWebView ouvre une fenêtre chromium-lite (très léger)
  - La page HTML charge le VRM via Three.js + @pixiv/three-vrm
  - Python envoie les données d'animation via WebSocket (/titan/ws dans FastAPI)
  - La page JS reçoit les frames lip-sync et met à jour les blendshapes

Thread model :
  - PyWebView DOIT tourner sur le thread principal (Windows)
  - → On l'isole dans un thread dédié lancé au démarrage
  - Le thread asyncio communique via asyncio.Queue → thread pywebview

Dépendances :
  pip install pywebview
"""
from __future__ import annotations
import asyncio
import json
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Set

from assistant.config import (
    TITAN_WINDOW_WIDTH, TITAN_WINDOW_HEIGHT, TITAN_API_BASE,
)

logger = logging.getLogger(__name__)

# ── WebSocket manager (côté FastAPI) ─────────────────────────────────────────
# Les clients (pages HTML Titan) qui sont connectés au WS /titan/ws

_titan_ws_clients: Set[Any] = set()
_titan_ws_lock = asyncio.Lock()


async def ws_titan_connect(ws) -> None:
    async with _titan_ws_lock:
        _titan_ws_clients.add(ws)
    logger.debug("[AVATAR] Client WS connecté (total: %d)", len(_titan_ws_clients))


async def ws_titan_disconnect(ws) -> None:
    async with _titan_ws_lock:
        _titan_ws_clients.discard(ws)
    logger.debug("[AVATAR] Client WS déconnecté (total: %d)", len(_titan_ws_clients))


async def ws_titan_broadcast(message: Dict[str, Any]) -> None:
    """Envoie un message JSON à tous les clients WS Titan connectés."""
    if not _titan_ws_clients:
        return
    payload = json.dumps(message)
    dead = set()
    for ws in list(_titan_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    for ws in dead:
        await ws_titan_disconnect(ws)


# ── Commandes d'animation ─────────────────────────────────────────────────────

async def send_expression(name: str, weight: float = 1.0, duration_ms: int = 300) -> None:
    """Envoie une expression faciale au renderer."""
    await ws_titan_broadcast({
        "type":     "expression",
        "name":     name,
        "weight":   round(weight, 3),
        "duration": duration_ms,
    })


async def send_blend_shapes(shapes: Dict[str, float], duration_ms: int = 33) -> None:
    """Envoie une mise à jour de blendshapes au renderer."""
    await ws_titan_broadcast({
        "type":     "blend",
        "shapes":   {k: round(v, 3) for k, v in shapes.items()},
        "duration": duration_ms,
    })


async def send_speaking(value: bool) -> None:
    """Signale le début/fin de parole au renderer."""
    await ws_titan_broadcast({"type": "speaking", "value": value})


async def send_reset() -> None:
    """Remet toutes les expressions à 0 (neutre)."""
    await ws_titan_broadcast({"type": "reset"})


# ── Lecture des frames lip-sync ───────────────────────────────────────────────

async def play_lip_frames(frames: List[Any]) -> None:
    """Joue les frames lip-sync en les envoyant au rythme des timestamps.

    Args:
        frames: Liste de LipFrame (time_ms, shapes)
    """
    if not frames:
        return

    await send_speaking(True)
    start_time = time.monotonic()

    for frame in frames:
        # Attendre jusqu'au bon timestamp
        target_t = start_time + frame.time_ms / 1000.0
        now      = time.monotonic()
        if target_t > now:
            await asyncio.sleep(target_t - now)

        await send_blend_shapes(frame.shapes, duration_ms=33)

    await send_speaking(False)
    await send_reset()


# ── Fenêtre PyWebView ─────────────────────────────────────────────────────────

class AvatarWindow:
    """Gère la fenêtre popup PyWebView dans son propre thread.

    Usage:
        win = AvatarWindow()
        win.start()         # démarre le thread WebView
        win.show()          # affiche la fenêtre
        win.hide()          # cache la fenêtre
        win.stop()          # termine le thread
    """

    def __init__(self) -> None:
        self._window  = None
        self._thread  = None
        self._started = threading.Event()
        self._cmd_q: queue.Queue = queue.Queue()
        self._url     = f"{TITAN_API_BASE}/assistant/"

    def start(self) -> None:
        """Démarre le thread PyWebView (non-bloquant)."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="titan-webview",
        )
        self._thread.start()
        self._started.wait(timeout=10)

    def _run(self) -> None:
        """Boucle principale PyWebView — doit tourner dans son thread."""
        try:
            import webview
            self._window = webview.create_window(
                title="Titan",
                url=self._url,
                width=TITAN_WINDOW_WIDTH,
                height=TITAN_WINDOW_HEIGHT,
                resizable=False,
                on_top=True,
                frameless=False,
                shadow=True,
                transparent=False,
                background_color="#0d0d1a",
                min_size=(320, 480),
            )
            self._started.set()

            # Traiter les commandes pendant l'exécution
            def on_loaded():
                logger.info("[AVATAR] Fenêtre WebView chargée")

            self._window.events.loaded += on_loaded

            # Démarrer PyWebView (bloquant jusqu'à fermeture)
            webview.start(debug=False, http_server=False)

        except ImportError:
            logger.warning("[AVATAR] PyWebView non installé : pip install pywebview")
            self._started.set()
        except Exception as e:
            logger.error("[AVATAR] Erreur WebView: %s", e)
            self._started.set()

    def show(self) -> None:
        """Affiche la fenêtre."""
        if self._window:
            try:
                self._window.show()
            except Exception as e:
                logger.debug("[AVATAR] show: %s", e)

    def hide(self) -> None:
        """Cache la fenêtre."""
        if self._window:
            try:
                self._window.hide()
            except Exception as e:
                logger.debug("[AVATAR] hide: %s", e)

    def stop(self) -> None:
        """Ferme la fenêtre et le thread."""
        if self._window:
            try:
                import webview
                webview.destroy_window(self._window)
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return self._window is not None


# Singleton
_avatar_window: Optional[AvatarWindow] = None


def get_avatar_window() -> AvatarWindow:
    global _avatar_window
    if _avatar_window is None:
        _avatar_window = AvatarWindow()
    return _avatar_window
