"""assistant/plugins/memory_plugin.py — Gestion de la mémoire persistante."""
from __future__ import annotations
import logging
import re
from typing import Dict, Any, Optional

from assistant.plugins.base import TitanPlugin
from assistant.memory_store import (
    remember, forget, get, add_note, get_notes, get_all, get_context_summary,
    clear_category,
)

logger = logging.getLogger(__name__)

_PREF_RE = re.compile(
    r"(?:je préfère|j'aime|j'adore|trading time|trading_time)\s+(.+)",
    re.IGNORECASE,
)
_NOTE_RE = re.compile(
    r"note\s*[:\-–]\s*(.+)|note que\s+(.+)|note\s*:\s*(.+)",
    re.IGNORECASE,
)
_REMEMBER_RE = re.compile(
    r"(?:souviens-toi que|souviens toi que|rappelle-toi que|mémorise que|garde en mémoire que|remember that)\s+(.+)",
    re.IGNORECASE,
)
_FORGET_RE = re.compile(
    r"(?:oublie|efface|supprime)\s+(?:mes\s+)?(\w+)",
    re.IGNORECASE,
)

_QUERY_WORDS = [
    "qu'est-ce que tu sais", "quelles sont tes notes", "tes notes",
    "ce que tu sais de moi", "ta mémoire", "ce que tu retiens",
    "affiche mémoire", "montre mémoire",
]


class MemoryPlugin(TitanPlugin):
    """Enregistre, consulte et efface la mémoire persistante de Titan."""

    name = "memory"
    intents = ["remember", "memory", "note", "souviens", "forget", "preference"]
    min_confidence = 0.55

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        t = text.strip()
        t_lower = t.lower()

        # ── Effacement ────────────────────────────────────────────────────────
        if intent == "forget" or any(w in t_lower for w in ["oublie", "efface", "supprime"]):
            m = _FORGET_RE.search(t_lower)
            if m:
                cat = m.group(1)
                if cat in ("preferences", "préférences", "preference"):
                    clear_category("preferences")
                    return "Préférences effacées."
                elif cat in ("notes",):
                    clear_category("notes")
                    return "Notes effacées."
                elif cat in ("facts", "faits"):
                    clear_category("facts")
                    return "Faits effacés."
                else:
                    forget(cat)
                    return f"'{cat}' oublié."
            return "Qu'est-ce que je dois oublier exactement ?"

        # ── Consultation ──────────────────────────────────────────────────────
        if any(w in t_lower for w in _QUERY_WORDS) or intent == "memory":
            summary = get_context_summary()
            notes = get_notes(5)
            parts = []
            if summary:
                parts.append(summary)
            if notes:
                parts.append("Notes: " + " | ".join(notes))
            return "\n".join(parts) if parts else "Je n'ai rien mémorisé pour l'instant."

        # ── Note ─────────────────────────────────────────────────────────────
        if intent == "note" or "note" in t_lower:
            m = _NOTE_RE.search(t)
            note_text = m.group(1) or m.group(2) or m.group(3) if m else None
            if note_text:
                note_text = note_text.strip()
                add_note(note_text)
                return f"Note enregistrée : {note_text}"
            return "Qu'est-ce que je dois noter ?"

        # ── Mémorisation d'une préférence ─────────────────────────────────────
        if intent == "preference":
            m = _PREF_RE.search(t)
            if m:
                value = m.group(1).strip()
                remember("preference_general", value, "preferences")
                return f"Préférence mémorisée : {value}"

        # ── Mémorisation générique ─────────────────────────────────────────────
        if intent in ("remember", "souviens"):
            m = _REMEMBER_RE.search(t)
            if m:
                fact = m.group(1).strip()
                # Essayer d'extraire clé=valeur
                kv = re.match(r"(\w[\w\s]*?)\s+(?:est|=|:)\s+(.+)", fact, re.IGNORECASE)
                if kv:
                    key = kv.group(1).strip().lower().replace(" ", "_")
                    val = kv.group(2).strip()
                    remember(key, val)
                    return f"Mémorisé : {key} = {val}"
                else:
                    add_note(fact)
                    return f"Noté : {fact}"

            # Fallback: mémoriser tout le texte nettoyé comme note
            clean = re.sub(
                r"\b(titan|hey titan|jarvis|souviens-toi|souviens toi|rappelle-toi|mémorise|garde en mémoire)\b",
                "", t_lower, flags=re.IGNORECASE
            ).strip(" ,.!?")
            if clean:
                add_note(clean)
                return f"Noté : {clean}"

        return None
