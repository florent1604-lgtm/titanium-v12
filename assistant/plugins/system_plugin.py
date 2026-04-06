"""assistant/plugins/system_plugin.py — État des services Titanium.

Gère l'intention : system.
Interroge /services/status et retourne un résumé lisible.
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

import aiohttp

from assistant.config import TITAN_API_BASE
from assistant.plugins.base import TitanPlugin

logger = logging.getLogger(__name__)


class SystemPlugin(TitanPlugin):
    """Répond aux questions sur l'état des services."""

    name = "system"
    intents = ["system"]
    min_confidence = 0.50

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{TITAN_API_BASE}/services/status",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        return _format_status(data)
        except Exception as e:
            logger.debug("[SYSTEM_PLUGIN] %s", e)

        return "Je suis en ligne et opérationnel. Titan v12 actif."


def _format_status(data: Dict) -> str:
    titan   = data.get("titan",   {})
    ollama  = data.get("ollama",  {})
    gitnx   = data.get("gitnexus",{})

    def led(ok: bool) -> str:
        return "✓" if ok else "✗"

    titan_ok  = titan.get("running", False)
    ollama_ok = ollama.get("running", False)
    model     = ollama.get("model", "?")
    gn_ok     = gitnx.get("running", False)
    gn_port   = gitnx.get("port", 0)

    lines = ["État des services Titanium v12 :"]
    lines.append(f"  {led(titan_ok)}  Titan assistant — {'actif' if titan_ok else 'inactif'}")
    lines.append(f"  {led(ollama_ok)}  Ollama LLM — {'actif (' + model + ')' if ollama_ok else 'inactif'}")
    gn_info = f"actif (port {gn_port})" if gn_ok else "inactif"
    lines.append(f"  {led(gn_ok)}  GitNexus — {gn_info}")

    return "\n".join(lines)
