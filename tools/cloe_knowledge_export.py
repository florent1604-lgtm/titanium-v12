"""tools/cloe_knowledge_export.py — EXPORT de la base de connaissance de Cloe pour le RAG.

Écrit `data/cloe/knowledge/*.md` : la mémoire de Cloe (brief), le contexte news/macro courant,
et les findings mesurés. C'est le DOSSIER à ingérer dans Open WebUI (RAG) pour donner à Cloe une
base documentaire à jour — sans qu'aucune donnée ne sorte de la machine.

Usage : venv\\Scripts\\python.exe -m tools.cloe_knowledge_export
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
KDIR = ROOT / "data" / "cloe" / "knowledge"


def export() -> dict:
    KDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    written = []

    # 1) mémoire de Cloe (identité/architecture/findings/directives)
    try:
        from core.cloe import get_cloe
        (KDIR / "01_cloe_memoire.md").write_text(
            f"# Mémoire de Cloe — {now}\n\n{get_cloe().brief(max_chars=6000)}\n", encoding="utf-8")
        written.append("01_cloe_memoire.md")
    except Exception as e:
        written.append(f"(memoire échec: {e!r})")

    # 2) contexte news / macro courant
    try:
        from core import flux
        mc = flux.market_context(); news = flux.news_headlines(limit=12)
        lines = [f"# Contexte NEWS / MACRO — {now}", "",
                 f"- Fear&Greed : {mc.get('fear_greed')} ({mc.get('fear_greed_label')})",
                 f"- Marché global : {json.dumps(mc.get('global_market'), ensure_ascii=False)}",
                 "", "## Dernières manchettes (journaux mondiaux)"]
        for a in news:
            lines.append(f"- [{a.get('source')}] {a.get('title')} ({a.get('published')})")
        (KDIR / "02_news_macro.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append("02_news_macro.md")
    except Exception as e:
        written.append(f"(news échec: {e!r})")

    # 3) findings mesurés (perf réelle par contexte, si dispo)
    try:
        ta = json.loads((ROOT / "data" / "trade_analytics.json").read_text(encoding="utf-8"))
        agg = ta.get("aggregates", {}); ov = agg.get("overall", {})
        lines = [f"# Findings mesurés — {now}", "",
                 f"GLOBAL: trades={ov.get('n')} winrate={ov.get('winrate')}% "
                 f"esperance={ov.get('expectancy_R')}R PF={ov.get('profit_factor')} PnL={ov.get('sum_pnl')}", ""]
        for dim in ("structure", "category", "side"):
            lines.append(f"## Par {dim}")
            for r in (agg.get(dim) or [])[:8]:
                lines.append(f"- {r.get(dim)}: n={r.get('n')} winrate={r.get('winrate')}% "
                             f"esp={r.get('expectancy_R')}R PF={r.get('profit_factor')}")
            lines.append("")
        (KDIR / "03_findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append("03_findings.md")
    except Exception as e:
        written.append(f"(findings: {e!r})")

    return {"dir": str(KDIR), "files": written, "generated_at": now}


def main() -> int:
    r = export()
    print(f"Base de connaissance Cloe exportée → {r['dir']}")
    for f in r["files"]:
        print(f"  - {f}")
    print("\n→ dans Open WebUI : Espace de travail > Documents/Connaissances, ingérer ce dossier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
