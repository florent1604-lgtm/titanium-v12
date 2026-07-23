"""tools/watch_collab.py — Fenêtre LIVE des échanges Claude <-> Codex.

Pour que Florent VOIE la collaboration en direct au lieu de nous croire sur
parole. Lit le bus append-only (collab/messages/stream.ndjson) et affiche chaque
nouveau message en clair, au fil de l'eau. Aucun secret n'est jamais sur le bus.

Lancement (fenêtre dédiée) :
    venv\\Scripts\\python.exe tools\\watch_collab.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
STREAM = ROOT / "collab" / "messages" / "stream.ndjson"

WHO = {"claude": "🟦 CLAUDE", "codex": "🟧 CODEX", "florent": "🟩 FLORENT",
       "hermes": "🟪 HERMES"}


def _fmt(m: dict) -> str:
    ts = str(m.get("ts_utc", ""))[11:19]
    frm = WHO.get(str(m.get("from")).lower(), str(m.get("from")))
    to = WHO.get(str(m.get("to")).lower(), str(m.get("to")))
    task = m.get("task") or m.get("type") or ""
    content = (m.get("content") or m.get("body") or "").strip()
    head = f"┌─ {ts}  {frm}  →  {to}   [{task}]"
    body = "\n".join("│ " + line for line in _wrap(content, 96))
    return f"{head}\n{body}\n└{'─' * 60}"


def _wrap(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out or [""]


def main() -> None:
    print("=" * 74)
    print("  TITANIUM — ÉCHANGES EN DIRECT  (Claude ⇄ Codex ⇄ Hermes)")
    print("  Chaque bloc = un message réel sur le bus. Actualisé toutes les 2 s.")
    print("  Ferme cette fenêtre quand tu veux — ça n'arrête rien.")
    print("=" * 74)
    seen: set[str] = set()
    first = True
    while True:
        try:
            lines = STREAM.read_text(encoding="utf-8").splitlines() if STREAM.exists() else []
        except Exception:
            lines = []
        rows = []
        for ln in lines:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        # au démarrage : montrer les 8 derniers ; ensuite : uniquement les nouveaux
        show = rows[-8:] if first else [r for r in rows if r.get("id") not in seen]
        for m in show:
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            if m.get("type") in (None, "message") or m.get("content") or m.get("body"):
                print("\n" + _fmt(m))
        for m in rows:
            if m.get("id"):
                seen.add(m["id"])
        if first:
            print(f"\n  … en attente de nouveaux messages ({datetime.now():%H:%M:%S}) …")
            first = False
        time.sleep(2)


if __name__ == "__main__":
    main()
