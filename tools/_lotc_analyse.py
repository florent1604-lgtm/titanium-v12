"""Analyse riche du journal Lot C (shadow_divergence). Lecture seule, jetable."""
import json, collections, statistics as st
from datetime import datetime

P = "data/shadow_divergence.ndjson"
rows = []
for l in open(P, encoding="utf-8"):
    l = l.strip()
    if not l:
        continue
    try:
        rows.append(json.loads(l))
    except Exception:
        pass

n = len(rows)
print("=" * 66)
print(f"  LOT C — ANALYSE APPROFONDIE ({n} observations)")
print("=" * 66)
if not n:
    raise SystemExit

ts = [r["ts"] for r in rows if r.get("ts")]
t0, t1 = min(ts), max(ts)
dur = datetime.fromisoformat(t1) - datetime.fromisoformat(t0)
mins = max(dur.total_seconds() / 60, 1e-9)
print(f"Fenetre   : {t0[11:19]} -> {t1[11:19]}  ({dur})")
print(f"Cadence   : {n/mins:.1f} obs/min")
print()

# Par symbole : sens, score min/max/moyen, seuil, distance au seuil
print("--- Par symbole : scores vs seuil d'emission ---")
by_sym = collections.defaultdict(list)
for r in rows:
    by_sym[r.get("symbol")].append(r)
for sym, rs in sorted(by_sym.items(), key=lambda kv: -len(kv[1])):
    scores = [r.get("effective_score") or 0 for r in rs]
    smins = [r.get("score_min") for r in rs if r.get("score_min") is not None]
    seuil = smins[-1] if smins else "?"
    achat = sum(1 for r in rs if str(r.get("side")).upper() in ("ACHAT", "BUY", "LONG"))
    vente = sum(1 for r in rs if str(r.get("side")).upper() in ("VENTE", "SELL", "SHORT"))
    print(f"  {sym:12s} n={len(rs):4d} | side ACHAT={achat} VENTE={vente} | "
          f"score min={min(scores)} max={max(scores)} moy={st.mean(scores):.2f} | seuil emission={seuil}")

print()
print("--- Distribution des scores effectifs (tous symboles) ---")
hist = collections.Counter(r.get("effective_score") or 0 for r in rows)
for score in sorted(hist):
    bar = "#" * min(50, hist[score])
    print(f"  score {score:>3} : {hist[score]:5d}  {bar}")

print()
print("--- Verdict cerveau : brain_allow / brain_side / conviction ---")
allow = collections.Counter(bool(r.get("brain_allow")) for r in rows)
bside = collections.Counter(r.get("brain_side") for r in rows)
conv = collections.Counter(round(r.get("brain_conviction") or 0.0, 2) for r in rows)
print(f"  brain_allow : {dict(allow)}")
print(f"  brain_side  : {dict(bside)}")
print(f"  conviction  : {dict(conv)}")

print()
print("--- Toutes les raisons rencontrees (reason_codes[0]) ---")
rc = collections.Counter((r.get("reason_codes") or ["?"])[0] for r in rows)
for k, v in rc.most_common():
    print(f"  {k:26s} {v:5d}")

# Y a-t-il eu le moindre score >= seuil (donc un signal EMIS) ?
emitted = [r for r in rows if r.get("emitted")]
near = [r for r in rows if r.get("score_min") and (r.get("effective_score") or 0) >= (r["score_min"] - 1)]
print()
print(f">>> Signaux EMIS reels        : {len(emitted)}")
print(f">>> Sondes a <=1 pt du seuil  : {len(near)}  (proximite d'un vrai signal)")
