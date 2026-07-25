"""tools/entry_memory.py — MÉMOIRE D'ADAPTATION des points d'entrée (Florent 25/07).

« On s'adapte et on mémorise au fur et à mesure. » Cet outil lit le journal démo
(data/demo_journal.ndjson) et accumule, PAR CONTEXTE D'ENTRÉE, ce que le moteur a
réellement pris pendant la phase de test — pour ajuster nos points d'entrée.

Contexte = (moteur, symbole, sens, tranche de taille). La taille (lot/risk_money)
encode désormais la QUALITÉ DE STRUCTURE (plus de piliers → plus gros lot), donc la
tranche de taille est un proxy direct de la structure du setup.

Persiste un instantané dans data/entry_adaptation.json (mémoire réutilisable).

Extension prévue (au fur et à mesure) : quand les trades démo se clôturent (TP/SL),
on joint le PnL par ticket pour obtenir le WINRATE / l'ESPÉRANCE par contexte, et on
remonte/abaisse la taille des structures qui gagnent/perdent.

Usage : venv\\Scripts\\python.exe -m tools.entry_memory
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL = os.path.join(ROOT, "data", "demo_journal.ndjson")
MEMORY = os.path.join(ROOT, "data", "entry_adaptation.json")


def _size_bucket(risk_money) -> str:
    """Tranche de taille = proxy de structure (le size_factor scale sur les piliers)."""
    try:
        r = float(risk_money)
    except (TypeError, ValueError):
        return "?"
    if r <= 0:
        return "0"
    if r < 8:
        return "S (~2 piliers)"
    if r < 20:
        return "M (~3 piliers)"
    if r < 45:
        return "L (~4 piliers)"
    return "XL (~5 piliers/pleine structure)"


def load_entries() -> list[dict]:
    rows = []
    try:
        with open(JOURNAL, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return rows


def build_memory() -> dict:
    rows = load_entries()
    placed = [r for r in rows if r.get("sent")]
    rejected = [r for r in rows if r.get("sent") is False]

    by_ctx = defaultdict(lambda: {"n": 0, "lots": [], "risks": [], "emotions": defaultdict(int)})
    for r in placed:
        ctx = (r.get("engine"), r.get("symbol"), r.get("side"), _size_bucket(r.get("risk_money")))
        slot = by_ctx[ctx]
        slot["n"] += 1
        if r.get("lot") is not None:
            slot["lots"].append(r["lot"])
        if r.get("risk_money") is not None:
            slot["risks"].append(r["risk_money"])
        emo = (r.get("emotion_observed") or {})
        for s in (emo.get("sources") or []):
            slot["emotions"][s] += 1

    contexts = []
    for (engine, sym, side, bucket), slot in sorted(by_ctx.items(), key=lambda kv: -kv[1]["n"]):
        contexts.append({
            "engine": engine, "symbol": sym, "side": side, "structure": bucket,
            "count": slot["n"],
            "avg_lot": round(sum(slot["lots"]) / len(slot["lots"]), 4) if slot["lots"] else None,
            "avg_risk": round(sum(slot["risks"]) / len(slot["risks"]), 2) if slot["risks"] else None,
            "emotions_top": sorted(slot["emotions"].items(), key=lambda kv: -kv[1])[:3],
        })

    # Motifs de refus les plus fréquents (pour ajuster les points d'entrée bloqués).
    rej = defaultdict(int)
    for r in rejected:
        code = str(r.get("reason") or "?").split(":")[0]
        rej[code] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_journalise": len(rows),
        "places": len(placed),
        "refuses": len(rejected),
        "par_structure": _by_structure(placed),
        "contexts": contexts,
        "refus_top": sorted(rej.items(), key=lambda kv: -kv[1])[:6],
        "note_outcomes": "Winrate/esperance par contexte -> ajoutes quand les trades se cloturent (join PnL par ticket).",
    }


def _by_structure(placed: list[dict]) -> dict:
    agg = defaultdict(lambda: {"count": 0, "risk": 0.0})
    for r in placed:
        b = _size_bucket(r.get("risk_money"))
        agg[b]["count"] += 1
        try:
            agg[b]["risk"] += float(r.get("risk_money") or 0)
        except (TypeError, ValueError):
            pass
    return {k: {"count": v["count"], "risk_total": round(v["risk"], 2)} for k, v in agg.items()}


def save_memory(mem: dict) -> None:
    os.makedirs(os.path.dirname(MEMORY), exist_ok=True)
    with open(MEMORY, "w", encoding="utf-8") as fh:
        json.dump(mem, fh, ensure_ascii=False, indent=2)


def main() -> int:
    mem = build_memory()
    save_memory(mem)
    print("=" * 60)
    print("  MÉMOIRE D'ADAPTATION — points d'entrée (phase de test démo)")
    print("=" * 60)
    print(f"journalisé={mem['total_journalise']} | placés={mem['places']} | refusés={mem['refuses']}")
    print(f"\nPar STRUCTURE (taille = proxy piliers) :")
    for k, v in mem["par_structure"].items():
        print(f"  {k:32s} n={v['count']:4d}  risque_total={v['risk_total']}")
    print(f"\nTop contextes d'entrée pris :")
    for c in mem["contexts"][:10]:
        print(f"  {str(c['engine']):16s} {str(c['symbol']):8s} {str(c['side']):5s} "
              f"[{c['structure']}] n={c['count']} lot~{c['avg_lot']} risk~{c['avg_risk']}")
    print(f"\nTop motifs de refus (points d'entrée bloqués) :")
    for code, n in mem["refus_top"]:
        print(f"  {code:28s} {n}")
    print(f"\n-> mémoire persistée : {MEMORY}")
    print(mem["note_outcomes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
