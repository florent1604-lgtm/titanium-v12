"""core/cloe/memory.py — mémoire PERSISTANTE, HIÉRARCHISÉE, DOCUMENTÉE de Cloe (LLM local).

But (Florent 27/07) : « le LLM local doit impérativement avoir un noyau mémoire persistant et
correctement hiérarchisé et documenté pour optimiser sa rapidité. »

HIÉRARCHIE (catégories, du plus stable au plus volatil) :
  1. identity   — qui est Cloe (rôle, contraintes non négociables).
  2. architecture — la pyramide + pointeurs vers les organes (où regarder).
  3. findings   — ce que Cloe a APPRIS (faits mesurés, réutilisables).
  4. directives — décisions de Florent (le master).
  5. analyses   — journal horodaté des dernières analyses/propositions (ring borné).

RAPIDITÉ : `brief()` produit un contexte COMPACT (hiérarchie condensée) que le LLM lit en
préfixe → il n'a plus à re-dériver le contexte à chaque appel, et le prompt reste court
(décisif sur un CPU à ~4 tok/s). La mémoire persiste (data/cloe/memory.json), donc les
apprentissages s'accumulent d'une session à l'autre.

Socle N0 : n'importe aucun module métier. Écritures atomiques, thread-safe, fail-safe.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
_STORE = _ROOT / "data" / "cloe" / "memory.json"

# Ordre hiérarchique (stable → volatil). `analyses` est une LISTE (journal), le reste des dicts.
_CATEGORIES = ["identity", "architecture", "findings", "directives", "analyses"]
_ANALYSES_MAX = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Cloe:
    """Accès à la mémoire persistante de Cloe."""

    def __init__(self, path: Path = _STORE):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        for c in _CATEGORIES:
            d.setdefault(c, [] if c == "analyses" else {})
        return d

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    # ── écriture ──────────────────────────────────────────────────────────────
    def remember(self, category: str, key: str, content: str, meta: Optional[dict] = None) -> None:
        if category not in _CATEGORIES or category == "analyses":
            return
        with self._lock:
            self._data.setdefault(category, {})[key] = {
                "content": content, "meta": meta or {}, "updated": _now()}
            self._save()

    def log_analysis(self, summary: str, meta: Optional[dict] = None) -> None:
        """Journalise une analyse/proposition (ring borné)."""
        with self._lock:
            self._data.setdefault("analyses", []).append(
                {"ts": _now(), "summary": summary, "meta": meta or {}})
            self._data["analyses"] = self._data["analyses"][-_ANALYSES_MAX:]
            self._save()

    def forget(self, category: str, key: str) -> None:
        with self._lock:
            if isinstance(self._data.get(category), dict):
                self._data[category].pop(key, None)
                self._save()

    # ── lecture ───────────────────────────────────────────────────────────────
    def recall(self, category: Optional[str] = None) -> Any:
        with self._lock:
            if category:
                return json.loads(json.dumps(self._data.get(category)))
            return json.loads(json.dumps(self._data))

    def brief(self, max_chars: int = 2600, recent_analyses: int = 3) -> str:
        """Contexte COMPACT hiérarchisé pour le LLM (rapidité : prompt court + persistant)."""
        with self._lock:
            d = self._data
        lines: List[str] = ["# MÉMOIRE DE CLOE (brief)"]
        titles = {"identity": "Identité", "architecture": "Architecture",
                  "findings": "Ce que j'ai appris (findings)", "directives": "Directives de Florent"}
        for cat in ["identity", "architecture", "findings", "directives"]:
            entries = d.get(cat) or {}
            if not entries:
                continue
            lines.append(f"\n## {titles[cat]}")
            for k, v in entries.items():
                lines.append(f"- {k}: {v.get('content')}")
        an = (d.get("analyses") or [])[-recent_analyses:]
        if an:
            lines.append("\n## Dernières analyses")
            for a in an:
                lines.append(f"- ({a['ts'][:16]}) {a['summary']}")
        txt = "\n".join(lines)
        return txt[:max_chars]


_shared: Optional[Cloe] = None
_shared_lock = threading.Lock()


def get_cloe() -> Cloe:
    global _shared
    if _shared is None:
        with _shared_lock:
            if _shared is None:
                _shared = Cloe()
    return _shared
