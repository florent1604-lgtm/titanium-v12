"""fundamentals/news_fetcher.py — Agrégateur d'actualités multi-sources.

Sources :
  1. NewsAPI.org  — nécessite NEWSAPI_KEY dans .env (plan gratuit : 100 req/j)
  2. GDELT v2     — gratuit, pas de clé, actualités mondiales en temps réel
  3. RSS feeds    — Reuters, BBC, CoinDesk (pas de clé)

Retourne une liste normalisée de dicts :
  {"title": str, "description": str, "url": str, "published": str, "source": str}
"""
from __future__ import annotations
import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import aiohttp
from utils.config import NEWSAPI_KEY, GDELT_ENABLED
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Sources RSS (pas de clé requise) ─────────────────────────────────────────
RSS_FEEDS: Dict[str, str] = {
    "reuters_world":   "https://feeds.reuters.com/reuters/worldNews",
    "reuters_business":"https://feeds.reuters.com/reuters/businessNews",
    "bbc_world":       "http://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_business":    "http://feeds.bbci.co.uk/news/business/rss.xml",
    "coindesk":        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph":   "https://cointelegraph.com/rss",
    "ft_world":        "https://www.ft.com/world?format=rss",
}

# ── Requêtes GDELT (thèmes macro) ─────────────────────────────────────────────
GDELT_QUERIES = [
    "financial crisis OR market crash OR economic collapse",
    "federal reserve OR ECB OR interest rate OR inflation",
    "war OR geopolitical OR sanctions OR trade war",
    "bitcoin OR cryptocurrency OR crypto regulation",
]

_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)
_MAX_AGE_HOURS = 24   # ignorer les articles > 24h


def _normalize_article(
    title: str,
    description: str,
    url: str,
    published: str,
    source: str,
) -> Dict[str, Any]:
    return {
        "title":       (title or "").strip()[:300],
        "description": (description or "").strip()[:500],
        "url":         url or "",
        "published":   published or datetime.now(timezone.utc).isoformat(),
        "source":      source,
    }


async def _fetch_rss(session: aiohttp.ClientSession, name: str, url: str) -> List[Dict[str, Any]]:
    """Parse un flux RSS et retourne les articles normalisés."""
    articles = []
    try:
        async with session.get(url, timeout=_TIMEOUT, ssl=False) as resp:
            if resp.status != 200:
                return []
            text = await resp.text(errors="replace")

        root = ET.fromstring(text)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}

        # Format RSS 2.0
        items = root.findall(".//item")
        for item in items[:15]:
            title = item.findtext("title", "")
            desc  = item.findtext("description", "")
            link  = item.findtext("link", "")
            pub   = item.findtext("pubDate", "")
            articles.append(_normalize_article(title, desc, link, pub, name))

        # Format Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title = entry.findtext("atom:title", "", ns)
                desc  = entry.findtext("atom:summary", "", ns)
                link_el = entry.find("atom:link", ns)
                link  = link_el.get("href", "") if link_el is not None else ""
                pub   = entry.findtext("atom:published", "", ns)
                articles.append(_normalize_article(title, desc, link, pub, name))

    except asyncio.TimeoutError:
        logger.debug("[NEWS] RSS %s timeout", name)
    except Exception as e:
        logger.debug("[NEWS] RSS %s erreur: %s", name, e)
    return articles


async def _fetch_newsapi(session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
    """Interroge NewsAPI.org (requiert NEWSAPI_KEY)."""
    if not NEWSAPI_KEY:
        return []
    articles = []
    try:
        params = {
            "q":        "economy OR crypto OR war OR inflation OR federal reserve",
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 50,
            "apiKey":   NEWSAPI_KEY,
        }
        url = "https://newsapi.org/v2/everything"
        async with session.get(url, params=params, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning("[NEWS] NewsAPI status %d", resp.status)
                return []
            data = await resp.json()
        for art in data.get("articles", []):
            articles.append(_normalize_article(
                art.get("title", ""),
                art.get("description", ""),
                art.get("url", ""),
                art.get("publishedAt", ""),
                f"newsapi/{art.get('source', {}).get('name', 'unknown')}",
            ))
    except Exception as e:
        logger.debug("[NEWS] NewsAPI erreur: %s", e)
    return articles


async def _fetch_gdelt(session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
    """Interroge GDELT v2 Doc API (gratuit, pas de clé)."""
    if not GDELT_ENABLED:
        return []
    articles = []
    try:
        # GDELT: dernières 15 minutes d'actualités mondiales
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            "?query=economy+OR+finance+OR+war+OR+crypto"
            "&mode=artlist&maxrecords=25&format=json"
            "&timespan=1h&sort=DateDesc"
        )
        async with session.get(url, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            data = json.loads(text)
        for art in data.get("articles", []):
            articles.append(_normalize_article(
                art.get("title", ""),
                art.get("seendate", ""),
                art.get("url", ""),
                art.get("seendate", ""),
                "gdelt",
            ))
    except Exception as e:
        logger.debug("[NEWS] GDELT erreur: %s", e)
    return articles


async def fetch_all_news(session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
    """Agrège toutes les sources en parallèle.

    Returns: liste d'articles normalisés (titre, description, url, source, published)
    """
    tasks = []

    # RSS feeds
    for name, url in RSS_FEEDS.items():
        tasks.append(_fetch_rss(session, name, url))

    # NewsAPI + GDELT
    tasks.append(_fetch_newsapi(session))
    tasks.append(_fetch_gdelt(session))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: List[Dict[str, Any]] = []
    for res in results:
        if isinstance(res, list):
            all_articles.extend(res)
        elif isinstance(res, Exception):
            logger.debug("[NEWS] Erreur source: %s", res)

    # Déduplication par URL
    seen: set = set()
    unique = []
    for art in all_articles:
        url = art.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(art)

    logger.info("[NEWS] %d articles uniques récupérés (%d sources)", len(unique), len(tasks))
    return unique


def get_all_text(articles: List[Dict[str, Any]]) -> str:
    """Concatène titre + description de tous les articles pour le scoring."""
    parts = []
    for art in articles:
        parts.append(f"{art.get('title', '')} {art.get('description', '')}")
    return " ".join(parts).lower()
