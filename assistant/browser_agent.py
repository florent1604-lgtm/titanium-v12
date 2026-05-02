"""assistant/browser_agent.py — Recherche web autonome pour Titan.

Utilise ddgs (DuckDuckGo Search) pour les recherches, Playwright pour la navigation.
Désactivé si BROWSER_ENABLED=0. Cache in-memory TTL=BROWSER_CACHE_TTL.
Max 2 pages Playwright simultanées.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

from assistant.config import (
    BROWSER_ENABLED, BROWSER_HEADLESS, BROWSER_TIMEOUT_SEC, BROWSER_CACHE_TTL,
)

logger = logging.getLogger(__name__)

SITE_CATEGORIES: dict[str, list[str]] = {
    "crypto_news": ["coindesk.com", "cointelegraph.com", "cryptonews.com"],
    "macro":       ["reuters.com", "investing.com"],
    "trading":     ["tradingview.com"],
}

# Cache: {cache_key: (timestamp, results)}
_cache: dict[tuple, tuple[float, list[dict]]] = {}
_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(2)
    return _semaphore


def _cache_key(query: str, sites: Optional[list[str]]) -> tuple:
    return (query.lower().strip(), tuple(sorted(sites)) if sites else ())


def _cache_get(key: tuple) -> Optional[list[dict]]:
    if key in _cache:
        ts, results = _cache[key]
        if time.time() - ts < BROWSER_CACHE_TTL:
            return results
        del _cache[key]
    return None


def _cache_set(key: tuple, results: list[dict]) -> None:
    _cache[key] = (time.time(), results)


def _ddg_search_sync(query: str, sites: Optional[list[str]], max_results: int) -> list[dict]:
    """Recherche synchrone via ddgs — à appeler dans executor."""
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("[BROWSER] ddgs non installé: pip install ddgs")
        return []

    full_query = query
    if sites:
        site_filter = " OR ".join(f"site:{s}" for s in sites)
        full_query = f"{query} {site_filter}"

    try:
        with DDGS() as ddg:
            raw = list(ddg.text(full_query, max_results=max_results))
        results = []
        for r in raw:
            results.append({
                "title":   r.get("title", ""),
                "url":     r.get("href", ""),
                "snippet": r.get("body", ""),
                "content": "",
            })
        return results
    except Exception as e:
        logger.warning("[BROWSER] Erreur DDG: %s", e)
        return []


async def search(
    query: str,
    sites: Optional[list[str]] = None,
    max_results: int = 3,
) -> list[dict]:
    """Recherche web. Retourne [] si désactivé ou en cas d'erreur."""
    if not BROWSER_ENABLED:
        return []

    key = _cache_key(query, sites)
    cached = _cache_get(key)
    if cached is not None:
        logger.debug("[BROWSER] Cache hit: %s", query)
        return cached

    logger.info("[BROWSER] Recherche: %s%s", query, f" sites={sites}" if sites else "")
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _ddg_search_sync, query, sites, max_results)
    _cache_set(key, results)
    return results


async def navigate(url: str) -> dict:
    """Navigue vers une URL et retourne titre + contenu texte."""
    if not BROWSER_ENABLED:
        return {"title": "", "content": "", "links": []}

    try:
        from playwright.async_api import async_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        return {"title": "", "content": "", "links": []}

    async with _get_semaphore():
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=BROWSER_HEADLESS)
                ctx = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await ctx.new_page()
                await page.goto(url, timeout=BROWSER_TIMEOUT_SEC * 1000, wait_until="domcontentloaded")
                html = await page.content()
                await browser.close()

            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title else ""
            content = " ".join(soup.get_text(separator=" ").split())[:2000]
            links = [a.get("href", "") for a in soup.find_all("a", href=True)][:10]
            return {"title": title, "content": content, "links": links}
        except Exception as e:
            logger.warning("[BROWSER] Erreur navigate %s: %s", url, e)
            return {"title": "", "content": "", "links": []}


async def research_context(symbol: str, side: str) -> str:
    """Retourne un résumé LLM-ready pour enrichir un signal de trading.

    Utilisé en fire-and-forget depuis signal_engine.
    """
    if not BROWSER_ENABLED:
        return ""

    query = f"{symbol} price {side} reason news today"
    results = await search(query, sites=SITE_CATEGORIES["crypto_news"], max_results=3)

    if not results:
        return ""

    lines = []
    for r in results:
        snippet = r.get("snippet", "")
        title = r.get("title", "")
        if snippet or title:
            lines.append(f"- {title}: {snippet[:150]}" if snippet else f"- {title}")

    return "\n".join(lines) if lines else ""
