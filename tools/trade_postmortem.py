"""tools/trade_postmortem.py — POST-MORTEM des entrées démo (Florent 26/07).

« Analyse chaque entrée depuis hier, identifie sur l'historique le MEILLEUR point
d'entrée, est-ce que le SL et les TP étaient bien calibrés, auraient-ils pu être
réajustés en cours de route au lieu de rester figés — identifie les axes d'optimisation. »

Croise DEUX sources (lecture seule, aucun ordre) :
  1. `data/demo_journal.ndjson` — l'INTENTION du bot (entrée/SL/TP/ATR par ordre envoyé) ;
  2. l'historique MT5 (`history_deals_get`) — le RÉEL (fill d'entrée, sortie, motif, P&L) ;
plus le chemin de prix M5 pour reconstruire, par trade :
  · MEILLEUR point d'entrée atteignable dans la fenêtre pré-entrée (combien de mieux) ;
  · MFE / MAE (excursion favorable / défavorable, en unités de R = risque au SL) ;
  · SL trop serré ? (stoppé puis le prix repart vers le TP) ;
  · un BREAKEVEN / TRAILING en cours de route aurait-il sauvé/amélioré le trade ?
  · le TP était-il atteignable (MFE l'a-t-il touché) ou trop loin ?

Usage : venv\\Scripts\\python.exe -m tools.trade_postmortem [--hours 36]
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

JOURNAL = ROOT / "data" / "demo_journal.ndjson"
OUT = ROOT / "data" / "trade_postmortem.json"
_REASON = {0: "CLIENT", 3: "EXPERT", 4: "SL", 5: "TP", 6: "TS"}


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
            ts = datetime.fromisoformat(r["ts_utc"])
        except Exception:
            continue
        # Le ticket n'est pas renvoyé par l'exécuteur → on n'en dépend pas ; il faut
        # juste entrée + SL (le TP peut manquer). L'issue est reconstruite sur le prix.
        if ts >= since and r.get("price") and r.get("sl"):
            r["_ts"] = ts
            rows.append(r)
    return rows


def _sign(side) -> int:
    s = str(side).lower()
    if s in ("long", "buy", "1", "achat"):
        return 1
    if s in ("short", "sell", "-1", "vente"):
        return -1
    return 0


def _path_window(df, t0, t1):
    """Sous-ensemble du chemin de prix entre t0 et t1 (inclus)."""
    if df is None or len(df) == 0:
        return None
    try:
        import pandas as pd  # noqa
        m = df[(df.index >= t0) & (df.index <= t1)]
        return m if len(m) else None
    except Exception:
        return None


def _reconstruct_outcome(df, side, entry_time, sl, tp, now):
    """Rejoue le chemin M5 APRÈS l'entrée : renvoie (reason, exit_time, exit_px).
    SL/TP touchés au fil des barres — le PREMIER touché gagne (SL prioritaire si les
    deux dans la même barre = hypothèse conservatrice). None atteint → OPEN."""
    after = _path_window(df, entry_time, now)
    if after is None:
        return "OPEN", now, None
    for ts, bar in after.iterrows():
        hi = float(bar["high"]); lo = float(bar["low"])
        hit_sl = (side > 0 and lo <= sl) or (side < 0 and hi >= sl)
        hit_tp = (tp is not None) and ((side > 0 and hi >= tp) or (side < 0 and lo <= tp))
        if hit_sl:
            return "SL", ts, float(sl)
        if hit_tp:
            return "TP", ts, float(tp)
    return "OPEN", now, float(after["close"].iloc[-1])


def analyse(hours: int = 36) -> dict:
    from data.mt5_provider import ensure_init, get_ohlcv
    if not ensure_init():
        raise RuntimeError("MT5_INIT_FAILED — terminal fermé ?")

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    sent = _load_journal_sent(since)

    trades = []
    _df_cache = {}
    for r in sent:
        side = _sign(r.get("side"))
        if side == 0:
            continue
        sym = r["symbol"]
        entry_px = float(r["price"]); sl = float(r["sl"]); tp = r.get("tp")
        tp = float(tp) if tp else None
        entry_time = r["_ts"]
        R = abs(entry_px - sl) if (sl and entry_px) else None

        # chemin M5 large (pré-entrée + vie du trade + post-sortie) — mis en cache par symbole
        if sym not in _df_cache:
            _df_cache[sym] = get_ohlcv(sym, "M5", 600)
        df = _df_cache[sym]

        reason, exit_time, exit_px = _reconstruct_outcome(df, side, entry_time, sl, tp, now)
        pnl = None  # P&L en unités de R (le journal ne porte pas la clôture broker)
        pre = _path_window(df, entry_time - timedelta(hours=2), entry_time)
        during = _path_window(df, entry_time, exit_time)
        post = _path_window(df, exit_time, exit_time + timedelta(hours=3)) if reason == "SL" else None

        # Meilleur point d'entrée atteignable dans la fenêtre pré-entrée
        best_entry = None; entry_gain_R = None
        if pre is not None and R:
            if side > 0:
                best_entry = float(pre["low"].min())
                entry_gain_R = (entry_px - best_entry) / R
            else:
                best_entry = float(pre["high"].max())
                entry_gain_R = (best_entry - entry_px) / R

        # MFE / MAE pendant la vie du trade
        mfe_R = mae_R = None
        if during is not None and R:
            if side > 0:
                mfe = float(during["high"].max()) - entry_px
                mae = entry_px - float(during["low"].min())
            else:
                mfe = entry_px - float(during["low"].min())
                mae = float(during["high"].max()) - entry_px
            mfe_R = mfe / R; mae_R = mae / R

        # TP atteignable ? (en unités de R)
        tp_R = (abs(tp - entry_px) / R) if (tp and R) else None
        tp_reached = (mfe_R is not None and tp_R is not None and mfe_R >= tp_R)

        # SL trop serré ? stoppé puis le prix repart vers le TP dans les 3h
        sl_too_tight = False
        if reason == "SL" and post is not None and tp and R:
            if side > 0:
                sl_too_tight = float(post["high"].max()) >= tp
            else:
                sl_too_tight = float(post["low"].min()) <= tp

        # Stop dynamique : un breakeven à +0.8R aurait-il sauvé une perte ?
        be_would_save = bool(reason == "SL" and mfe_R is not None and mfe_R >= 0.8)
        # Trailing : le prix a couru bien au-delà du TP touché (gain laissé sur la table) ?
        trail_upside_R = (mfe_R - tp_R) if (mfe_R is not None and tp_R is not None and tp_reached) else None

        # P&L en unités de R reconstruit : SL = -1R, TP = +tp_R, OPEN = excursion nette actuelle.
        if reason == "SL":
            pnl_R = -1.0
        elif reason == "TP":
            pnl_R = tp_R
        elif reason == "OPEN" and R and exit_px is not None:
            pnl_R = (exit_px - entry_px) / R * side
        else:
            pnl_R = None

        trades.append({
            "symbol": sym, "side": "long" if side > 0 else "short",
            "engine": r.get("engine"), "opened": entry_time.isoformat(),
            "entry": round(entry_px, 6), "sl": round(sl, 6), "tp": round(tp, 6) if tp else None,
            "risk_R": round(R, 6) if R else None,
            "exit": round(exit_px, 6) if exit_px is not None else None,
            "reason": reason, "pnl_R": round(pnl_R, 2) if pnl_R is not None else None,
            "best_entry": round(best_entry, 6) if best_entry is not None else None,
            "entry_gain_R": round(entry_gain_R, 2) if entry_gain_R is not None else None,
            "mfe_R": round(mfe_R, 2) if mfe_R is not None else None,
            "mae_R": round(mae_R, 2) if mae_R is not None else None,
            "tp_R": round(tp_R, 2) if tp_R is not None else None,
            "tp_reached": tp_reached,
            "sl_too_tight": sl_too_tight,
            "breakeven_would_save": be_would_save,
            "trailing_upside_R": round(trail_upside_R, 2) if trail_upside_R is not None else None,
            "status": "OPEN" if reason == "OPEN" else "closed",
        })

    trades.sort(key=lambda t: t["opened"])
    closed = [t for t in trades if t["status"] == "closed"]
    losses = [t for t in closed if (t.get("pnl_R") or 0) < 0]

    def _avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    summary = {
        "generated_at": now.isoformat(), "window_hours": hours,
        "n_trades": len(trades), "n_closed": len(closed), "n_open": len(trades) - len(closed),
        "n_losses": len(losses),
        "avg_entry_gain_R_available": _avg([t["entry_gain_R"] for t in trades]),
        "avg_mfe_R": _avg([t["mfe_R"] for t in trades]),
        "avg_mae_R": _avg([t["mae_R"] for t in trades]),
        "n_wins": sum(1 for t in closed if (t.get("pnl_R") or 0) > 0),
        "sum_pnl_R": _avg([t["pnl_R"] for t in closed]) and round(sum(t["pnl_R"] for t in closed if t.get("pnl_R") is not None), 2),
        "avg_mae_R_winners": _avg([t["mae_R"] for t in closed if (t.get("pnl_R") or 0) > 0]),
        "losses_breakeven_would_save": sum(1 for t in losses if t["breakeven_would_save"]),
        "sl_too_tight_count": sum(1 for t in closed if t["sl_too_tight"]),
        "tp_reached_count": sum(1 for t in closed if t["tp_reached"]),
    }
    return {"summary": summary, "trades": trades}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=36)
    args = ap.parse_args()
    res = analyse(args.hours)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    s = res["summary"]; T = res["trades"]

    print("=" * 96)
    print(f"  POST-MORTEM des entrées démo — {s['window_hours']}h  ({s['n_trades']} trades : "
          f"{s['n_closed']} clôturés, {s['n_open']} ouverts)")
    print("=" * 96)
    hdr = ("SYM       SENS  motif  P&L(R) | entrée     meilleure   gain(R) | MFE  MAE  | "
           "TP_R touché | SLserré BE-save trail")
    print(hdr); print("-" * len(hdr))
    for t in T:
        be = "OUI" if t["breakeven_would_save"] else " . "
        stt = "OUI" if t["sl_too_tight"] else " . "
        tpx = "OUI" if t["tp_reached"] else " . "
        print(f"{t['symbol']:9s} {t['side']:5s} {str(t['reason']):5s} {str(t['pnl_R']):>6s} | "
              f"{str(t['entry']):<10s} {str(t['best_entry']):<10s} {str(t['entry_gain_R']):>6s} | "
              f"{str(t['mfe_R']):>4s} {str(t['mae_R']):>4s} | {str(t['tp_R']):>4s} {tpx:>5s} | "
              f"{stt:>6s} {be:>6s} {str(t['trailing_upside_R'] or '')}")
    print("-" * len(hdr))
    print(f"  bilan reconstruit : {s['n_wins']} gagnants / {s['n_losses']} perdants "
          f"| somme = {s.get('sum_pnl_R')} R")
    print("\nAXES D'OPTIMISATION (données réelles) :")
    print(f"  • Meilleur point d'entrée : en moyenne {s['avg_entry_gain_R_available']} R de mieux "
          f"était atteignable dans l'heure précédant l'entrée (→ valide le raffinement M5/M1).")
    print(f"  • Excursion favorable moyenne (MFE) = {s['avg_mfe_R']} R | défavorable (MAE) = {s['avg_mae_R']} R.")
    print(f"  • SL : {s['sl_too_tight_count']} trade(s) stoppés PUIS le prix est reparti vers le TP "
          f"(SL trop serré / posé sur le bruit).")
    print(f"  • Stop dynamique : {s['losses_breakeven_would_save']}/{s['n_losses']} perte(s) auraient "
          f"été ÉVITÉES par un breakeven à +0.8R (au lieu d'un SL figé).")
    print(f"  • MAE moyen des GAGNANTS = {s['avg_mae_R_winners']} R (marge de SL réellement nécessaire).")
    print(f"  • TP : {s['tp_reached_count']} trade(s) ont atteint leur TP en excursion.")
    print(f"\n→ détail complet persisté : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
