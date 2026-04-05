"""vision/ollama_vision.py — Analyse de chart par IA locale Ollama.

[FIX] Corrections du bug vision v11 :
  1. keep_alive=3600s — modèle maintenu en RAM entre les appels
  2. Timeout par phase (connexion 5s / génération 60s) au lieu d'un timeout global
  3. Retry ×2 avec backoff exponentiel avant fallback texte-only
  4. Détection Ollama au démarrage — warning propre si absent
  5. VISION_TEXT_ONLY=0 par défaut (désactivation du workaround)
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import aiohttp
from utils.config import (
    OLLAMA_BASE_URL, OLLAMA_CHAT_URL, VISION_MODEL_PRIMARY, VISION_MODEL_FALLBACK,
    VISION_NUM_CTX, VISION_KEEP_ALIVE, VISION_TIMEOUT_CONNECT, VISION_TIMEOUT_GENERATE,
    VISION_CACHE_TTL, VISION_CACHE_SIZE, VISION_TEXT_ONLY,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Cache ──────────────────────────────────────────────────────────────────

class _VisionCache:
    def __init__(self, max_size: int, ttl: int):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._order = []
        self.max_size = max_size
        self.ttl      = ttl

    def _key(self, image_b64: str, sym: str, tf: str) -> str:
        raw = f"{image_b64[:2048]}|{sym}|{tf}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, image_b64: str, sym: str, tf: str) -> Optional[Dict[str, Any]]:
        k = self._key(image_b64, sym, tf)
        v = self._store.get(k)
        if v is None:
            return None
        if time.monotonic() - v["_ts"] > self.ttl:
            self._store.pop(k, None)
            return None
        return dict(v, _cache_hit=True)

    def set(self, image_b64: str, sym: str, tf: str, value: Dict[str, Any]) -> None:
        k = self._key(image_b64, sym, tf)
        self._store[k] = dict(value, _ts=time.monotonic())
        if k in self._order:
            self._order.remove(k)
        self._order.append(k)
        while len(self._order) > self.max_size:
            old = self._order.pop(0)
            self._store.pop(old, None)


_cache = _VisionCache(VISION_CACHE_SIZE, VISION_CACHE_TTL)

# ── Ollama disponible ? ────────────────────────────────────────────────────
_ollama_available: Optional[bool] = None


async def check_ollama_available(session: aiohttp.ClientSession) -> bool:
    """[FIX] Vérifie si Ollama est accessible au démarrage."""
    global _ollama_available
    try:
        async with session.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=aiohttp.ClientTimeout(total=VISION_TIMEOUT_CONNECT),
        ) as r:
            _ollama_available = r.status == 200
            if _ollama_available:
                logger.info("[VISION] Ollama disponible sur %s", OLLAMA_BASE_URL)
            else:
                logger.warning("[VISION] Ollama répond HTTP %s — vision désactivée", r.status)
    except Exception as e:
        _ollama_available = False
        logger.warning("[VISION] Ollama non accessible (%s) — vision désactivée", e)
    return _ollama_available or False


# ── Prompt SMC ─────────────────────────────────────────────────────────────
SMC_PROMPT = """Tu es un analyste SMC (Smart Money Concepts) expert.
Analyse ce chart crypto et réponds en JSON structuré :
{
  "trend": "haussier|baissier|neutre",
  "key_levels": ["niveau1", "niveau2"],
  "ob_fvg": "description des Order Blocks et FVG visibles",
  "sweep": "liquidity sweep détecté ? oui/non + description",
  "signal": "ACHAT|VENTE|NEUTRE",
  "confidence": 0.0-1.0,
  "reasoning": "explication courte"
}"""


def _strip_data_url(b64: str) -> str:
    """Supprime le préfixe data:image/...;base64, si présent."""
    if b64 and b64.startswith("data:"):
        return b64.split(",", 1)[-1]
    return b64


async def _call_ollama(
    session: aiohttp.ClientSession,
    model: str,
    image_b64: str,
    context_text: str,
) -> str:
    """[FIX] Appel Ollama avec timeout par phase (connexion + génération séparés)."""
    user_msg: Dict[str, Any] = {"role": "user", "content": context_text}
    if image_b64 and len(image_b64) > 100 and not VISION_TEXT_ONLY:
        user_msg["images"] = [image_b64]

    payload = {
        "model": model,
        "stream": False,
        "keep_alive": VISION_KEEP_ALIVE,
        "options": {"num_ctx": VISION_NUM_CTX},
        "messages": [
            {"role": "system", "content": SMC_PROMPT},
            user_msg,
        ],
    }

    # [FIX] Timeout par phase : connexion courte, génération plus longue
    timeout = aiohttp.ClientTimeout(
        connect=VISION_TIMEOUT_CONNECT,
        total=VISION_TIMEOUT_CONNECT + VISION_TIMEOUT_GENERATE,
    )

    async with session.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout) as r:
        if r.status >= 400:
            body = await r.text()
            raise RuntimeError(f"Ollama HTTP {r.status}: {body[:150]}")
        data = await r.json(content_type=None)

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"]))

    content = ((data.get("message") or {}).get("content")) or data.get("response") or ""
    if not content:
        raise RuntimeError(f"Ollama response vide (model={model})")
    return content


def _parse_response(content: str, sym: str, tf: str, model: str) -> Dict[str, Any]:
    """Parse la réponse Ollama, extrait le JSON, fallback sur texte brut."""
    result = {
        "trend": "neutre", "key_levels": [], "ob_fvg": "",
        "sweep": "non", "signal": "NEUTRE", "confidence": 0.5,
        "reasoning": content[:300], "_model": model, "_source": "ollama_local",
    }
    try:
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            result.update({k: v for k, v in parsed.items() if k in result})
    except Exception:
        pass
    return result


async def ollama_vision_analyze(
    session: aiohttp.ClientSession,
    image_b64: str,
    symbol: str,
    timeframe: str,
    price: float,
    side_hint: Optional[str] = None,
    algo_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[FIX] Analyse vision avec retry ×2 et fallback texte-only."""
    image_b64 = _strip_data_url(image_b64)

    # Cache hit
    cached = _cache.get(image_b64, symbol, timeframe)
    if cached:
        return cached

    # Ollama disponible ?
    if _ollama_available is False:
        return {
            "signal": "NEUTRE", "confidence": 0.0,
            "_source": "ollama_unavailable", "_error": "Ollama non accessible",
        }

    context = (
        f"Symbol: {symbol} | TF: {timeframe} | Prix: {price:.2f}"
        + (f" | Biais: {side_hint}" if side_hint else "")
        + (f" | Contexte: {algo_context}" if algo_context else "")
    )

    models = [VISION_MODEL_PRIMARY]
    if VISION_MODEL_FALLBACK and VISION_MODEL_FALLBACK != VISION_MODEL_PRIMARY:
        models.append(VISION_MODEL_FALLBACK)

    last_error = ""
    for model in models:
        for attempt in range(2):  # [FIX] retry ×2 par modèle
            try:
                content = await _call_ollama(session, model, image_b64, context)
                result  = _parse_response(content, symbol, timeframe, model)
                _cache.set(image_b64, symbol, timeframe, result)
                logger.info("[VISION] %s/%s analysé (model=%s attempt=%d)", symbol, timeframe, model, attempt + 1)
                return result
            except Exception as e:
                last_error = str(e)
                logger.warning("[VISION] %s attempt %d/%s: %s", model, attempt + 1, 2, e)
                if attempt == 0:
                    await asyncio.sleep(2 ** attempt)  # backoff exponentiel

    # Fallback texte-only (aucune image)
    logger.warning("[VISION] Fallback texte-only — %s", last_error)
    try:
        content = await _call_ollama(session, models[0], "", context)
        result  = _parse_response(content, symbol, timeframe, f"{models[0]}_text_only")
        result["_text_only"] = True
        return result
    except Exception as e:
        return {
            "signal": "NEUTRE", "confidence": 0.0,
            "_source": "ollama_failed", "_error": str(e)[:100],
        }
