"""assistant/voice_engine.py — Détection wake word + transcription STT.

Pipeline :
  1. Écoute continue en arrière-plan (sounddevice)
  2. WebRTC VAD frame par frame (30ms)
  3. Buffer vocal → tiny Whisper → cherche le wake word
  4. Si wake word : enregistre l'utterance complète (silence = fin)
  5. Transcrit avec Whisper small pour la précision

Dépendances :
  pip install faster-whisper sounddevice webrtcvad numpy
"""
from __future__ import annotations
import asyncio
import logging
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np

from assistant.config import (
    TITAN_SAMPLE_RATE, TITAN_FRAME_MS, TITAN_STT_MODEL, TITAN_STT_DEVICE,
    TITAN_STT_COMPUTE, TITAN_WAKE_WORDS, TITAN_SILENCE_SEC, TITAN_MAX_RECORD_SEC,
    TITAN_VAD_AGGR,
)

logger = logging.getLogger(__name__)

_FRAME_SIZE = TITAN_SAMPLE_RATE * TITAN_FRAME_MS // 1000   # 480 samples @ 16kHz


class VoiceEngine:
    """Moteur STT avec détection de wake word basée sur VAD + Whisper.

    Usage:
        engine = VoiceEngine()
        engine.start(on_command=callback)   # démarre l'écoute en arrière-plan
        engine.stop()
    """

    def __init__(self) -> None:
        self._vad         = None       # webrtcvad.Vad (chargé à la demande)
        self._whisper     = None       # faster_whisper.WhisperModel (chargé à la demande)
        self._audio_q: queue.Queue     = queue.Queue()
        self._running     = False
        self._stream      = None       # sounddevice.InputStream
        self._listen_thr  = None       # thread d'écoute
        self._callback: Optional[Callable[[str], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Chargement lazy (évite le coût au démarrage) ──────────────────────────

    def _load_vad(self):
        if self._vad is None:
            try:
                import webrtcvad
                self._vad = webrtcvad.Vad(TITAN_VAD_AGGR)
                logger.info("[VOICE] VAD initialisé (agressivité=%d)", TITAN_VAD_AGGR)
            except ImportError:
                logger.error("[VOICE] webrtcvad non installé : pip install webrtcvad")
                raise

    def _load_whisper(self):
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
                logger.info("[VOICE] Chargement Whisper %s (%s)…", TITAN_STT_MODEL, TITAN_STT_COMPUTE)
                self._whisper = WhisperModel(
                    TITAN_STT_MODEL,
                    device=TITAN_STT_DEVICE,
                    compute_type=TITAN_STT_COMPUTE,
                )
                logger.info("[VOICE] Whisper prêt")
            except ImportError:
                logger.error("[VOICE] faster-whisper non installé : pip install faster-whisper")
                raise

    # ── Transcription ─────────────────────────────────────────────────────────

    def transcribe(self, audio_np: np.ndarray, language: str = "fr") -> str:
        """Transcrit un tableau numpy float32 (16kHz mono) en texte."""
        self._load_whisper()
        segments, _ = self._whisper.transcribe(
            audio_np,
            language=language,
            beam_size=3,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(s.text.strip() for s in segments).strip()

    # ── Enregistrement VAD ────────────────────────────────────────────────────

    def _record_until_silence(self) -> Optional[np.ndarray]:
        """Enregistre jusqu'à TITAN_SILENCE_SEC de silence ou TITAN_MAX_RECORD_SEC.

        Retourne un tableau numpy float32 ou None si rien enregistré.
        Bloquant — appeler depuis un thread séparé.
        """
        self._load_vad()
        import sounddevice as sd

        frames_silence   = int(TITAN_SILENCE_SEC * 1000 / TITAN_FRAME_MS)
        frames_max       = int(TITAN_MAX_RECORD_SEC * 1000 / TITAN_FRAME_MS)
        silence_counter  = 0
        audio_frames     = []
        total_frames     = 0

        logger.debug("[VOICE] Enregistrement en cours…")

        try:
            with sd.InputStream(
                samplerate=TITAN_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=_FRAME_SIZE,
            ) as stream:
                while total_frames < frames_max:
                    frame_bytes, _ = stream.read(_FRAME_SIZE)
                    pcm_bytes      = frame_bytes.tobytes()

                    is_speech = False
                    try:
                        is_speech = self._vad.is_speech(pcm_bytes, TITAN_SAMPLE_RATE)
                    except Exception:
                        is_speech = True   # en cas d'erreur VAD, supposer parole

                    audio_frames.append(frame_bytes.copy())
                    total_frames += 1

                    if is_speech:
                        silence_counter = 0
                    else:
                        silence_counter += 1
                        if silence_counter >= frames_silence and len(audio_frames) > frames_silence:
                            break

        except Exception as e:
            logger.warning("[VOICE] Erreur enregistrement: %s", e)
            return None

        if len(audio_frames) <= frames_silence:
            return None   # trop court

        audio_np = np.concatenate([f.flatten() for f in audio_frames]).astype(np.float32)
        audio_np /= 32768.0   # normaliser int16 → float32
        return audio_np

    # ── Détection wake word en boucle ─────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Boucle d'écoute continue dans un thread dédié."""
        self._load_vad()
        self._load_whisper()

        import sounddevice as sd

        logger.info("[VOICE] Écoute active — wake words: %s", TITAN_WAKE_WORDS)

        # Fenêtre glissante de 2 secondes pour la détection du wake word
        _wake_window_frames = int(2.0 * 1000 / TITAN_FRAME_MS)
        wake_buffer: list[np.ndarray] = []

        try:
            with sd.InputStream(
                samplerate=TITAN_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=_FRAME_SIZE,
            ) as stream:
                while self._running:
                    frame_bytes, _ = stream.read(_FRAME_SIZE)
                    wake_buffer.append(frame_bytes.flatten())

                    if len(wake_buffer) < _wake_window_frames:
                        continue

                    # Garder seulement la fenêtre
                    if len(wake_buffer) > _wake_window_frames:
                        wake_buffer = wake_buffer[-_wake_window_frames:]

                    # Transcription rapide pour le wake word
                    audio_np = np.concatenate(wake_buffer).astype(np.float32) / 32768.0
                    text = self.transcribe(audio_np).lower()

                    if any(w in text for w in TITAN_WAKE_WORDS):
                        logger.info("[VOICE] Wake word détecté! ('%s')", text.strip())
                        wake_buffer.clear()

                        # Enregistrer la commande complète
                        utterance = self._record_until_silence()
                        if utterance is None or len(utterance) < TITAN_SAMPLE_RATE * 0.5:
                            continue

                        command = self.transcribe(utterance).strip()
                        if not command:
                            continue

                        # Retirer le wake word du texte de la commande
                        for ww in TITAN_WAKE_WORDS:
                            command = command.lower().replace(ww, "").strip()
                        command = command.strip(" ,.!?")

                        if command:
                            logger.info("[VOICE] Commande: '%s'", command)
                            if self._loop and self._callback:
                                asyncio.run_coroutine_threadsafe(
                                    self._callback(command), self._loop
                                )

        except Exception as e:
            logger.error("[VOICE] Erreur boucle écoute: %s", e)

    # ── API publique ──────────────────────────────────────────────────────────

    def start(
        self,
        on_command: Callable[[str], None],
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Démarre l'écoute en arrière-plan.

        Args:
            on_command: Coroutine appelée avec le texte transcrit.
            loop: Event loop asyncio pour envoyer la coroutine (get_event_loop si None).
        """
        if self._running:
            return
        self._running  = True
        self._callback = on_command
        self._loop     = loop or asyncio.get_event_loop()

        self._listen_thr = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="titan-voice",
        )
        self._listen_thr.start()
        logger.info("[VOICE] Thread d'écoute démarré")

    def stop(self) -> None:
        """Arrête l'écoute."""
        self._running = False
        if self._listen_thr:
            self._listen_thr.join(timeout=2)
        logger.info("[VOICE] Écoute arrêtée")

    def is_running(self) -> bool:
        return self._running


# Singleton partagé
_engine: Optional[VoiceEngine] = None


def get_voice_engine() -> VoiceEngine:
    global _engine
    if _engine is None:
        _engine = VoiceEngine()
    return _engine
