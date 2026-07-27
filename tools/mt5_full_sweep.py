"""tools/mt5_full_sweep.py — BALAYAGE COMPLET MT5 (Florent 25/07).

« Il manque beaucoup d'actifs sur les 149 à analyser, je n'en vois que 24. »

Le moteur démo tourne sur un univers CODÉ EN DUR (CONFLUENCE_DEMO_SYMBOLS +
CONFLUENCE_CRYPTO_SYMBOLS ≈ 27) avec rotation par lots → à un instant T le
dashboard n'en montre qu'une tranche. Cet outil, lui, énumère TOUT l'univers
tradable de MT5 (list_universe, ~141 actifs hors actions) et applique le MÊME
moteur de confluence (decide, M15/H4, mode EXPLORE) sur CHACUN, puis classe les
MEILLEURES opportunités du moment :

  - verdict ENTER (setup complet) d'abord,
  - puis les setups STRUCTURÉS (piliers en place ≥ seuil agressif) mais incomplets,
  - triés par nombre de piliers + côté.

Lecture seule (données MT5 uniquement, aucun ordre). Écrit data/mt5_sweep.json.

Usage :
  venv\\Scripts\\python.exe -m tools.mt5_full_sweep
  venv\\Scripts\\python.exe -m tools.mt5_full_sweep --top 40 --ltf M15 --htf H4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Console cp1252 → forcer utf-8 pour les glyphes (─, ▲, …).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "data" / "mt5_sweep.json"


def _n_pillars(decision) -> tuple[int, list[str]]:
    """Piliers de confluence RÉELLEMENT en place (mêmes gates que le moteur démo,
    hors la porte technique data_valid)."""
    passed = [g.name for g in decision.gates if g.passed and g.name != "data_valid"]
    return len(passed), passed


def sweep(ltf: str = "M15", htf: str = "H4", n_bars: int = 300,
          aggressive_min: int = 3) -> dict:
    from tools.asset_optimizer import list_universe
    from data.mt5_provider import get_ohlcv, ensure_init
    from core.confluence_demo_engine import decide, _aggressive_eligible
    import core.confluence_adapter as ca

    if not ensure_init():
        raise RuntimeError("MT5_INIT_FAILED — le terminal MetaTrader5 est-il ouvert ?")

    uni = list_universe()
    if not uni:
        raise RuntimeError("UNIVERSE_EMPTY — aucun symbole retourné par MT5.")

    tfs = ca.freshness_timeframes(ltf, htf)
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    t0 = time.monotonic()

    for i, item in enumerate(uni, 1):
        sym = item["symbol"]
        try:
            frames = {}
            for tf in tfs:
                frames[tf] = get_ohlcv(sym, tf, n_bars)
            df_ltf = frames.get(ltf)
            df_htf = frames.get(htf)
            # venue=cfd : source MT5 pure ; run_emotion=False → balayage rapide (le
            # timing émotionnel ne change pas la STRUCTURE des piliers).
            decision, feats = decide(sym, df_ltf, df_htf, ltf_tf=ltf, htf_tf=htf,
                                     venue="cfd", now=now, run_emotion=False,
                                     freshness_frames=frames)
            n_pil, pillars = _n_pillars(decision)
            aggr = _aggressive_eligible(decision, feats, aggressive_min)
            price = None
            try:
                if df_ltf is not None and len(df_ltf):
                    price = float(df_ltf["close"].iloc[-1])
            except Exception:
                price = None
            rows.append({
                "symbol": sym, "category": item.get("category"),
                "spread_bps": item.get("spread_bps"), "swap_bps_day": item.get("swap_bps_day"),
                "verdict": decision.verdict, "side": decision.side, "code": decision.code,
                "n_pillars": n_pil, "pillars": pillars,
                "structured": bool(aggr), "struct_side": (aggr or {}).get("side"),
                "data_valid": bool(feats.get("data_valid")),
                "reason": str(feats.get("reason") or ""),
                "price": price,
            })
        except Exception as exc:  # fail-safe : un actif ne casse pas le balayage
            rows.append({"symbol": sym, "error": repr(exc)})
        if i % 20 == 0:
            print(f"  …{i}/{len(uni)} balayés ({time.monotonic()-t0:.0f}s)", flush=True)

    # Score d'opportunité : ENTER >> structuré >> reste ; puis nb de piliers.
    def _rank_key(r):
        v = 3 if r.get("verdict") == "ENTER" else (2 if r.get("structured") else 1)
        return (v, r.get("n_pillars", 0))
    scored = [r for r in rows if "error" not in r]
    scored.sort(key=_rank_key, reverse=True)

    enter = [r for r in scored if r.get("verdict") == "ENTER"]
    structured = [r for r in scored if r.get("verdict") != "ENTER" and r.get("structured")]
    errors = [r for r in rows if "error" in r]

    return {
        "generated_at": now.isoformat(),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "ltf": ltf, "htf": htf, "aggressive_min": aggressive_min,
        "universe_size": len(uni), "analysed": len(scored), "errors": len(errors),
        "n_enter": len(enter), "n_structured": len(structured),
        "ranking": scored,
        "error_symbols": [r["symbol"] for r in errors],
    }


def _fmt_row(r: dict) -> str:
    side = {1: "▲ LONG", -1: "▼ SHORT", 0: "· flat"}.get(r.get("side") or 0, "·")
    if r.get("verdict") != "ENTER" and r.get("structured"):
        ss = r.get("struct_side")
        side = {1: "▲ long?", -1: "▼ short?"}.get(ss or 0, side)
    tag = "ENTER " if r.get("verdict") == "ENTER" else ("STRUCT" if r.get("structured") else "      ")
    pil = "●" * r.get("n_pillars", 0) + "○" * (5 - min(5, r.get("n_pillars", 0)))
    return (f"  {tag} {r['symbol']:>12s} {str(r.get('category') or ''):<10s} "
            f"{pil} {r.get('n_pillars',0)}/5  {side:<8s} "
            f"spread~{r.get('spread_bps','?')}bps  [{r.get('code','')}]")


def main() -> int:
    ap = argparse.ArgumentParser(description="Balayage complet MT5 — meilleures opportunités de confluence.")
    ap.add_argument("--ltf", default="M15")
    ap.add_argument("--htf", default="H4")
    ap.add_argument("--bars", type=int, default=300)
    ap.add_argument("--aggressive-min", type=int, default=3)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    print("=" * 78)
    print(f"  BALAYAGE COMPLET MT5 — confluence {args.ltf}/{args.htf} (mode EXPLORE)")
    print("=" * 78)
    res = sweep(args.ltf, args.htf, args.bars, args.aggressive_min)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nUnivers MT5 = {res['universe_size']} actifs | analysés={res['analysed']} "
          f"| erreurs={res['errors']} | {res['elapsed_s']}s")
    print(f"→ ENTER (setup complet) : {res['n_enter']}   |   STRUCTURÉS (≥{args.aggressive_min} piliers) : {res['n_structured']}\n")

    enter = [r for r in res["ranking"] if r.get("verdict") == "ENTER"]
    struct = [r for r in res["ranking"] if r.get("verdict") != "ENTER" and r.get("structured")]

    if enter:
        print("── SETUPS COMPLETS (ENTER) ──────────────────────────────────────────────")
        for r in enter:
            print(_fmt_row(r))
    if struct:
        print("\n── SETUPS STRUCTURÉS (piliers en place, entrée à surveiller) ────────────")
        for r in struct[:args.top]:
            print(_fmt_row(r))
    if not enter and not struct:
        print("Aucun setup complet ni structuré à l'instant — top piliers :")
        for r in res["ranking"][:args.top]:
            print(_fmt_row(r))

    print(f"\n→ balayage complet persisté : {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
