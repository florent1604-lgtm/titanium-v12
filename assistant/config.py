"""assistant/config.py — Configuration de l'assistant Titan.

Variables .env supportées :
  TITAN_ENABLED          1 pour activer (défaut : 0)
  TITAN_WAKE_WORDS       Mots-clés séparés par virgule (défaut : titan,hey titan)
  TITAN_STT_MODEL        Modèle Whisper (tiny|small|base, défaut : small)
  TITAN_STT_DEVICE       cpu ou cuda (défaut : cpu)
  TITAN_LLM_MODEL        Modèle Ollama (défaut : phi3:mini)
  TITAN_LLM_URL          URL Ollama (défaut : http://localhost:11434)
  TITAN_VOICE_MODEL      Fichier .onnx Piper (défaut : fr_FR-upmc-medium.onnx)
  TITAN_VOICE_DIR        Dossier des modèles Piper (défaut : assistant/voices)
  TITAN_AVATAR_FILE      Nom du fichier VRM (défaut : VRoid_V110_Male_v1.1.3.vrm)
  TITAN_REPORT_HOUR      Heure rapport quotidien (défaut : 20)
  TITAN_REPORT_MIN       Minute rapport quotidien (défaut : 0)
  TITAN_WINDOW_WIDTH     Largeur fenêtre popup (défaut : 420)
  TITAN_WINDOW_HEIGHT    Hauteur fenêtre popup (défaut : 620)
  TITAN_API_BASE         URL de l'API Titanium (défaut : http://localhost:8080)
  TITAN_SILENCE_SEC      Silence avant fin d'enregistrement (défaut : 1.5)
  TITAN_MAX_RECORD_SEC   Durée max d'une utterance (défaut : 15)
  TITAN_VAD_AGGR         Agressivité VAD 0-3 (défaut : 2)
  TITAN_SCORE_CONTEXT    Inclure score/positions dans contexte LLM (défaut : 1)
"""
from __future__ import annotations
import os
from pathlib import Path

# Chemin de base du projet
_BASE = Path(__file__).resolve().parent.parent


def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _bool(key: str, default: str) -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


# ── Activation ────────────────────────────────────────────────────────────────
TITAN_ENABLED        = _bool("TITAN_ENABLED", "0")

# ── Wake word ─────────────────────────────────────────────────────────────────
TITAN_WAKE_WORDS     = [w.strip().lower() for w in _str("TITAN_WAKE_WORDS", "titan,hey titan").split(",")]

# ── STT ───────────────────────────────────────────────────────────────────────
TITAN_STT_MODEL      = _str("TITAN_STT_MODEL", "small")
TITAN_STT_DEVICE     = _str("TITAN_STT_DEVICE", "cpu")
TITAN_STT_COMPUTE    = _str("TITAN_STT_COMPUTE", "int8")   # int8 = ultra-léger CPU

# ── LLM ───────────────────────────────────────────────────────────────────────
TITAN_LLM_MODEL      = _str("TITAN_LLM_MODEL", "phi3:mini")
TITAN_LLM_URL        = _str("TITAN_LLM_URL", "http://localhost:11434")
TITAN_LLM_TIMEOUT    = _int("TITAN_LLM_TIMEOUT", 60)   # 60s : phi3:mini peut être lent au premier appel
TITAN_LLM_MAX_TOKENS = _int("TITAN_LLM_MAX_TOKENS", 300)   # réponses courtes = plus rapide

# ── TTS ───────────────────────────────────────────────────────────────────────
TITAN_VOICE_MODEL    = _str("TITAN_VOICE_MODEL", "fr_FR-upmc-medium.onnx")
TITAN_VOICE_DIR      = _BASE / _str("TITAN_VOICE_DIR", "assistant/voices")

# ── Avatar VRM ────────────────────────────────────────────────────────────────
TITAN_AVATAR_FILE    = _str("TITAN_AVATAR_FILE", "VRoid_V110_Male_v1.1.3.vrm")
TITAN_AVATAR_PATH    = _BASE / "assistant" / TITAN_AVATAR_FILE
TITAN_WINDOW_WIDTH   = _int("TITAN_WINDOW_WIDTH", 420)
TITAN_WINDOW_HEIGHT  = _int("TITAN_WINDOW_HEIGHT", 620)

# ── Rapport quotidien ─────────────────────────────────────────────────────────
TITAN_REPORT_HOUR    = _int("TITAN_REPORT_HOUR", 20)
TITAN_REPORT_MIN     = _int("TITAN_REPORT_MIN", 0)
TITAN_REPORT_ENABLED = _bool("TITAN_REPORT_ENABLED", "1")

# ── API interne ───────────────────────────────────────────────────────────────
TITAN_API_BASE       = _str("TITAN_API_BASE", "http://localhost:8080")

# ── Audio ─────────────────────────────────────────────────────────────────────
TITAN_SAMPLE_RATE    = 16000
TITAN_FRAME_MS       = 30           # durée d'une trame VAD (ms)
TITAN_SILENCE_SEC    = _float("TITAN_SILENCE_SEC", 1.5)
TITAN_MAX_RECORD_SEC = _float("TITAN_MAX_RECORD_SEC", 15.0)
TITAN_VAD_AGGR       = _int("TITAN_VAD_AGGR", 2)    # 0=permissif, 3=strict

# ── Contexte LLM ─────────────────────────────────────────────────────────────
TITAN_SCORE_CONTEXT  = _bool("TITAN_SCORE_CONTEXT", "1")

# ── Chemins utiles ────────────────────────────────────────────────────────────
TITAN_WEB_DIR        = _BASE / "assistant" / "web"
TITAN_ASSISTANT_DIR  = _BASE / "assistant"

# Système de prompt de Titan
TITAN_SYSTEM_PROMPT = """Tu es Titan, l'assistant IA intégré au bot de trading algorithmique Titanium.
Tu es un expert en trading Smart Money Concepts (SMC), analyse technique et gestion du risque.
Tu parles toujours en français, de façon concise, professionnelle et directe.
Tu as accès en temps réel aux données du bot : positions paper, PnL, signaux, scores, risque macro.

Directives :
- Réponds en 1-3 phrases maximum sauf si on te demande un rapport détaillé.
- Utilise des chiffres précis quand tu parles de PnL, score ou risque.
- Si tu ne sais pas quelque chose, dis-le honnêtement.
- Tu peux proactivement signaler des anomalies ou opportunités importantes.
- Évite les formules de politesse inutiles (pas de "bien sûr !", "absolument !")."""
