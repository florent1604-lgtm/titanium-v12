"""tools/openwebui_ingest_cloe.py — ingère la connaissance de Cloe dans Open WebUI (RAG).

Automatise l'option B : crée (ou réutilise) une collection de connaissances « Cloe — Titanium »
dans Open WebUI et y verse les fichiers de `data/cloe/knowledge/` (mémoire, news/macro, findings),
régénérés en continu par le bot. Open WebUI calcule alors les embeddings (via Ollama) → Cloe
répond en RAG sur sa propre mémoire.

PRÉ-REQUIS : une CLÉ API Open WebUI (Paramètres → Compte → Clés API → Créer). L'API l'exige
(sécurité) — impossible sans, c'est voulu.

Usage :
  venv\\Scripts\\python.exe tools\\openwebui_ingest_cloe.py sk-xxxxxxxx
  # ou via l'environnement :
  set OPENWEBUI_API_KEY=sk-xxxx & venv\\Scripts\\python.exe tools\\openwebui_ingest_cloe.py

Idempotent : relancer met la collection à jour (purge les fichiers existants puis ré-ingère
les versions courantes). Lecture seule côté Titanium.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

BASE = os.getenv("OPENWEBUI_BASE_URL", "http://localhost:3000").rstrip("/")
KNOW_NAME = os.getenv("OPENWEBUI_KNOWLEDGE_NAME", "Cloe — Titanium")
KNOW_DESC = "Mémoire vivante de Cloe (identité, architecture, findings, news/macro) — Titanium V12."
ROOT = Path(__file__).resolve().parent.parent
KDIR = ROOT / "data" / "cloe" / "knowledge"
TIMEOUT = 120


def _key() -> str:
    key = (sys.argv[1] if len(sys.argv) > 1 else "") or os.getenv("OPENWEBUI_API_KEY", "")
    key = key.strip()
    if not key:
        print("❌ Clé API manquante. Génère-la dans Open WebUI (Paramètres → Compte → Clés API)\n"
              "   puis : venv\\Scripts\\python.exe tools\\openwebui_ingest_cloe.py <clé>")
        raise SystemExit(2)
    return key


def main() -> int:
    key = _key()
    h = {"Authorization": f"Bearer {key}"}
    s = requests.Session()
    s.headers.update(h)

    files = sorted(KDIR.glob("*.md"))
    if not files:
        print(f"❌ Aucun fichier dans {KDIR} — lance d'abord l'export "
              f"(tools/cloe_knowledge_export.py ou la boucle de débrief du bot).")
        return 1
    print(f"→ Open WebUI : {BASE}")
    print(f"→ {len(files)} fichier(s) à ingérer depuis {KDIR}\n")

    # 1) trouver/créer la collection
    try:
        r = s.get(f"{BASE}/api/v1/knowledge/", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
        existing = {k.get("name"): k for k in items if isinstance(k, dict)}
    except Exception as exc:
        print(f"❌ Impossible de lister les collections ({exc}). Clé API valide ? Open WebUI up ?")
        return 1

    kid = None
    if KNOW_NAME in existing:
        kid = existing[KNOW_NAME]["id"]
        print(f"• Collection existante réutilisée : « {KNOW_NAME} » ({kid})")
        # purge des fichiers déjà présents (ré-ingestion propre)
        try:
            det = s.get(f"{BASE}/api/v1/knowledge/{kid}", timeout=TIMEOUT).json()
            for f in (det.get("files") or []):
                fid = f.get("id")
                if fid:
                    s.post(f"{BASE}/api/v1/knowledge/{kid}/file/remove",
                           json={"file_id": fid}, timeout=TIMEOUT)
            print(f"  purge de {len(det.get('files') or [])} ancien(s) fichier(s).")
        except Exception as exc:
            print(f"  ⚠️ purge partielle ({exc}) — on continue.")
    else:
        r = s.post(f"{BASE}/api/v1/knowledge/create",
                   json={"name": KNOW_NAME, "description": KNOW_DESC}, timeout=TIMEOUT)
        if not r.ok:
            print(f"❌ Création de collection refusée : {r.status_code} {r.text[:200]}")
            return 1
        kid = r.json().get("id")
        print(f"• Collection créée : « {KNOW_NAME} » ({kid})")

    # 2) upload + rattachement de chaque fichier
    ok = 0
    for fp in files:
        try:
            with fp.open("rb") as fh:
                up = s.post(f"{BASE}/api/v1/files/?process=true",
                            files={"file": (fp.name, fh, "text/markdown")}, timeout=TIMEOUT)
            if not up.ok:
                print(f"  ✗ {fp.name} : upload {up.status_code} {up.text[:120]}")
                continue
            fid = up.json().get("id")
            # Open WebUI traite le fichier en ASYNCHRONE (extraction + embeddings). On attend
            # que data.content soit rempli, sinon /file/add échoue « content is empty ».
            ready = False
            for _ in range(30):
                det = s.get(f"{BASE}/api/v1/files/{fid}", timeout=TIMEOUT).json()
                content = det.get("content") or (det.get("data") or {}).get("content") or ""
                if content.strip():
                    ready = True
                    break
                time.sleep(2)
            if not ready:
                print(f"  ✗ {fp.name} : traitement non terminé (contenu vide après 60 s)")
                continue
            add = s.post(f"{BASE}/api/v1/knowledge/{kid}/file/add",
                         json={"file_id": fid}, timeout=TIMEOUT)
            if add.ok:
                print(f"  ✓ {fp.name}  → embeddings en cours côté Open WebUI")
                ok += 1
            else:
                print(f"  ✗ {fp.name} : add {add.status_code} {add.text[:120]}")
        except Exception as exc:
            print(f"  ✗ {fp.name} : {exc}")

    print(f"\n✅ {ok}/{len(files)} fichier(s) ingéré(s) dans « {KNOW_NAME} ».")
    print("   Dans Open WebUI : ouvre un chat, tape # puis choisis la collection, ou attache-la à "
          "un modèle « Cloe » (Espace de travail → Modèles).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
