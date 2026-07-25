"""assistant/popup_manager.py — Orchestrateur : texte → TTS → lip-sync → avatar.

Flux complet d'une réponse vocale :
  1. Ouvrir la fenêtre popup (si pas déjà ouverte)
  2. Synthesize(texte) → audio + durée
  3. Générer les frames lip-sync (phonèmes + RMS combinés)
  4. Lancer en parallèle :
     - Lecture audio (sounddevice)
     - Envoi des frames lip-sync via WebSocket
  5. Attendre la fin de la lecture
  6. Masquer la fenêtre après 2 secondes
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from assistant.config import TITAN_POPUP_AUTO_SHOW

logger = logging.getLogger(__name__)


class PopupManager:
    """Gère le cycle de vie complet d'une réponse Titan."""

    def __init__(self) -> None:
        self._speaking      = False
        self._auto_hide_task: Optional[asyncio.Task] = None

    async def speak(
        self,
        text: str,
        expression: str = "neutral",
        show_window: bool = TITAN_POPUP_AUTO_SHOW,
    ) -> None:
        """Fait parler Titan avec animation avatar synchronisée.

        Args:
            text: Texte à prononcer.
            expression: Expression faciale ('neutral', 'happy', 'thinking').
            show_window: Ouvrir la fenêtre popup si True.
        """
        if self._speaking:
            logger.warning("[POPUP] Déjà en train de parler — requête ignorée")
            return

        self._speaking = True

        # Annuler l'auto-hide en cours si besoin
        if self._auto_hide_task and not self._auto_hide_task.done():
            self._auto_hide_task.cancel()

        # Orb: passer en mode speaking
        try:
            from assistant.avatar_renderer import ws_titan_broadcast
            asyncio.create_task(ws_titan_broadcast({"type": "orb_state", "state": "speaking"}))
        except Exception:
            pass

        try:
            from assistant.tts_engine import get_tts
            from assistant.lip_sync import generate_lip_frames, generate_rms_frames, blend_frames
            from assistant.avatar_renderer import (
                get_avatar_window, play_lip_frames, send_expression, send_reset
            )

            tts    = get_tts()
            window = get_avatar_window()

            # Montrer la fenêtre
            if show_window:
                window.show()

            # Définir l'expression faciale de base
            await send_expression(expression, weight=0.6, duration_ms=500)

            # Synthèse vocale
            audio, sr = await tts.synthesize_async(text)

            if audio is None:
                # Fallback sans audio — animation minimale
                tts.speak_fallback(text)
                await asyncio.sleep(len(text) * 0.07)  # approximation durée
            else:
                duration_sec = len(audio) / sr

                # Générer les frames lip-sync (phonèmes + RMS combinés)
                phoneme_frames = generate_lip_frames(text, duration_sec, fps=30)
                rms_frames     = generate_rms_frames(audio, sr, fps=30)
                lip_frames     = blend_frames(phoneme_frames, rms_frames, phoneme_weight=0.55)

                # Lancer audio + animation en parallèle
                await asyncio.gather(
                    tts.play_async(audio, sr),
                    play_lip_frames(lip_frames),
                )

            # Reset expression
            await send_reset()

            # Auto-hide après 2 secondes
            self._auto_hide_task = asyncio.create_task(self._delayed_hide(2.0, window))

        except Exception as e:
            logger.error("[POPUP] Erreur speak: %s", e)
        finally:
            self._speaking = False
            # Orb: revenir en idle
            try:
                from assistant.avatar_renderer import ws_titan_broadcast
                asyncio.create_task(ws_titan_broadcast({"type": "orb_state", "state": "idle"}))
            except Exception:
                pass

    async def _delayed_hide(self, delay: float, window) -> None:
        await asyncio.sleep(delay)
        window.hide()

    def show_window(self) -> None:
        from assistant.avatar_renderer import get_avatar_window
        get_avatar_window().show()

    def hide_window(self) -> None:
        from assistant.avatar_renderer import get_avatar_window
        get_avatar_window().hide()

    @property
    def is_speaking(self) -> bool:
        return self._speaking


# Singleton
_popup: Optional[PopupManager] = None


def get_popup_manager() -> PopupManager:
    global _popup
    if _popup is None:
        _popup = PopupManager()
    return _popup


async def titan_speak(text: str, expression: str = "neutral") -> None:
    """Raccourci global pour faire parler Titan."""
    await get_popup_manager().speak(text, expression=expression)
