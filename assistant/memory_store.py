"""assistant/memory_store.py — Mémoire persistante JSON pour Titan."""
from __future__ import annotations
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from assistant.config import TITAN_MEMORY_FILE

logger = logging.getLogger(__name__)

_EMPTY: dict = {"preferences": {}, "notes": [], "facts": {}}


def _load() -> dict:
    p = Path(TITAN_MEMORY_FILE)
    if not p.exists():
        return {k: v.copy() if isinstance(v, dict) else list(v) for k, v in _EMPTY.items()}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in _EMPTY:
            if key not in data:
                data[key] = _EMPTY[key].copy() if isinstance(_EMPTY[key], dict) else []
        return data
    except Exception as e:
        logger.warning("[MEMORY] Erreur lecture: %s", e)
        return {k: v.copy() if isinstance(v, dict) else list(v) for k, v in _EMPTY.items()}


def _save(data: dict) -> None:
    p = Path(TITAN_MEMORY_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[MEMORY] Erreur écriture: %s", e)


def remember(key: str, value: str, category: str = "facts") -> None:
    data = _load()
    if category not in data or not isinstance(data[category], dict):
        data[category] = {}
    data[category][key] = value
    _save(data)
    logger.info("[MEMORY] Mémorisé [%s] %s = %s", category, key, value)


def forget(key: str, category: str = "facts") -> None:
    data = _load()
    if category in data and isinstance(data[category], dict):
        data[category].pop(key, None)
        _save(data)
        logger.info("[MEMORY] Oublié [%s] %s", category, key)


def get(key: str, category: str = "facts") -> Optional[str]:
    data = _load()
    return data.get(category, {}).get(key)


def get_all() -> dict:
    return _load()


def add_note(text: str) -> None:
    data = _load()
    data["notes"].append({"date": date.today().isoformat(), "text": text})
    _save(data)
    logger.info("[MEMORY] Note ajoutée: %s", text)


def get_notes(last_n: int = 5) -> list[str]:
    data = _load()
    notes = data.get("notes", [])
    return [f"{n['date']}: {n['text']}" for n in notes[-last_n:]]


def get_context_summary() -> str:
    data = _load()
    parts: list[str] = []

    prefs = data.get("preferences", {})
    if prefs:
        pref_lines = ", ".join(f"{k}={v}" for k, v in prefs.items())
        parts.append(f"Préférences utilisateur: {pref_lines}")

    facts = data.get("facts", {})
    if facts:
        fact_lines = ", ".join(f"{k}: {v}" for k, v in facts.items())
        parts.append(f"Faits mémorisés: {fact_lines}")

    notes = data.get("notes", [])
    if notes:
        last = notes[-3:]
        note_lines = "; ".join(n["text"] for n in last)
        parts.append(f"Notes récentes: {note_lines}")

    return "\n".join(parts) if parts else ""


def clear_category(category: str) -> None:
    data = _load()
    if category in data:
        data[category] = {} if isinstance(data[category], dict) else []
        _save(data)
        logger.info("[MEMORY] Catégorie effacée: %s", category)
