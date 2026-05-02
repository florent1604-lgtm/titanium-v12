"""assistant/plugins/diagnostic_plugin.py — Auto-diagnostic des erreurs système."""
from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional

import aiohttp

from assistant.config import TITAN_LLM_URL, TITAN_LLM_MODEL, TITAN_LLM_TIMEOUT
from assistant.plugins.base import TitanPlugin

logger = logging.getLogger(__name__)

_LOG_FILE = Path("titan_stdout.log")
_LOG_LINES = 100

_KNOWN_PATTERNS: list[tuple[str, str]] = [
    (r"ollama.*timeout|timeout.*ollama",
     "Ollama est lent. Le modèle prend du temps à se charger. Normal au premier appel."),
    (r"\[WS\].*reconnect|\[WS\].*disconnect",
     "Le WebSocket Binance s'est reconnecté. Connexion instable mais non critique."),
    (r"\[VOICE\].*error|\[VOICE\].*erreur",
     "Le moteur vocal a rencontré des erreurs. Vérifiez que le micro est branché."),
    (r"\[TTS\].*error|\[TTS\].*erreur",
     "Piper TTS a rencontré des erreurs. Vérifiez l'exécutable dans assistant/piper/."),
    (r"cuda.*error|gpu.*error",
     "Erreur GPU détectée. Le bot utilise le CPU en fallback."),
]

_ERROR_PATTERNS = re.compile(
    r"\b(ERROR|WARNING|error|timeout|failed|disconnect|Exception|Traceback)\b",
    re.IGNORECASE,
)

_MODULE_MAP = {
    "[VOICE]": "STT/Voice",
    "[TTS]":   "TTS",
    "[WS]":    "WebSocket",
    "[SCAN]":  "Scanner",
    "ollama":  "Ollama/LLM",
    "vision":  "Vision",
}


def _read_log(n: int = _LOG_LINES) -> list[str]:
    """Lit les n dernières lignes du log."""
    candidates = [_LOG_FILE, Path("logs/titan_stdout.log"), Path("titan.log")]
    for p in candidates:
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                return lines[-n:]
            except Exception:
                pass
    return []


def _analyze_log(lines: list[str]) -> dict[str, list[str]]:
    """Groupe les erreurs par module."""
    grouped: dict[str, list[str]] = {}
    for line in lines:
        if not _ERROR_PATTERNS.search(line):
            continue
        module = "Général"
        for key, label in _MODULE_MAP.items():
            if key.lower() in line.lower():
                module = label
                break
        grouped.setdefault(module, []).append(line.strip()[:200])
    return grouped


def _check_known_patterns(lines: list[str]) -> list[str]:
    """Retourne les réponses prédéfinies pour les patterns connus."""
    full = "\n".join(lines).lower()
    matched = []
    for pattern, response in _KNOWN_PATTERNS:
        if re.search(pattern, full, re.IGNORECASE):
            matched.append(response)
    return matched


async def _llm_diagnose(grouped: dict[str, list[str]]) -> Optional[str]:
    """Envoie les erreurs groupées au LLM pour analyse."""
    if not grouped:
        return None

    errors_text = ""
    for module, lines in grouped.items():
        errors_text += f"\n[{module}]\n" + "\n".join(f"  {l}" for l in lines[:5])

    prompt = (
        "Voici les erreurs récentes du bot de trading Titanium:\n"
        f"{errors_text}\n\n"
        "Diagnostique en 2 phrases max. Mentionne le module concerné et si c'est critique ou non. "
        "Style direct, pas de politesse."
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{TITAN_LLM_URL}/api/generate",
                json={
                    "model": TITAN_LLM_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 150, "temperature": 0.3},
                },
                timeout=aiohttp.ClientTimeout(total=TITAN_LLM_TIMEOUT),
            ) as resp:
                data = await resp.json()
                return data.get("response", "").strip() or None
    except Exception as e:
        logger.warning("[DIAG] Erreur LLM: %s", e)
        return None


class DiagnosticPlugin(TitanPlugin):
    """Analyse les logs et retourne un diagnostic vocal."""

    name = "diagnostic"
    intents = ["diagnostic", "fix", "repare", "erreur", "statut"]
    min_confidence = 0.50

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        lines = _read_log()

        if not lines:
            return "Aucun fichier de log trouvé. Lance le bot pour générer des logs."

        # Patterns connus — réponse rapide
        known = _check_known_patterns(lines)
        if known:
            return " ".join(known)

        # Analyse LLM
        grouped = _analyze_log(lines)
        if not grouped:
            return "Logs analysés — aucune erreur critique détectée. Tout semble fonctionner."

        modules = ", ".join(grouped.keys())
        count = sum(len(v) for v in grouped.values())
        diagnosis = await _llm_diagnose(grouped)
        if diagnosis:
            return diagnosis
        return f"{count} erreurs détectées dans : {modules}. Vérifiez les logs pour les détails."
