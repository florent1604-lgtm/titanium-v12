"""tools/position_debrief.py — DÉBRIEF analytique PAR POSITION (Florent 27/07).

« Tous les flux corrélés doivent être associés à une prise de position, reportés et journalisés
pour améliorer la structure des analyses du bot et affiner ses positions. Détailler exactement
la raison pour laquelle la position a été prise et un débrief analytique ensuite par position,
le tout journalisé en mémoire. »

Ce script relie chaque position CLÔTURÉE (historique MT5) à son RATIONALE D'ENTRÉE (journal
unifié, kind=fill : piliers + flux fondamentaux/coût/régime/émotion) et produit un DÉBRIEF :
raison d'entrée → résultat (SL/TP, R). Journalisé (kind=debrief) + mémorisé par Cloe pour
accumuler des enseignements par contexte.

Lecture seule. Écrit data/position_debriefs.json.
Usage : venv\\Scripts\\python.exe -m tools.position_debrief [--hours 24]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "position_debriefs.json"
_REASON = {0: "MANUEL", 3: "EXPERT", 4: "SL", 5: "TP", 6: "TS"}


def debrief(hours: int = 24) -> dict:
    import MetaTrader5 as mt5
    from ingestion.market.mt5_provider import ensure_init, mt5_lock
    from core.journal import get_journal
    from core.cloe import get_cloe
    if not ensure_init():
        raise RuntimeError("MT5 non initialisé.")
    now = datetime.now(timezone.utc); since = now - timedelta(hours=hours)
    j = get_journal(); cloe = get_cloe()

    # 1) rationales d'entrée (journal fills) indexés par ticket
    fills = j.read(kind="fill", since_iso=(since - timedelta(hours=6)).isoformat(), limit=100000)
    by_ticket = {}
    for f in fills:
        tk = (f.get("payload") or {}).get("ticket")
        if tk:
            by_ticket[int(tk)] = f["payload"]

    # 2) positions clôturées (deals MT5)
    with mt5_lock:
        deals = mt5.history_deals_get(since - timedelta(hours=2), now + timedelta(hours=2))
    from collections import defaultdict
    raw = defaultdict(dict)
    for d in (deals or []):
        raw[d.position_id]["in" if d.entry == 0 else "out"] = d

    debriefs = []; already = {b.get("meta", {}).get("ticket") for b in cloe.recall("analyses")
                              if b.get("meta", {}).get("kind") == "debrief"}
    for pid, pair in raw.items():
        din, dout = pair.get("in"), pair.get("out")
        if not dout or not din:
            continue
        if not str(getattr(din, "comment", "") or "").startswith("titanium"):
            continue
        rat = by_ticket.get(int(pid))                # rationale d'entrée (si connu)
        reason = _REASON.get(dout.reason, dout.reason); pnl = round(float(dout.profit), 2)
        entry = float(din.price); exitp = float(dout.price)
        r_est = round(pnl / abs(pnl), 2) if pnl else 0.0   # signe seulement si risque inconnu
        # analyse : le contexte d'entrée était-il cohérent avec le résultat ?
        note = ""
        if rat:
            side = rat.get("side"); trend = rat.get("trend_h4")
            if side and trend and side == -trend and pnl < 0:
                note = "fade contre-tendance -> perte (cohérent avec le diagnostic)"
            elif side and trend and side == trend and pnl > 0:
                note = "continuation avec la tendance -> gain"
            elif pnl < 0 and reason == "SL":
                note = "SL touché"
        d = {
            "ticket": int(pid), "symbol": dout.symbol, "reason": reason, "pnl": pnl,
            "entry": round(entry, 6), "exit": round(exitp, 6),
            "rationale_entree": rat, "debrief": note or "(contexte d'entrée non journalisé)",
        }
        debriefs.append(d)
        # mémoriser (une seule fois par ticket)
        if int(pid) not in already:
            why = (rat or {}).get("why", f"{dout.symbol} (rationale inconnu)")
            cloe.log_analysis(f"DEBRIEF {why} -> {reason} PnL={pnl} | {d['debrief']}",
                              meta={"kind": "debrief", "ticket": int(pid), "symbol": dout.symbol})
    res = {"generated_at": now.isoformat(), "window_h": hours,
           "n_debriefs": len(debriefs), "n_avec_rationale": sum(1 for d in debriefs if d["rationale_entree"]),
           "debriefs": debriefs[:100]}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()
    res = debrief(args.hours)
    print("=" * 78)
    print(f"  DÉBRIEF PAR POSITION — {args.hours}h ({res['n_debriefs']} clôturées, "
          f"{res['n_avec_rationale']} avec rationale d'entrée journalisé)")
    print("=" * 78)
    for d in res["debriefs"][:20]:
        r = d.get("rationale_entree") or {}
        pil = f"{r.get('n_pillars','?')}p{r.get('pillars','')}" if r else "?"
        print(f"  {d['symbol']:10s} {str(d['reason']):5s} PnL={d['pnl']:>7} | {pil} trend={r.get('trend_h4','?')} "
              f"fond={((r.get('fundamentals') or {}).get('level'))} -> {d['debrief']}")
    print(f"\n→ débriefs persistés : {OUT} (+ mémorisés par Cloe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
