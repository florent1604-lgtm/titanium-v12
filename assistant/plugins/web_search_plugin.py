"""assistant/plugins/web_search_plugin.py — Recherche web via browser_agent."""
from __future__ import annotations
import logging
import re
from typing import Dict, Any, Optional

import aiohttp

from assistant.config import TITAN_LLM_URL, TITAN_LLM_MODEL, TITAN_LLM_TIMEOUT, TITAN_LLM_MAX_TOKENS
from assistant.plugins.base import TitanPlugin
from assistant.browser_agent import search, navigate, SITE_CATEGORIES

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+|www\.\S+\.\S+")

_TRIGGER_WORDS = [
    "news", "actualit", "cherch", "recherch", "browse",
    "va sur", "ouvre", "infos", "dernier", "quoi de neuf",
    "events", "quoi se passe", "article",
]


def _extract_query(text: str) -> str:
    """Supprime les mots-déclencheurs et retourne la requête brute."""
    t = text.lower().strip()
    for w in ["titan", "hey titan", "jarvis", "hey jarvis"]:
        t = t.replace(w, "").strip()
    for w in ["cherche", "recherche", "news", "actualités", "actualite",
              "dis-moi", "montre-moi", "infos sur", "infos", "va sur",
              "ouvre", "quoi de neuf sur", "events", "quoi se passe"]:
        t = t.replace(w, "").strip()
    return t.strip(" ,.!?") or text.strip()


async def _summarize(results: list[dict], query: str) -> Optional[str]:
    """Résume les résultats via Ollama."""
    if not results:
        return "Aucun résultat trouvé pour cette recherche."

    snippets = "\n".join(
        f"- {r['title']}: {r['snippet'][:200]}"
        for r in results
        if r.get("snippet") or r.get("title")
    )
    prompt = (
        f"Voici les résultats de recherche pour '{query}':\n{snippets}\n\n"
        "Résume en 2 phrases max, style direct, chiffres si disponibles. "
        "Pas de politesse inutile."
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{TITAN_LLM_URL}/api/generate",
                json={
                    "model": TITAN_LLM_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 150, "temperature": 0.5},
                },
                timeout=aiohttp.ClientTimeout(total=TITAN_LLM_TIMEOUT),
            ) as resp:
                data = await resp.json()
                return data.get("response", "").strip() or None
    except Exception as e:
        logger.warning("[WEB_SEARCH] Erreur LLM: %s", e)
        # Fallback: retourner premier snippet
        first = next((r for r in results if r.get("snippet")), None)
        return f"{first['title']}: {first['snippet'][:200]}" if first else None


class WebSearchPlugin(TitanPlugin):
    """Recherche web via DuckDuckGo + résumé LLM."""

    name = "web_search"
    intents = ["search", "news", "actualite", "browse", "cherche", "recherche"]
    min_confidence = 0.55

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        t = text.lower()

        # Navigation directe si URL détectée
        url_match = _URL_RE.search(t)
        if url_match or intent == "browse":
            url = url_match.group(0) if url_match else _extract_query(text)
            if not url.startswith("http"):
                url = "https://" + url
            logger.info("[WEB_SEARCH] Navigation vers %s", url)
            page = await navigate(url)
            if page.get("content"):
                preview = page["content"][:300]
                return f"Sur {page.get('title', url)}: {preview}"
            return f"Impossible d'accéder à {url}."

        query = _extract_query(text)
        if not query:
            return None

        # Choisir les sites selon le type de requête
        sites = None
        t_lower = t
        if any(w in t_lower for w in ["crypto", "bitcoin", "btc", "eth", "coin"]):
            sites = SITE_CATEGORIES["crypto_news"]
        elif any(w in t_lower for w in ["macro", "fed", "inflation", "bce", "dollar"]):
            sites = SITE_CATEGORIES["macro"]

        results = await search(query, sites=sites, max_results=3)
        summary = await _summarize(results, query)
        return summary
