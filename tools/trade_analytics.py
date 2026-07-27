"""tools/trade_analytics.py — ANALYTIQUE consolidée des trades démo (Florent 26/07).

« Étendre les outils d'abord : consolider les DONNÉES avant l'IA qui les exploite. »

Relie chaque DÉCISION (data/demo_journal.ndjson) à son RÉSULTAT RÉEL (historique MT5 :
SL/TP, P&L, durée), enrichit de CONTEXTE (moteur, sens, structure, catégorie d'actif,
heure) et agrège la performance PAR CONTEXTE (winrate, espérance en R, profit factor).

C'est la table « ce qui marche vraiment, et dans quel contexte » — le socle qu'une future
boucle d'apprentissage / IA locale exploitera. Complémentaire de `trade_postmortem`
(lui simule le MEILLEUR point d'entrée / stop dynamique sur le CHEMIN de prix).

Lecture seule (aucun ordre). Écrit data/trade_analytics.json.
Usage : venv\\Scripts\\python.exe -m tools.trade_analytics [--days 3]
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

JOURNAL = ROOT / "data" / "demo_journal.ndjson"
OUT = ROOT / "data" / "trade_analytics.json"
_REASON = {0: "MANUAL", 3: "EXPERT", 4: "SL", 5: "TP", 6: "TS"}
_CRYPTO = {"BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "SOL", "DOGE", "BNB"}


def _category(sym: str) -> str:
    s = str(sym or "").upper()
    if any(s.startswith(c) and s.endswith("USD") for c in _CRYPTO):
        return "crypto"
    if s.startswith(("XAU", "XAG", "XPT", "XPD")):
        return "metals"
    if s.endswith(".FS"):
        return "futures"
    if len(s) == 6 and s.isalpha():
        return "fx"
    return "index/cash"


def _structure(risk_money) -> str:
    """Proxy de structure = tranche de taille (le lot scale sur la qualité des piliers)."""
    try:
        r = float(risk_money)
    except (TypeError, ValueError):
        return "?"
    if r <= 0:
        return "0"
    if r < 8:
        return "S(~2p)"
    if r < 20:
        return "M(~3p)"
    if r < 45:
        return "L(~4p)"
    return "XL(~5p)"


def _hour_bucket(ts_iso: str) -> str:
    try:
        h = datetime.fromisoformat(ts_iso).astimezone(timezone.utc).hour
    except Exception:
        return "?"
    if 0 <= h < 7:
        return "Asie(00-07)"
    if 7 <= h < 12:
        return "Londres(07-12)"
    if 12 <= h < 17:
        return "NY(12-17)"
    return "Soir(17-24)"


def _sign(side) -> int:
    s = str(side).lower()
    return 1 if s in ("long", "buy", "achat", "1") else (-1 if s in ("short", "sell", "vente", "-1") else 0)


def _load_journal_sent(since):
    rows = []
    if not JOURNAL.exists():
        return rows
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("sent"):
            continue
        try:
            if datetime.fromisoformat(r["ts_utc"]) >= since:
                rows.append(r)
        except Exception:
            continue
    return rows


def _pillars(comment: str):
    c = str(comment or "")
    if "|p" in c:
        try:
            return int(c.rsplit("|p", 1)[1][:1])
        except (ValueError, IndexError):
            return None
    return None


def _engine_from_comment(comment: str) -> str:
    return "confluence-aggr" if "aggr" in str(comment or "").lower() else "confluence"


def _structure_from_pillars(p) -> str:
    if p is None:
        return "?"
    return {0: "0", 1: "S(1p)", 2: "S(2p)", 3: "M(3p)", 4: "L(4p)", 5: "XL(5p)"}.get(int(p),
            "XL(5p+)" if int(p) > 5 else "?")


def build_trades(closed_by_pos, open_positions):
    """Construit les trades depuis la VÉRITÉ TERRAIN MT5 (une position = un trade, mode
    hedging). Contexte tiré du commentaire d'ouverture (moteur + piliers). R normalisé
    ensuite sur l'unité de risque (perte médiane au SL)."""
    trades = []
    for pid, c in closed_by_pos.items():
        p = c["pillars"]
        trades.append({
            "pos_id": pid, "symbol": c["symbol"], "category": _category(c["symbol"]),
            "engine": _engine_from_comment(c["in_comment"]),
            "side": "long" if c["side"] > 0 else "short",
            "pillars": p, "structure": _structure_from_pillars(p),
            "hour": _hour_bucket(c["entry_time"].isoformat()) if c["entry_time"] else "?",
            "opened": c["entry_time"].isoformat() if c["entry_time"] else None,
            "reason": c["reason"], "pnl": round(c["pnl"], 2), "closed": True, "R": None,
        })
    for p in open_positions:
        pil = _pillars(getattr(p, "comment", ""))
        trades.append({
            "pos_id": p.ticket, "symbol": p.symbol, "category": _category(p.symbol),
            "engine": _engine_from_comment(getattr(p, "comment", "")),
            "side": "long" if int(p.type) == 0 else "short",
            "pillars": pil, "structure": _structure_from_pillars(pil),
            "hour": "?", "opened": None, "reason": "OPEN",
            "pnl": round(float(p.profit), 2), "closed": False, "R": None,
        })
    return trades


