"""tools/llm_adapt_study.py — étude LLM LOCAL des choix de positions (Florent 27/07).

Le LLM local (Ollama, aucune API commerciale) étudie les RÉSULTATS RÉELS du bot (perf par
nombre de piliers / structure / catégorie / sens, + coût des refus du journal non censuré) et
propose une RÉADAPTATION par piliers. C'est CONSULTATIF : le LLM PROPOSE, Florent valide, le
moteur déterministe décide (invariant du fil débranché — aucune décision ne dépend du LLM).

Lecture seule. Écrit data/llm_adapt_proposal.md.
Usage : venv\\Scripts\\python.exe -m tools.llm_adapt_study [--model qwen2.5:7b]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "llm_adapt_proposal.md"


def _ollama(prompt: str, model: str, timeout: int = 420) -> str:
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2, "num_ctx": 8192}}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rows(agg: dict, dim: str) -> str:
    out = []
    for r in (agg.get(dim) or [])[:8]:
        out.append(f"    {r.get(dim)}: n={r.get('n')} winrate={r.get('winrate')}% "
                   f"esperance={r.get('expectancy_R')}R PF={r.get('profit_factor')} PnL={r.get('sum_pnl')}")
    return "\n".join(out) or "    (aucune donnée)"


def build_prompt() -> str:
    ta = _load(ROOT / "data" / "trade_analytics.json")
    jr = _load(ROOT / "data" / "journal_report.json")
    agg = ta.get("aggregates", {})
    ov = agg.get("overall", {})
    refus = "\n".join(
        f"    {r['reason']}: n={r['n']} would_win={r.get('would_win_pct')}% ret_moy={r.get('avg_ret_pct')}%"
        for r in (jr.get("refus_counterfactual") or [])[:8]) or "    (aucun)"
    try:
        from core.cloe import get_cloe
        _brief = get_cloe().brief()
    except Exception:
        _brief = ""
    return f"""{_brief}

Tu es Cloe (ci-dessus ta mémoire). Voici les résultats RÉELS (compte démo) d'un bot de trading
qui utilise une méthode de CONFLUENCE à PILIERS (support/résistance, fair-value, liquidité,
OTE/OB, bougie). Le lot est dimensionné selon le nombre de piliers (plus de piliers = plus gros lot).

GLOBAL: trades={ov.get('n')} winrate={ov.get('winrate')}% esperance={ov.get('expectancy_R')}R PF={ov.get('profit_factor')} PnL={ov.get('sum_pnl')}

PAR STRUCTURE (nb de piliers) :
{_rows(agg,'structure')}

PAR CATÉGORIE :
{_rows(agg,'category')}

PAR SENS :
{_rows(agg,'side')}

COÛT DES REFUS (vetos, journal non censuré ; ret_moy>0 = veto a coupé un gagnant) :
{refus}

MISSION — réponds en FRANÇAIS, concis et ACTIONNABLE, en 4 sections :
1. DIAGNOSTIC : quelles configs de piliers / contextes GAGNENT vs PERDENT (chiffres à l'appui).
2. SIZING PAR PILIERS : le lot doit-il monter ou BAISSER avec le nb de piliers ? propose une
   échelle concrète (ex. 1 pilier -> x, 5 piliers -> y).
3. FILTRES DE CONTEXTE : quels actifs/sens/sessions couper ou favoriser.
4. VETOS : lesquels garder, lesquels sont trop stricts (coût d'opportunité).
Base-toi UNIQUEMENT sur les chiffres ci-dessus. Pas de généralités."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:7b")
    args = ap.parse_args()
    prompt = build_prompt()
    print(f"Étude LLM local ({args.model}) — CPU, patiente ~1-3 min…\n")
    try:
        resp = _ollama(prompt, args.model)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Ollama indisponible : {e!r}")
        return 1
    print("=" * 78)
    print(f"  PROPOSITION DU LLM LOCAL ({args.model}) — CONSULTATIF (à valider par Florent)")
    print("=" * 78)
    print(resp.strip())
    OUT.write_text(f"# Proposition LLM local ({args.model}) — {__import__('datetime').datetime.now()}\n\n"
                   + resp.strip() + "\n", encoding="utf-8")
    # Cloe MÉMORISE son analyse (accumulation d'une session à l'autre).
    try:
        from core.cloe import get_cloe
        _first = next((ln.strip() for ln in resp.splitlines() if ln.strip()), resp[:200])
        get_cloe().log_analysis(f"[{args.model}] {_first[:200]}", meta={"file": str(OUT)})
    except Exception:
        pass
    print(f"\n→ proposition persistée : {OUT} (+ mémorisée par Cloe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
