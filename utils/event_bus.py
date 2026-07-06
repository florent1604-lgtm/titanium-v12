"""utils/event_bus.py — Bus d'événements typés, append-only, pour le dashboard temps réel.

Types utilisés : SIGNAL, GUARD, SPECTRAL, TRADE, HEARTBEAT, JARVIS.

Placé dans utils/ (comme config.py/logger.py) car émis depuis core/, execution/, api/ et
assistant/ indifféremment — un module partagé évite les dépendances circulaires entre couches.

EVENT_BUS_ENABLED=1 par défaut : purement passif (append + notification), n'affecte jamais
le chemin signal/exécution. emit() est synchrone pour rester appelable depuis n'importe quel
contexte (sync ou async) sans changer la signature des fonctions appelantes.
"""
from __future__ import annotations
import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List

from utils.config import EVENT_BUS_ENABLED, EVENT_BUS_MAX_MEMORY, EVENTS_FILE
from utils.logger import get_logger

logger = get_logger(__name__)

_events: Deque[Dict[str, Any]] = deque(maxlen=EVENT_BUS_MAX_MEMORY)
_subscribers: List["asyncio.Queue[Dict[str, Any]]"] = []


def emit(event_type: str, data: Dict[str, Any]) -> None:
    """Émet un événement typé — append mémoire + fichier, notifie les abonnés WS."""
    if not EVENT_BUS_ENABLED:
        return
    event = {"type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **data}
    _events.append(event)
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        logger.debug("[EVENTBUS] écriture disque échouée: %s", e)
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass


def get_recent(limit: int = 100, event_type: str = "") -> List[Dict[str, Any]]:
    """Derniers événements en mémoire, le plus récent en premier."""
    events = list(_events)
    if event_type:
        events = [e for e in events if e.get("type") == event_type]
    return list(reversed(events))[:limit]


def subscribe() -> "asyncio.Queue[Dict[str, Any]]":
    """Abonne un client (typiquement une connexion WS) — à désabonner via unsubscribe()."""
    q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    return q


def unsubscribe(q: "asyncio.Queue[Dict[str, Any]]") -> None:
    if q in _subscribers:
        _subscribers.remove(q)
