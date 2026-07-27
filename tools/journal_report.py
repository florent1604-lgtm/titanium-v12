"""tools/journal_report.py — DÉPOUILLEMENT du journal non censuré (Florent 27/07).

Le journal unifié (core/journal, réorg Phase 1) enregistre signal / decision / fill / GHOST.
Ce rapport en tire la valeur clé qu'aucun autre outil n'a : le **coût d'opportunité des REFUS**.
Pour chaque signal refusé (ghost = trade fantôme), on rejoue le prix M5 APRÈS le refus et on
mesure ce que le trade aurait donné — regroupé PAR MOTIF de refus. Ça répond à : « est-ce
qu'un veto (contre-tendance, brain, master, coût…) coupe des trades qui auraient gagné ? »

Lecture seule (journal local + données MT5). Écrit data/journal_report.json.
Usage : venv\\Scripts\\python.exe -m tools.journal_report [--horizon-bars 24]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "journal_report.json"


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _ghost_counterfactual(ghosts, horizon_bars: int):
    """Pour chaque refus directionnel, rejoue M5 après le refus → rendement signé par le sens
    voulu. Agrège par motif : n, % favorable, rendement moyen, MFE/MAE moyens (%)."""
    from ingestion.market.mt5_provider import get_ohlcv
    by_symbol = {}
    per_reason = defaultdict(lambda: {"n": 0, "fav": 0, "ret": [], "mfe": [], "mae": []})
    detail = []
    skipped_outliers = 0
    _OUTLIER_PCT = 50.0    # |rendement 2h| > 50% = artefact d'échelle de prix, exclu
    for g in ghosts:
        p = g["payload"]; sym = g.get("symbol"); side = int(p.get("side") or 0)
        entry = p.get("price"); reason = p.get("reason") or "?"
        if not sym or side == 0 or not entry:
            continue
        try:
            ts = datetime.fromisoformat(g["ts_utc"])
        except Exception:
            continue
        if sym not in by_symbol:
            by_symbol[sym] = get_ohlcv(sym, "M5", 600)
        df = by_symbol[sym]
        if df is None or len(df) == 0:
            continue
        fwd = df[df.index >= ts]
        if len(fwd) < 2:
            continue
        fwd = fwd.iloc[:horizon_bars]
        entry = float(entry)
        close_h = float(fwd["close"].iloc[-1])
        ret = (close_h - entry) / entry * side * 100.0            # rendement signé (%)
        if side > 0:
            mfe = (float(fwd["high"].max()) - entry) / entry * 100.0
            mae = (entry - float(fwd["low"].min())) / entry * 100.0
        else:
            mfe = (entry - float(fwd["low"].min())) / entry * 100.0
            mae = (float(fwd["high"].max()) - entry) / entry * 100.0
        if abs(ret) > _OUTLIER_PCT or abs(mfe) > _OUTLIER_PCT or abs(mae) > _OUTLIER_PCT:
            skipped_outliers += 1           # artefact d'échelle de prix (symbole mal apparié)
            continue
        slot = per_reason[reason]
        slot["n"] += 1; slot["fav"] += 1 if ret > 0 else 0
        slot["ret"].append(ret); slot["mfe"].append(mfe); slot["mae"].append(mae)
        detail.append({"symbol": sym, "side": side, "reason": reason,
                       "ret_pct": round(ret, 3), "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)})
    rows = []
    for reason, s in per_reason.items():
        rows.append({"reason": reason, "n": s["n"],
                     "would_win_pct": round(100 * s["fav"] / s["n"], 1) if s["n"] else None,
                     "avg_ret_pct": _avg(s["ret"]), "avg_mfe_pct": _avg(s["mfe"]),
                     "avg_mae_pct": _avg(s["mae"])})
    rows.sort(key=lambda r: (r["avg_ret_pct"] or -99), reverse=True)
    return rows, detail, skipped_outliers


def analyse(horizon_bars: int = 24, since_hours: int = 48) -> dict:
    from core.journal import get_journal
    j = get_journal()
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    decisions = j.read(kind="decision", since_iso=since_iso, limit=100000)
    ghosts = j.read(kind="ghost", since_iso=since_iso, limit=100000)
    fills = j.read(kind="fill", since_iso=since_iso, limit=100000)

    from collections import Counter
    verdicts = Counter(d["payload"].get("decision") for d in decisions)
    reasons = Counter(d["payload"].get("reason") for d in decisions)

    cf_rows, cf_detail, skipped = _ghost_counterfactual(ghosts, horizon_bars)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_hours": since_hours, "horizon_bars": horizon_bars,
        "counts": j.counts_by_kind(),
        "verdicts": dict(verdicts), "top_reasons": dict(reasons.most_common(10)),
        "n_fills": len(fills), "outliers_exclus": skipped,
        "refus_counterfactual": cf_rows, "refus_detail": cf_detail[:50],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-bars", type=int, default=24)   # 24 barres M5 = 2h
    ap.add_argument("--since-hours", type=int, default=48)
    args = ap.parse_args()
    res = analyse(args.horizon_bars, args.since_hours)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    print("=" * 78)
    print(f"  JOURNAL NON CENSURÉ — dépouillement ({args.since_hours}h, horizon {args.horizon_bars}×M5)")
    print("=" * 78)
    print(f"volumes : {res['counts']}")
    print(f"verdicts : {res['verdicts']}")
    print(f"top motifs : {res['top_reasons']}")
    print(f"\n── COÛT D'OPPORTUNITÉ DES REFUS (fantômes rejoués, {res.get('outliers_exclus',0)} aberrants exclus) ──")
    print(f"  {'motif':26s} {'n':>3s} {'gagnant%':>8s} {'ret.moy%':>9s} {'MFE%':>7s} {'MAE%':>7s}")
    if not res["refus_counterfactual"]:
        print("  (pas encore assez de fantômes rejouables — laisser tourner)")
    for r in res["refus_counterfactual"]:
        print(f"  {str(r['reason']):26s} {r['n']:>3d} {str(r['would_win_pct']):>7s}% "
              f"{str(r['avg_ret_pct']):>9s} {str(r['avg_mfe_pct']):>7s} {str(r['avg_mae_pct']):>7s}")
    print("\n  Lecture : ret.moy > 0 = le veto a coupé un mouvement FAVORABLE (coût d'opportunité) ;")
    print("            ret.moy < 0 = le veto a bien PROTÉGÉ. n faible = signal encore fragile.")
    print(f"\n→ rapport persisté : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
