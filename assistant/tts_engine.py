"""assistant/tts_engine.py — Synthèse vocale Piper TTS + lecture audio.

Piper TTS est ultra-léger (< 50ms pour une phrase), 100% local, qualité haute.

Installation :
  1. Télécharger piper depuis https://github.com/rhasspy/piper/releases
     → piper_windows_amd64.zip (Windows)
  2. Extraire dans assistant/piper/
  3. Télécharger le modèle voix :
     curl -L https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx -o assistant/voices/fr_FR-upmc-medium.onnx
     curl -L https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json -o assistant/voices/fr_FR-upmc-medium.onnx.json

Dépendances Python :
  pip install sounddevice numpy
"""
from __future__ import annotations
import asyncio
import io
import logging
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from assistant.config import (
    TITAN_VOICE_MODEL, TITAN_VOICE_DIR, TITAN_ASSISTANT_DIR,
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL, ELEVENLABS_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Chemin vers l'exécutable Piper
_PIPER_DIRS = [
    TITAN_ASSISTANT_DIR / "piper",
    TITAN_ASSISTANT_DIR / "piper" / "piper",
    Path("assistant/piper"),
]
_PIPER_EXE_NAMES = ["piper.exe", "piper"]


def _find_piper() -> Optional[Path]:
    """Cherche l'exécutable Piper dans les emplacements connus."""
    for d in _PIPER_DIRS:
        for name in _PIPER_EXE_NAMES:
            p = d / name
            if p.exists():
                return p
    # Chercher dans PATH
    import shutil
    found = shutil.which("piper")
    if found:
        return Path(found)
    return None


def _find_voice_model() -> Optional[Path]:
    """Cherche le fichier .onnx du modèle vocal."""
    # Nom exact
    direct = TITAN_VOICE_DIR / TITAN_VOICE_MODEL
    if direct.exists():
        return direct
    # Sans extension
    base = TITAN_VOICE_MODEL.replace(".onnx", "")
    for d in [TITAN_VOICE_DIR, TITAN_ASSISTANT_DIR / "voices"]:
        for f in d.glob("*.onnx") if d.exists() else []:
            if base.lower() in f.name.lower():
                return f
    return None


class PiperTTS:
    """Moteur TTS Piper avec lecture audio et extraction des durées phonétiques.

    Méthode principale : synthesize(text) → (audio_np, sample_rate, durations)
    """

    def __init__(self) -> None:
        self._piper_path  = _find_piper()
        self._voice_model = _find_voice_model()
        self._available   = False

        if self._piper_path is None:
            logger.warning(
                "[TTS] Piper non trouvé. Placer l'exécutable dans assistant/piper/piper.exe\n"
                "      Télécharger : https://github.com/rhasspy/piper/releases"
            )
        elif self._voice_model is None:
            logger.warning(
                "[TTS] Modèle vocal '%s' non trouvé dans %s\n"
                "      Télécharger : https://huggingface.co/rhasspy/piper-voices",
                TITAN_VOICE_MODEL, TITAN_VOICE_DIR,
            )
        else:
            self._available = True
            logger.info("[TTS] Piper prêt — modèle: %s", self._voice_model.name)

    # ── Synthèse ──────────────────────────────────────────────────────────────

    def synthesize(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Synthétise le texte en audio.

        Returns:
            (audio_float32, sample_rate) ou (None, 22050) si erreur.
        """
        if not self._available:
            logger.warning("[TTS] Piper non disponible — TTS désactivé")
            return None, 22050

        text = text.strip()
        if not text:
            return None, 22050

        try:
            cmd = [
                str(self._piper_path),
                "--model", str(self._voice_model),
                "--output_raw",           # PCM brut en stdout
                "--sentence_silence", "0.2",
            ]
            result = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("[TTS] Piper erreur: %s", result.stderr[:200].decode("utf-8", errors="ignore"))
                return None, 22050

            raw_pcm = result.stdout
            if not raw_pcm:
                return None, 22050

            # Piper output = PCM 16-bit little-endian 22050 Hz mono
            sample_rate = 22050
            audio_int16 = np.frombuffer(raw_pcm, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0
            return audio_float, sample_rate

        except subprocess.TimeoutExpired:
            logger.error("[TTS] Piper timeout")
            return None, 22050
        except Exception as e:
            logger.error("[TTS] Erreur synthèse: %s", e)
            return None, 22050

    async def synthesize_async(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Version asynchrone — essaie ElevenLabs si clé présente, sinon Piper."""
        if ELEVENLABS_API_KEY:
            result = await self._synthesize_elevenlabs(text)
            if result[0] is not None:
                return result
            logger.warning("[TTS] ElevenLabs échoué, fallback Piper")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.synthesize, text)

    async def _synthesize_elevenlabs(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Synthèse via ElevenLabs API. Retourne (None, 22050) si indisponible."""
        try:
            import aiohttp as _aiohttp
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text,
                "model_id": ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            timeout = _aiohttp.ClientTimeout(total=ELEVENLABS_TIMEOUT)
            async with _aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                    if resp.status != 200:
                        logger.warning("[TTS] ElevenLabs HTTP %d", resp.status)
                        return None, 22050
                    mp3_bytes = await resp.read()

            # Décoder MP3 → numpy float32
            try:
                import io
                from pydub import AudioSegment  # type: ignore
                seg = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
                seg = seg.set_frame_rate(22050).set_channels(1).set_sample_width(2)
                audio_int16 = np.frombuffer(seg.raw_data, dtype=np.int16)
                audio_float = audio_int16.astype(np.float32) / 32768.0
                logger.info("[TTS] ElevenLabs OK (%d samples)", len(audio_float))
                return audio_float, 22050
            except ImportError:
                # pydub non installé — sauvegarder MP3 et jouer avec sounddevice indirect
                logger.warning("[TTS] pydub non installé, ElevenLabs désactivé (pip install pydub)")
                return None, 22050

        except Exception as e:
            logger.warning("[TTS] ElevenLabs erreur: %s", e)
            return None, 22050

    # ── Lecture audio ─────────────────────────────────────────────────────────

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Joue l'audio en bloquant jusqu'à la fin de la lecture."""
        try:
            import sounddevice as sd
            sd.play(audio, samplerate=sample_rate, blocking=True)
        except ImportError:
            logger.error("[TTS] sounddevice non installé : pip install sounddevice")
        except Exception as e:
            logger.error("[TTS] Erreur lecture audio: %s", e)

    async def play_async(self, audio: np.ndarray, sample_rate: int) -> None:
        """Version asynchrone de play."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.play, audio, sample_rate)

    # ── Durée audio ───────────────────────────────────────────────────────────

    @staticmethod
    def duration_sec(audio: np.ndarray, sample_rate: int) -> float:
        """Retourne la durée audio en secondes."""
        return len(audio) / sample_rate if audio is not None else 0.0

    # ── État ──────────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._available

    def speak_fallback(self, text: str) -> None:
        """Fallback Windows SAPI si Piper non disponible."""
        try:
            import subprocess
            ps_cmd = f'Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak("{text}")'
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                **kwargs,
            )
        except Exception:
            logger.warning("[TTS] Aucun TTS disponible (Piper + SAPI échoués)")


# Singleton
_tts: Optional[PiperTTS] = None


def get_tts() -> PiperTTS:
    global _tts
    if _tts is None:
        _tts = PiperTTS()
    return _tts
