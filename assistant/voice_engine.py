"""assistant/voice_engine.py — Détection wake word + transcription STT.

Pipeline :
  1. Thread audio lit les trames 30ms en continu (jamais bloqué)
  2. Accumulation dans un buffer glissant de 2s
  3. Thread Whisper séparé transcrit par batch quand énergie détectée (stride 500ms)
  4. Si wake word → enregistre l'utterance complète puis transcrit la commande
  5. Callback asyncio déclenché avec le texte de la commande

Dépendances :
  pip install faster-whisper sounddevice webrtcvad numpy
"""
from __future__ import annotations
import asyncio
import concurrent.futures
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
                logger.info("[VOICE] VAD WebRTC initialisé (agressivité=%d)", TITAN_VAD_AGGR)
            except ImportError:
                self._vad = "amplitude"
                logger.warning("[VOICE] webrtcvad non dispo → VAD amplitude (fallback)")

    def _is_speech(self, frame: np.ndarray) -> bool:
        """Détecte la parole : WebRTC VAD ou amplitude RMS en fallback."""
        if self._vad == "amplitude":
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            return rms > 350.0
        try:
            return self._vad.is_speech(frame.tobytes(), TITAN_SAMPLE_RATE)
        except Exception:
            return True

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

        # Vérifier l'énergie minimale avant de transcrire
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        if rms < 0.005:
            return ""   # silence — pas besoin de transcrire

        segments, _ = self._whisper.transcribe(
            audio_np,
            language=language,
            beam_size=3,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = " ".join(s.text.strip() for s in segments).strip()

        # Filtrer les hallucinations connues de Whisper
        if self._is_hallucination(text):
            logger.debug("[VOICE] Hallucination filtrée: '%s'", text[:60])
            return ""
        return text

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        """Détecte les phrases générées par Whisper sur du silence/bruit ambiant."""
        if not text:
            return False
        low = text.lower().strip()
        # Phrases fantomes connues de Whisper (FR + EN)
        _HALLUCINATION_PATTERNS = [
            "sous-titres réalisés par",
            "sous-titres",
            "amara.org",
            "merci d'avoir regardé",
            "merci de votre attention",
            "thank you for watching",
            "please subscribe",
            "like and subscribe",
            "music",
            "\u266a",
            "...",
        ]
        for pat in _HALLUCINATION_PATTERNS:
            if pat in low:
                return True
        # Texte très court et répétitif ("oui oui oui", "merci merci")
        words = low.split()
        if len(words) <= 2:
            return True   # trop court pour être une commande
        if len(set(words)) == 1 and len(words) > 2:
            return True   # mot répété
        return False

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

                    is_speech = self._is_speech(frame_bytes)

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
        """Boucle d'écoute avec transcription Whisper non-bloquante.

        Le thread audio lit les trames 30ms sans jamais s'arrêter.
        Un executor séparé lance Whisper uniquement quand de la parole est
        détectée, avec un stride minimum de 500ms entre deux appels.
        """
        self._load_vad()
        self._load_whisper()

        import sounddevice as sd

        logger.info("[VOICE] Écoute active — wake words: %s", TITAN_WAKE_WORDS)

        _wake_window_frames = int(2.0 * 1000 / TITAN_FRAME_MS)   # 67 trames = 2s
        _stride_frames      = int(500 / TITAN_FRAME_MS)           # 17 trames = 500ms
        _min_rms            = 0.008                               # seuil parole float32 (rehaussé anti-hallucination)

        wake_buffer: list[np.ndarray] = []
        frames_since_last  = 0
        fut                = None
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="titan-whisper"
        )

        def _transcribe_bg(audio: np.ndarray) -> str:
            return self.transcribe(audio).lower()

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
                    frames_since_last += 1

                    if len(wake_buffer) > _wake_window_frames:
                        wake_buffer = wake_buffer[-_wake_window_frames:]

                    # Récupérer le résultat Whisper si prêt
                    if fut is not None and fut.done():
                        try:
                            text = fut.result()
                        except Exception:
                            text = ""
                        fut = None

                        if text:
                            logger.info("[VOICE] Transcription: '%s'", text.strip())

                        if any(w in text for w in TITAN_WAKE_WORDS):
                            logger.info("[VOICE] Wake word détecté! ('%s')", text.strip())
                            wake_buffer.clear()
                            frames_since_last = 0

                            utterance = self._record_until_silence()
                            if utterance is None or len(utterance) < TITAN_SAMPLE_RATE * 0.5:
                                continue

                            command = self.transcribe(utterance).strip()
                            if not command:
                                continue

                            for ww in TITAN_WAKE_WORDS:
                                command = command.lower().replace(ww, "").strip()
                            command = command.strip(" ,.!?")

                            if command:
                                logger.info("[VOICE] Commande: '%s'", command)
                                if self._loop and self._callback:
                                    asyncio.run_coroutine_threadsafe(
                                        self._callback(command), self._loop
                                    )

                    # Lancer Whisper si : pas de tâche en cours + stride ok + buffer plein + parole
                    if (fut is None
                            and frames_since_last >= _stride_frames
                            and len(wake_buffer) >= _wake_window_frames):

                        audio_np = np.concatenate(wake_buffer).astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(audio_np ** 2)))

                        if rms > _min_rms:
                            frames_since_last = 0
                            logger.info("[VOICE] Parole RMS=%.4f — Whisper lancé", rms)
                            fut = executor.submit(_transcribe_bg, audio_np.copy())

        except Exception as e:
            logger.error("[VOICE] Erreur boucle écoute: %s", e)
        finally:
            executor.shutdown(wait=False)

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
