"""tools/openwebui_cloe_super.py — enregistre « Cloe Super » : la FUSION multi-cerveaux.

Crée dans Open WebUI une FONCTION (pipe) qui, à chaque question :
  1. injecte la mémoire de Cloe (data/cloe/knowledge/*.md, lue à chaud) ;
  2. interroge PLUSIEURS cerveaux locaux en parallèle (qwen2.5:7b + phi3:medium) ;
  3. envoie leurs brouillons à un synthétiseur qui produit UNE réponse fusionnée.

Résultat : un modèle sélectionnable « Cloe Super » qui raisonne avec tous les cerveaux à la fois.
⚠️ CPU only → 3 inférences par question = lent (~1-3 min). Modèles réglables via les Valves.

Usage : venv\\Scripts\\python.exe tools\\openwebui_cloe_super.py sk-xxxx
"""
from __future__ import annotations
import os, sys, requests

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

BASE = os.getenv("OPENWEBUI_BASE_URL", "http://localhost:3000").rstrip("/")

# ── Code de la FONCTION exécutée DANS Open WebUI ─────────────────────────────
PIPE_CODE = r'''"""
title: Cloe Super
author: Titanium
version: 0.1.0
description: Fusion multi-cerveaux de Cloe — interroge plusieurs modeles locaux et synthetise UNE reponse.
"""
import os, glob, concurrent.futures, requests
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        OLLAMA_URL: str = Field(default="http://127.0.0.1:11434")
        BRAINS: str = Field(default="qwen2.5:7b,phi3:medium")
        SYNTHESIZER: str = Field(default="qwen2.5:7b")
        KNOWLEDGE_DIR: str = Field(default="C:/Users/flore/Desktop/v12/data/cloe/knowledge")
        SHOW_DRAFTS: bool = Field(default=True)

    def __init__(self):
        self.type = "pipe"
        self.id = "cloe_super"
        self.name = "Cloe Super"
        self.valves = self.Valves()

    def _memory(self):
        try:
            parts = []
            for fp in sorted(glob.glob(os.path.join(self.valves.KNOWLEDGE_DIR, "*.md"))):
                with open(fp, "r", encoding="utf-8") as fh:
                    parts.append("===== " + os.path.basename(fp) + " =====\n" + fh.read().strip())
            return "\n\n".join(parts)
        except Exception:
            return ""

    def _ask(self, model, messages):
        try:
            r = requests.post(self.valves.OLLAMA_URL + "/api/chat",
                              json={"model": model, "messages": messages, "stream": False},
                              timeout=900)
            return model, (r.json().get("message", {}) or {}).get("content", "").strip()
        except Exception as e:
            return model, "(erreur " + model + ": " + str(e) + ")"

    def pipe(self, body, __user__=None, __event_emitter__=None):
        import asyncio
        messages = list(body.get("messages", []))
        persona = ("Tu es Cloe, l'intelligence analytique du bot Titanium V12 de Florent. "
                   "Francais, factuelle, concise, honnete. Base-toi sur TA MEMOIRE ci-dessous.\n\n"
                   "===== MEMOIRE =====\n" + self._memory())
        convo = [{"role": "system", "content": persona}] + \
                [m for m in messages if m.get("role") in ("user", "assistant")]
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", ""); break

        def emit(txt):
            if __event_emitter__:
                try:
                    asyncio.get_event_loop().create_task(__event_emitter__(
                        {"type": "status", "data": {"description": txt, "done": False}}))
                except Exception:
                    pass

        brains = [b.strip() for b in self.valves.BRAINS.split(",") if b.strip()]
        emit("Cloe consulte " + str(len(brains)) + " cerveaux...")
        drafts = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(brains))) as ex:
            for model, ans in ex.map(lambda b: self._ask(b, convo), brains):
                drafts[model] = ans
        emit("Fusion des analyses...")

        synth = ("Tu es Cloe. Plusieurs de tes cerveaux ont analyse la meme question. "
                 "Fusionne leurs analyses en UNE reponse finale : garde le meilleur de chaque, "
                 "signale et tranche les desaccords, reste factuelle et concise.\n\n")
        for model, ans in drafts.items():
            synth += "----- " + model + " -----\n" + ans + "\n\n"
        synth += "Question : " + user_msg + "\n\nReponse fusionnee de Cloe :"
        _, fused = self._ask(self.valves.SYNTHESIZER,
                             [{"role": "system", "content": persona},
                              {"role": "user", "content": synth}])

        if self.valves.SHOW_DRAFTS:
            out = "## Cloe Super - fusion\n\n" + fused + "\n\n---\n"
            out += "<details><summary>Analyses individuelles des cerveaux</summary>\n\n"
            for model, ans in drafts.items():
                out += "**" + model + "**\n\n" + ans + "\n\n"
            out += "</details>"
            return out
        return fused
'''


def main() -> int:
    key = (sys.argv[1] if len(sys.argv) > 1 else "") or os.getenv("OPENWEBUI_API_KEY", "")
    if not key.strip():
        print("❌ Clé API manquante."); return 2
    s = requests.Session(); s.headers.update({"Authorization": f"Bearer {key.strip()}"})
    payload = {"id": "cloe_super", "name": "Cloe Super", "content": PIPE_CODE,
               "meta": {"description": "Fusion multi-cerveaux de Cloe (qwen + phi3 → synthèse).",
                        "manifest": {"title": "Cloe Super", "version": "0.1.0"}}}
    r = s.post(f"{BASE}/api/v1/functions/create", json=payload, timeout=40)
    print("create function:", r.status_code, r.text[:160] if r.status_code >= 400 else "OK")
    # active la fonction
    for ep in (f"/api/v1/functions/id/cloe_super/toggle", f"/api/v1/functions/cloe_super/toggle"):
        t = s.post(BASE + ep, timeout=20)
        if t.ok:
            print("toggle actif:", t.status_code); break
    g = s.get(f"{BASE}/api/v1/functions/", timeout=20).json()
    fns = [f.get("id") for f in g] if isinstance(g, list) else g
    print("fonctions enregistrées:", fns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
