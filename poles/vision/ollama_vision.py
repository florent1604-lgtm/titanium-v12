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
SMC_PROMPT = """Tu es un analyste expert en Smart Money Concepts (SMC) pour les cryptomonnaies.
Tu reçois des données temps réel issues d'un scanner algorithmique. Analyse-les et réponds UNIQUEMENT avec un objet JSON valide — aucun texte avant ni après, aucun bloc markdown.

Utilise les prix et niveaux fournis dans le contexte pour remplir chaque champ avec des valeurs RÉELLES et précises.

Format JSON attendu (sans commentaires, valeurs réelles obligatoires) :
{
  "trend": "haussier ou baissier ou neutre",
  "structure": "BOS haussier ou BOS baissier ou CHoCH haussier ou CHoCH baissier ou neutre",
  "key_levels": ["prix_support_reel", "prix_resistance_reel", "prix_ema_reel"],
  "ob_fvg": "description des OB et FVG basée sur les données reçues",
  "sweep": "oui ou non",
  "sweep_detail": "description du sweep si détecté, chaîne vide sinon",
  "inducement": "oui ou non",
  "entry_zone": "zone entrée avec prix approximatif ex: retour OB à 76200",
  "sl_zone": "zone SL avec prix ex: sous swing low à 75800",
  "tp_zones": ["TP1: prix cible 1", "TP2: prix cible 2", "TP3: prix cible 3"],
  "signal": "ACHAT ou VENTE ou NEUTRE",
  "confidence": 0.0,
  "reasoning": "analyse en 2-3 phrases avec les données réelles du contexte"
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
    """Parse la réponse Ollama avec plusieurs stratégies de fallback."""
    result = {
        "trend": "neutre", "structure": "neutre", "key_levels": [],
        "ob_fvg": "", "sweep": "non", "sweep_detail": "",
        "inducement": "non", "entry_zone": "", "sl_zone": "",
        "tp_zones": [], "signal": "NEUTRE", "confidence": 0.5,
        "reasoning": content[:500], "_model": model, "_source": "ollama_local",
    }
    # Nettoyage : underscores échappés, blocs markdown
    cleaned = content.replace("\\_", "_")
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned).replace("```", "")
    # Stratégie 1 : JSON complet
    try:
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            parsed = json.loads(json_match.group())
            result.update({k: v for k, v in parsed.items() if k in result})
            return result
    except Exception:
        pass
    # Stratégie 2 : extraction champ par champ
    for field, pattern in [
        ("signal",     r'"signal"\s*:\s*"(ACHAT|VENTE|NEUTRE)"'),
        ("trend",      r'"trend"\s*:\s*"([^"]+)"'),
        ("structure",  r'"structure"\s*:\s*"([^"]+)"'),
        ("confidence", r'"confidence"\s*:\s*([0-9.]+)'),
        ("ob_fvg",     r'"ob_fvg"\s*:\s*"([^"]+)"'),
        ("sweep",      r'"sweep"\s*:\s*"([^"]+)"'),
        ("entry_zone", r'"entry_zone"\s*:\s*"([^"]+)"'),
        ("sl_zone",    r'"sl_zone"\s*:\s*"([^"]+)"'),
        ("reasoning",  r'"reasoning"\s*:\s*"([^"]+)"'),
    ]:
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            val = m.group(1)
            result[field] = float(val) if field == "confidence" else val
    # Extraction key_levels et tp_zones (tableaux)
    for field, pattern in [
        ("key_levels", r'"key_levels"\s*:\s*\[([^\]]*)\]'),
        ("tp_zones",   r'"tp_zones"\s*:\s*\[([^\]]*)\]'),
    ]:
        m = re.search(pattern, cleaned)
        if m:
            items = re.findall(r'"([^"]+)"', m.group(1))
            result[field] = items
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

    ctx = algo_context or {}
    lines = [
        f"Symbol: {symbol} | Timeframe: {timeframe} | Prix actuel: {price:.2f} USDT",
        f"Biais suggéré: {side_hint or 'AUTO'}",
    ]
    if ctx:
        score = ctx.get("score", "?")
        side  = ctx.get("side", "?")
        lines.append(f"\n--- DONNÉES ALGORITHMIQUES TEMPS RÉEL (score {score}/11, signal {side}) ---")
        ema4h = ctx.get("ema200_h4")
        if ema4h:
            bias4h = "HAUSSIÈRE" if ctx.get("EMA200_H4") else "BAISSIÈRE"
            lines.append(f"EMA200 4H: {ema4h:.2f} → tendance {bias4h}")
        ema1d = ctx.get("ema200_1d")
        if ema1d:
            bias1d = "haussier" if ctx.get("EMA200_1D") else "baissier"
            lines.append(f"EMA200 1D: {ema1d:.2f} → biais daily {bias1d}")
        ob_q = ctx.get("ob_quality", 0)
        lines.append(f"OB/FVG 30m: {'✓ détecté' if ctx.get('OB_FVG_30M') else '✗'} (qualité {ob_q:.0%}) | conf 15m: {'✓' if ctx.get('OB_FVG_15M_CONFIRM') else '✗'}")
        lines.append(f"Structure BOS H2/H1: {'✓ confirmé' if ctx.get('STRUCT_H2H1') else '✗'} | Alignement: {'✓' if ctx.get('ALIGN_H2H1') else '✗'}")
        lines.append(f"Liquidity Sweep: {'✓ DÉTECTÉ' if ctx.get('LIQ_SWEEP') else '✗ aucun'}")
        d_pct = ctx.get("delta_pct", 0)
        lines.append(f"Delta Volume: {'✓' if ctx.get('DELTA_VOL') else '✗'} ({d_pct:+.1%}) | TRIX 5m: {'✓' if ctx.get('TRIX_5M') else '✗'}")
        rsi = ctx.get("rsi")
        if rsi:
            lines.append(f"RSI: {rsi:.1f} | Divergence: {ctx.get('rsi_divergence', 'none')}")
        adx = ctx.get("adx")
        if adx:
            lines.append(f"ADX: {adx:.1f} | Régime: {ctx.get('regime', '?')}")
        confs = ctx.get("confs", [])
        if confs:
            lines.append(f"Critères validés: {' | '.join(confs)}")
    context = "\n".join(lines)

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