def _normalise_R(trades):
    """R par trade = P&L / unité de risque (perte médiane des trades SL = ~1R)."""
    sl_losses = sorted(abs(t["pnl"]) for t in trades
                       if t["closed"] and t["reason"] == "SL" and t["pnl"] < 0)
    if sl_losses:
        unit = sl_losses[len(sl_losses) // 2]              # médiane
    else:
        closed = [abs(t["pnl"]) for t in trades if t["closed"] and t["pnl"]]
        unit = (sorted(closed)[len(closed) // 2] if closed else 1.0)
    unit = unit or 1.0
    for t in trades:
        if t["pnl"] is not None:
            t["R"] = round(t["pnl"] / unit, 2)
    return round(unit, 2)


def _stats(trades):
    """Stats agrégées d'un groupe de trades CLÔTURÉS. Pur/testable."""
    closed = [t for t in trades if t["closed"] and t["R"] is not None]
    if not closed:
        return {"n": 0}
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] < 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    return {
        "n": len(closed),
        "winrate": round(100 * len(wins) / len(closed), 1),
        "expectancy_R": round(sum(t["R"] for t in closed) / len(closed), 3),
        "sum_pnl": round(sum(t["pnl"] for t in closed), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
    }


def aggregate(trades):
    """Agrège par chaque dimension de contexte. Pur/testable."""
    dims = ["category", "engine", "side", "structure", "hour", "symbol"]
    out = {"overall": _stats(trades)}
    for dim in dims:
        groups = defaultdict(list)
        for t in trades:
            groups[t.get(dim)].append(t)
        rows = [{dim: k, **_stats(v)} for k, v in groups.items()]
        rows = [r for r in rows if r.get("n", 0) > 0]
        rows.sort(key=lambda r: (r.get("expectancy_R") or -9, r["n"]), reverse=True)
        out[dim] = rows
    return out


def analyse(days: int = 3) -> dict:
    import MetaTrader5 as mt5
    from data.mt5_provider import ensure_init, mt5_lock
    if not ensure_init():
        raise RuntimeError("MT5_INIT_FAILED — terminal fermé ?")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    n_sent = len(_load_journal_sent(since))

    with mt5_lock:
        deals = mt5.history_deals_get(since - timedelta(hours=2), now + timedelta(hours=2))
        openpos = list(mt5.positions_get() or [])

    # Deals → position_id → {ouverture IN, clôture OUT}. NOS positions seulement.
    raw = defaultdict(dict)
    for d in (deals or []):
        raw[d.position_id]["in" if d.entry == 0 else "out"] = d
    closed_by_pos = {}
    for pid, pair in raw.items():
        din, dout = pair.get("in"), pair.get("out")
        if not dout or not din:
            continue
        in_comment = str(getattr(din, "comment", "") or "")
        # filtre NOS trades (l'ouverture porte « titanium… » ; magic non exposé sur le deal)
        if not in_comment.startswith("titanium"):
            continue
        closed_by_pos[pid] = {
            "symbol": dout.symbol, "side": 1 if din.type == 0 else -1,
            "entry_price": float(din.price), "in_comment": in_comment,
            "entry_time": datetime.fromtimestamp(din.time, timezone.utc),
            "reason": _REASON.get(dout.reason, dout.reason), "pnl": float(dout.profit),
            "pillars": _pillars(in_comment),
        }
    ours_open = [p for p in openpos if str(getattr(p, "comment", "") or "").startswith("titanium")
                 or int(getattr(p, "magic", 0)) == 500786]

    trades = build_trades(closed_by_pos, ours_open)
    unit_r = _normalise_R(trades)
    agg = aggregate(trades)
    return {"generated_at": now.isoformat(), "window_days": days,
            "n_decisions_sent": n_sent, "n_matched": len(trades), "unit_R_money": unit_r,
            "aggregates": agg, "trades": trades}


def _print_dim(title, rows, key, top=8):
    print(f"\n── {title} " + "─" * max(2, 60 - len(title)))
    print(f"  {'contexte':<16s} {'n':>3s} {'winrate':>8s} {'esp.(R)':>8s} {'PF':>5s} {'P&L':>8s}")
    for r in rows[:top]:
        print(f"  {str(r.get(key)):<16s} {r['n']:>3d} {str(r.get('winrate','')):>7s}% "
              f"{str(r.get('expectancy_R','')):>8s} {str(r.get('profit_factor','')):>5s} "
              f"{str(r.get('sum_pnl','')):>8s}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    args = ap.parse_args()
    res = analyse(args.days)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    a = res["aggregates"]
    o = a["overall"]
    print("=" * 72)
    print(f"  ANALYTIQUE TRADES DÉMO — {res['window_days']}j  ({res['n_matched']} trades reliés "
          f"sur {res['n_decisions_sent']} décisions envoyées)")
    print("=" * 72)
    if o.get("n"):
        print(f"GLOBAL clôturés={o['n']} | winrate={o['winrate']}% | espérance={o['expectancy_R']}R "
              f"| PF={o['profit_factor']} | P&L={o['sum_pnl']}")
    else:
        print("Aucun trade clôturé sur la fenêtre.")
    _print_dim("PAR CATÉGORIE", a["category"], "category")
    _print_dim("PAR MOTEUR", a["engine"], "engine")
    _print_dim("PAR SENS", a["side"], "side")
    _print_dim("PAR STRUCTURE", a["structure"], "structure")
    _print_dim("PAR SESSION", a["hour"], "hour")
    _print_dim("PAR ACTIF (top espérance)", a["symbol"], "symbol", top=12)
    print(f"\n→ analytique persistée : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
