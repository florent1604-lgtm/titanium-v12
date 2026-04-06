# assistant/hotkey_manager.py -- Raccourci global Ctrl+Alt pour Titan.
#
# Flux :
#   Ctrl+Alt enfonce  -> etat "listening" (micro actif, barre verte pulse)
#   Silence detecte   -> etat "thinking" (spinner, Titan reflechit)
#   Reponse prete     -> etat "speaking" (avatar parle + lip-sync)
#   Fin               -> etat "idle"
#
# Dependances : pip install pynput keyboard

from __future__ import annotations
import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None
_busy = threading.Event()   # evite les doubles declenchements


# ── Etats visuels -> WebSocket -> avatar.js ───────────────────────────────────

async def _set_state(state: str, message: str = "") -> None:
    """Envoie l'etat courant a la page avatar via WebSocket.

    States :
      listening  - micro actif, barre verte pulse
      thinking   - spinner, attente LLM
      speaking   - avatar parle (gere par popup_manager)
      idle       - retour neutre
    """
    try:
        from assistant.avatar_renderer import ws_titan_broadcast
        await ws_titan_broadcast({"type": "state", "state": state, "message": message})
    except Exception as e:
        logger.debug("[HOTKEY] ws state '%s': %s", state, e)


def _fire_state(state: str, message: str = "") -> None:
    """Version synchrone de _set_state pour appel depuis un thread."""
    if _loop and not _loop.is_closed():
        asyncio.run_coroutine_threadsafe(_set_state(state, message), _loop)


# ── Enregistrement + reponse ─────────────────────────────────────────────────

def _record_and_respond() -> None:
    """Pipeline complet : enregistrement -> STT -> LLM -> TTS."""
    try:
        from assistant.voice_engine import get_voice_engine
        engine = get_voice_engine()

        # ── Etat 1 : LISTENING (micro actif) ──────────────────────────────
        _fire_state("listening", "Ecoute en cours...")
        logger.info("[HOTKEY] Enregistrement demarre")

        audio = engine._record_until_silence()

        if audio is None or len(audio) < 8000:
            logger.info("[HOTKEY] Trop court, ignore")
            _fire_state("idle")
            return

        # ── Etat 2 : TRANSCRIPTION ─────────────────────────────────────────
        _fire_state("thinking", "Transcription...")
        text = engine.transcribe(audio).strip()

        if not text:
            logger.info("[HOTKEY] Transcription vide, ignore")
            _fire_state("idle")
            return

        logger.info("[HOTKEY] Transcrit : '%s'", text)

        # ── Etat 3 : THINKING (LLM en cours) ──────────────────────────────
        _fire_state("thinking", f"\"{text[:40]}{'...' if len(text)>40 else ''}\"")

        # Envoyer a Titan
        if _loop and not _loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(
                _handle_command(text), _loop
            )
            future.result(timeout=60)

    except Exception as e:
        logger.error("[HOTKEY] Erreur pipeline: %s", e)
        _fire_state("idle")
    finally:
        _busy.clear()


async def _handle_command(text: str) -> None:
    """Interroge Titan et joue la reponse phrase par phrase (streaming)."""
    try:
        import aiohttp
        from assistant.titan_agent import ask_titan_stream
        from assistant.popup_manager import titan_speak

        async def _speak_sentence(phrase: str) -> None:
            """Parle une phrase dès qu'elle est disponible."""
            if not phrase:
                return
            lower = phrase.lower()
            expression = "neutral"
            if any(w in lower for w in ["excellent", "parfait", "bien", "hausse"]):
                expression = "happy"
            elif any(w in lower for w in ["attention", "risque", "baisse", "alerte"]):
                expression = "surprised"
            await titan_speak(phrase, expression=expression)

        async with aiohttp.ClientSession() as session:
            await ask_titan_stream(text, session=session, on_sentence=_speak_sentence)

    except Exception as e:
        logger.error("[HOTKEY] Erreur reponse LLM: %s", e)
        await _set_state("idle")


# ── Declenchement hotkey ──────────────────────────────────────────────────────

def _trigger() -> None:
    """Appele quand Ctrl+Alt est detecte."""
    if _busy.is_set():
        return   # deja en cours
    _busy.set()

    # Montrer la fenetre avatar
    try:
        from assistant.avatar_renderer import get_avatar_window
        get_avatar_window().show()
    except Exception:
        pass

    # Lancer le pipeline dans un thread daemon
    t = threading.Thread(target=_record_and_respond, daemon=True, name="titan-voice-pipeline")
    t.start()


# ── Listeners clavier ─────────────────────────────────────────────────────────

def _start_pynput() -> None:
    """Listener pynput -- fonctionne sans droits admin."""
    from pynput import keyboard as pk

    ctrl  = threading.Event()
    alt   = threading.Event()
    fired = threading.Event()

    CTRL_KEYS = {pk.Key.ctrl, pk.Key.ctrl_l, pk.Key.ctrl_r}
    ALT_KEYS  = {pk.Key.alt,  pk.Key.alt_l,  pk.Key.alt_r, pk.Key.alt_gr}

    def on_press(key):
        if key in CTRL_KEYS: ctrl.set()
        if key in ALT_KEYS:  alt.set()
        if ctrl.is_set() and alt.is_set() and not fired.is_set():
            fired.set()
            _trigger()

    def on_release(key):
        if key in CTRL_KEYS: ctrl.clear()
        if key in ALT_KEYS:  alt.clear()
        if not ctrl.is_set() and not alt.is_set():
            fired.clear()

    listener = pk.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    logger.info("[HOTKEY] Ctrl+Alt actif (pynput)")
    listener.join()   # bloque le thread


def _start_keyboard_lib() -> None:
    """Listener keyboard -- necessite admin sur Windows."""
    import keyboard
    keyboard.add_hotkey("ctrl+alt", _trigger, suppress=False)
    logger.info("[HOTKEY] Ctrl+Alt actif (keyboard lib)")
    keyboard.wait()   # bloque le thread


def start_hotkey_listener(loop: asyncio.AbstractEventLoop) -> None:
    """Demarre le listener dans un thread daemon (essaie pynput puis keyboard)."""
    global _loop
    _loop = loop

    def _run():
        try:
            _start_pynput()
        except ImportError:
            try:
                _start_keyboard_lib()
            except ImportError:
                logger.warning("[HOTKEY] Installer pynput : pip install pynput")
        except Exception as e:
            logger.error("[HOTKEY] Erreur listener: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="titan-hotkey")
    t.start()
