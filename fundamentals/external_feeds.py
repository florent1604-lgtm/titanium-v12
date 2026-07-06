"""fundamentals/external_feeds.py — Flux de données externes gratuits (v13).

Sources sans clé API, rafraîchies en continu pour enrichir le contexte macro :
  - Fear & Greed Index crypto (alternative.me) — sentiment de marché [0..100]
  - Global market snapshot (CoinGecko /global) — dominance BTC, market cap 24h

Chaque source est isolée : une panne d'un flux ne casse ni les autres ni le bot.
Les valeurs sont exposées via get_external_snapshot() → /api/state → dashboard.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

import aiohttp

from utils.logger import get_logger

logger = get_logger(__name__)

FNG_URL       = "https://api.alternative.me/fng/?limit=1"
COINGECKO_URL = "https://api.coingecko.com/api/v3/global"
REFRESH_SEC   = 900          # 15 min — ces indices bougent lentement

_snapshot: Dict[str, Any] = {}


def get_external_snapshot() -> Dict[str, Any]:
    return dict(_snapshot)


async def _fetch_fear_greed(session: aiohttp.ClientSession) -> None:
    try:
        async with session.get(FNG_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return
            data = await r.json(content_type=None)
            item = (data.get("data") or [{}])[0]
            _snapshot["fear_greed"] = {
                "value":  int(item.get("value", 0)),
                "label":  item.get("value_classification", "?"),
                "ts":     datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.debug("[EXT] fear_greed: %s", e)


async def _fetch_global_market(session: aiohttp.ClientSession) -> None:
    try:
        async with session.get(COINGECKO_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return
            data = (await r.json(content_type=None)).get("data", {})
            _snapshot["global_market"] = {
                "btc_dominance_pct": round(float(data.get("market_cap_percentage", {}).get("btc", 0)), 1),
                "mcap_change_24h_pct": round(float(data.get("market_cap_change_percentage_24h_usd", 0)), 2),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.debug("[EXT] global_market: %s", e)


async def external_feeds_loop(session: aiohttp.ClientSession) -> None:
    """Boucle de rafraîchissement des flux externes — 1 tâche asyncio."""
    logger.info("[EXT] Flux externes démarrés (Fear&Greed, CoinGecko) — refresh %ds", REFRESH_SEC)
    while True:
        await asyncio.gather(
            _fetch_fear_greed(session),
            _fetch_global_market(session),
        )
        fg = _snapshot.get("fear_greed", {})
        gm = _snapshot.get("global_market", {})
        if fg or gm:
            logger.info("[EXT] F&G=%s (%s) | BTC.D=%s%% | mcap24h=%s%%",
                        fg.get("value", "—"), fg.get("label", "—"),
                        gm.get("btc_dominance_pct", "—"), gm.get("mcap_change_24h_pct", "—"))
        await asyncio.sleep(REFRESH_SEC)
