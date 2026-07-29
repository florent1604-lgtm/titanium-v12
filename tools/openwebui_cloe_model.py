"""tools/openwebui_cloe_model.py — crée/rafraîchit le modèle « Cloe » dans Open WebUI.

Injecte la mémoire vivante de Cloe (data/cloe/knowledge/*.md : identité, architecture,
findings, news/macro) dans le SYSTEM PROMPT d'un modèle Open WebUI « Cloe » (base qwen2.5:7b).
Plus robuste que le RAG pour un contenu petit et TOUJOURS pertinent (pas besoin d'embeddings).

La connaissance se régénère toute seule (boucle de débrief du bot, ~10 min) → RELANCE ce script
pour rafraîchir la mémoire de Cloe (findings/news à jour).

Usage :
  set OPENWEBUI_API_KEY=sk-xxxx & venv\\Scripts\\python.exe tools\\openwebui_cloe_model.py
  # ou : venv\\Scripts\\python.exe tools\\openwebui_cloe_model.py sk-xxxx
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

BASE = os.getenv("OPENWEBUI_BASE_URL", "http://localhost:3000").rstrip("/")
BASE_MODEL = os.getenv("CLOE_BASE_MODEL", "qwen2.5:7b")
ROOT = Path(__file__).resolve().parent.parent
KDIR = ROOT / "data" / "cloe" / "knowledge"

PERSONA = (
    "Tu es Cloe, l'intelligence analytique du bot de trading Titanium V12 de Florent. "
    "Tu parles français, tu es factuelle, concise et honnête (tu dis quand tu ne sais pas). "
    "Tu raisonnes à partir de TA MÉMOIRE ci-dessous (identité, architecture, findings, "
    "news/macro). Tu n'apportes jamais de conseil financier à un tiers : tu analyses le "
    "système de Florent.\n\n===== MÉMOIRE DE CLOE (source de vérité) =====\n"
)


def _key() -> str:
    key = (sys.argv[1] if len(sys.argv) > 1 else "") or os.getenv("OPENWEBUI_API_KEY", "")
    if not key.strip():
        print("❌ Clé API manquante (Open WebUI → Compte → Clés API).")
        raise SystemExit(2)
    return key.strip()


def main() -> int:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {_key()}"})
    files = sorted(KDIR.glob("*.md"))
    if not files:
        print(f"❌ Aucune connaissance dans {KDIR}.")
        return 1
    knowledge = "\n\n".join(f"===== {fp.name} =====\n{fp.read_text(encoding='utf-8').strip()}"
                            for fp in files)
    system = PERSONA + knowledge
    payload = {
        "id": "cloe", "base_model_id": BASE_MODEL, "name": "Cloe",
        "meta": {"profile_image_url": "/static/favicon.png",
                 "description": "Intelligence analytique de Titanium V12 — mémoire vivante injectée.",
                 "capabilities": {"vision": False, "citations": False},
                 "tags": [{"name": "titanium"}, {"name": "cloe"}]},
        "params": {"system": system}, "is_active": True,
    }
    r = s.post(f"{BASE}/api/v1/models/create", json=payload, timeout=60)
    if r.status_code >= 400:
        r = s.post(f"{BASE}/api/v1/models/model/update?id=cloe", json=payload, timeout=60)
        action = "mis à jour"
    else:
        action = "créé"
    if r.ok:
        print(f"✅ Modèle « Cloe » {action} (base {BASE_MODEL}, mémoire {len(system)} caractères).")
        print("   Interface : http://localhost:3000 → sélectionne « Cloe » → discute.")
        return 0
    print(f"❌ Échec : {r.status_code} {r.text[:200]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
