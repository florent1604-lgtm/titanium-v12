"""tools/gen_neural_map.py — Carte neuronale RÉELLE du bot pour l'orbe (DASH v4).

Deux sources, même contrat de sortie (data/neural_map.json) :

1. **GitNexus** (prioritaire, arbitrage Florent 11/07/2026) : interroge le
   registre commun http://localhost:4747/api/graph et projette le VRAI graphe
   d'appels (Function/Method/Class/Route + arêtes CALLS) — le même registre que
   consultent Florent (UI), Codex et Hermes.
2. **AST** (repli, hors-ligne) : imports internes entre modules, comme v3.

Usage : venv\\Scripts\\python.exe tools\\gen_neural_map.py [--source gitnexus|ast|auto]
Regénérer après refactor (ou laisser le watcher GitNexus rafraîchir l'index
puis relancer). L'orbe /orbe recharge le JSON à chaque cycle de page.
"""
from __future__ import annotations

import ast
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "neural_map.json"
GITNEXUS_GRAPH = "http://localhost:4747/api/graph"

# Couches runtime (groupe affiché sur l'orbe). tests/tools/docs exclus.
PACKAGES = {
    "data": "DONNÉES", "indicators": "DONNÉES",
    "core": "CERVEAU", "domain": "CERVEAU", "fundamentals": "CERVEAU",
    "engine": "CERVEAU",
    "execution": "EXÉCUTION",
    "api": "INTERFACE", "assistant": "INTERFACE",
    "utils": "SOCLE", "validation": "SOCLE",
}
MAX_NODES = 140


def _group_of(file_path: str) -> str | None:
    top = file_path.replace("\\", "/").split("/")[0]
    if top == "main.py":
        return "SOCLE"
    return PACKAGES.get(top)


def _mod_of(file_path: str) -> str:
    return file_path.replace("\\", "/").removesuffix(".py").replace("/", ".")


# ── Source 1 : registre GitNexus (graphe d'appels réel) ──────────────────────

def from_gitnexus() -> dict | None:
    try:
        with urllib.request.urlopen(GITNEXUS_GRAPH, timeout=20) as r:
            g = json.load(r)
    except Exception:
        return None

    KEEP = {"Function", "Method", "Class", "Route"}
    nodes: dict[str, dict] = {}
    for n in g.get("nodes", []):
        if n.get("label") not in KEEP:
            continue
        fp = (n.get("properties") or {}).get("filePath") or ""
        grp = _group_of(fp)
        if not grp:
            continue
        nodes[n["id"]] = {
            "id": n["id"], "group": grp, "kind": n["label"].lower(),
            "name": (n["properties"].get("name") or n["id"]).split("/")[-1],
            "file": fp, "mod": _mod_of(fp), "deg": 0,
        }

    EDGE_TYPES = {"CALLS", "HANDLES_ROUTE", "EXTENDS", "HAS_METHOD"}
    edges: set[tuple[str, str]] = set()
    for e in g.get("relationships", []):
        if e.get("type") not in EDGE_TYPES:
            continue
        a, b = e.get("sourceId"), e.get("targetId")
        if a in nodes and b in nodes and a != b:
            edges.add((a, b))

    for a, b in edges:
        nodes[a]["deg"] += 1
        nodes[b]["deg"] += 1

    # top-N connectés ; on garde toujours les routes (surface API réelle)
    ranked = sorted(nodes.values(), key=lambda x: -x["deg"])
    keep = {n["id"] for n in ranked[:MAX_NODES]} | {
        n["id"] for n in nodes.values() if n["kind"] == "route"}
    nodes_k = [n for n in nodes.values() if n["id"] in keep]
    edges_k = [[a, b] for a, b in sorted(edges) if a in keep and b in keep]
    if len(nodes_k) < 20 or len(edges_k) < 20:
        return None  # index vide/partiel → repli AST
    return {"source": "gitnexus", "nodes": nodes_k, "edges": edges_k}


# ── Source 2 : AST des imports (repli hors-ligne, = v3) ──────────────────────

def from_ast() -> dict:
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    files: dict[str, Path] = {}

    for pkg in PACKAGES:
        d = ROOT / pkg
        if not d.is_dir():
            continue
        for py in d.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(ROOT).with_suffix("")
            m = ".".join(rel.parts)
            files[m] = py
            nodes[m] = {"id": m, "group": PACKAGES[pkg], "kind": "module",
                        "name": m.split(".")[-1], "file": str(py.relative_to(ROOT)),
                        "mod": m, "deg": 0}
    main = ROOT / "main.py"
    if main.exists():
        files["main"] = main
        nodes["main"] = {"id": "main", "group": "SOCLE", "kind": "module",
                         "name": "main", "file": "main.py", "mod": "main", "deg": 0}

    tops = {m.split(".")[0] for m in nodes}
    for m, py in files.items():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets = [node.module]
            for t in targets:
                if t.split(".")[0] not in tops:
                    continue
                cand = t
                while cand and cand not in nodes:
                    cand = ".".join(cand.split(".")[:-1])
                if cand and cand != m:
                    edges.add((m, cand))
    for a, b in edges:
        nodes[a]["deg"] += 1
        nodes[b]["deg"] += 1
    ranked = sorted(nodes.values(), key=lambda x: -x["deg"])[:MAX_NODES]
    keep = {n["id"] for n in ranked}
    return {"source": "ast",
            "nodes": [n for n in nodes.values() if n["id"] in keep],
            "edges": [[a, b] for a, b in sorted(edges) if a in keep and b in keep]}


def main() -> None:
    want = "auto"
    if "--source" in sys.argv:
        want = sys.argv[sys.argv.index("--source") + 1]
    data = None
    if want in ("auto", "gitnexus"):
        data = from_gitnexus()
    if data is None and want != "gitnexus":
        data = from_ast()
    if data is None:
        print("ÉCHEC : GitNexus indisponible et repli refusé")
        sys.exit(1)

    data["generated"] = datetime.now(timezone.utc).isoformat()
    data["groups"] = sorted(set(PACKAGES.values()))
    data["nodes"] = sorted(data["nodes"], key=lambda x: x["id"])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"neural_map.json [{data['source']}] : {len(data['nodes'])} nodes, "
          f"{len(data['edges'])} edges")


if __name__ == "__main__":
    main()
