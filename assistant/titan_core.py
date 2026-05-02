"""assistant/titan_core.py — Point d'entrée principal de l'assistant Titan.

Démarre :
  1. La fenêtre PyWebView (thread dédié)
  2. Le moteur vocal (thread dédié)
  3. La boucle de rapport quotidien (tâche asyncio)

Usage depuis main.py / api_server.py :
    from assistant.titan_core import start_titan, stop_titan
    await start_titan(session)  # dans lifespan FastAPI
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

import aiohttp

from assistant.config import TITAN_ENABLED

logger = logging.getLogger(__name__)

_titan_tasks = []
_voice_engine = None
_avatar_window = None


async def start_titan(session: Optional[aiohttp.ClientSession] = None) -> None:
    """Démarre tous les composants de Titan."""
    if not TITAN_ENABLED:
        logger.info("[TITAN] Désactivé (TITAN_ENABLED=0)")
        return

    global _voice_engine, _avatar_window

    logger.info("[TITAN] Démarrage de l'assistant Titan…")

    # ── 1. Fenêtre avatar ──────────────────────────────────────────────────
    try:
        from assistant.avatar_renderer import get_avatar_window
        _avatar_window = get_avatar_window()
        _avatar_window.start()   # thread PyWebView
        logger.info("[TITAN] Fenêtre avatar initialisée")
    except Exception as e:
        logger.warning("[TITAN] Avatar non disponible: %s", e)

    # ── 2. Moteur vocal (wake word + STT) ──────────────────────────────────
    try:
        from assistant.voice_engine import get_voice_engine
        loop = asyncio.get_event_loop()
        _voice_engine = get_voice_engine()
        _voice_engine.start(on_command=_handle_voice_command, loop=loop)
        logger.info("[TITAN] Écoute vocale démarrée — wake words: %s",
                    __import__('assistant.config', fromlist=['TITAN_WAKE_WORDS']).TITAN_WAKE_WORDS)
    except Exception as e:
        logger.warning("[TITAN] Moteur vocal non disponible: %s", e)

    # ── 3. Raccourci clavier Ctrl+Alt ─────────────────────────────────────
    try:
        from assistant.hotkey_manager import start_hotkey_listener
        loop = asyncio.get_event_loop()
        start_hotkey_listener(loop)
        logger.info("[TITAN] Raccourci Ctrl+Alt actif")
    except Exception as e:
        logger.warning("[TITAN] Raccourci clavier non disponible: %s", e)

    # ── 5. Rapport quotidien ───────────────────────────────────────────────
    try:
        from assistant.daily_report import daily_report_loop
        task = asyncio.create_task(daily_report_loop(session), name="titan-report")
        _titan_tasks.append(task)
    except Exception as e:
        logger.warning("[TITAN] Rapport quotidien non démarré: %s", e)

    # ── 6. Message de bienvenue ────────────────────────────────────────────
    asyncio.create_task(_welcome_message(session))

    logger.info("[TITAN] Assistant opérationnel")


async def _welcome_message(session: Optional[aiohttp.ClientSession]) -> None:
    """Message de bienvenue au démarrage (après 3 secondes)."""
    await asyncio.sleep(3)
    try:
        from assistant.popup_manager import titan_speak
        await titan_speak(
            "Titan en ligne. Je surveille les marchés. À votre service.",
            expression="neutral",
        )
    except Exception as e:
        logger.debug("[TITAN] Message bienvenue: %s", e)


async def _handle_voice_command(command: str) -> None:
    """Traite une commande vocale reçue du moteur STT."""
    if not command:
        return

    logger.info("[TITAN] Commande vocale: '%s'", command)

    # Orb: passer en mode listening pendant le traitement
    try:
        from assistant.avatar_renderer import ws_titan_broadcast
        await ws_titan_broadcast({"type": "orb_state", "state": "listening"})
    except Exception:
        pass

    try:
        import aiohttp as _aio
        from assistant.titan_agent import ask_titan
        from assistant.popup_manager import titan_speak

        async with _aio.ClientSession() as session:
            response = await ask_titan(command, session=session)

        # Analyser le ton de la réponse pour l'expression
        expression = "neutral"
        response_lower = response.lower()
        if any(w in response_lower for w in ["excellent", "parfait", "bravo", "bien"]):
            expression = "happy"
        elif any(w in response_lower for w in ["attention", "risque", "danger", "alerte"]):
            expression = "surprised"

        await titan_speak(response, expression=expression)

    except Exception as e:
        logger.error("[TITAN] Erreur traitement commande: %s", e)
        try:
            from assistant.popup_manager import titan_speak
            await titan_speak("Désolé, une erreur est survenue lors du traitement de votre commande.")
        except Exception:
            pass


async def stop_titan() -> None:
    """Arrête proprement tous les composants de Titan."""
    global _voice_engine, _avatar_window

    if _voice_engine:
        _voice_engine.stop()

    for task in _titan_tasks:
        task.cancel()

    if _avatar_window:
        _avatar_window.stop()

    logger.info("[TITAN] Assistant arrêté")
