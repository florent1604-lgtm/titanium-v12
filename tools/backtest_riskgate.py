"""tools/backtest_riskgate.py — BACKTEST de validation du RiskGate (Florent 27/07).

« Le moyen d'enrichir le RiskGate reste les backtests MT5. » Ce backtest rejoue l'historique
M15/H4 à travers LE MÊME chemin de décision (decide → RiskGate) et compare deux modes sur les
MÊMES signaux :
  · B (baseline)  : on prend tous les setups agressifs, sizing structure (plus de piliers = plus gros).
  · A (RiskGate)  : filtre tendance + barème de sizing par piliers du RiskGate (plafonne les gros piliers).
On mesure l'espérance PONDÉRÉE PAR LE LOT (proxy € réel) : la correction améliore-t-elle le résultat ?

CAVEATS (honnêteté) : résolution BARRE (pas tick) ; le filtre COÛT/flux du RiskGate utilise les
valeurs COURANTES (pas historiques) → ce backtest valide surtout le SIZING PILIERS + le filtre
TENDANCE (déterministes sur l'historique), pas le filtre coût. Sans frais/slippage détaillés.

Lecture seule. Usage : venv\\Scripts\\python.exe -m tools.backtest_riskgate [--bars 300]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "US500", "BTCUSD", "USDJPY"]
SL_ATR, TP_ATR, HORIZON = 1.5, 2.25, 48        # SL/TP en multiples d'ATR ; horizon de résolution


def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = (h - l).combine((h - pc).abs(), max).combine((l - pc).abs(), max)
    return float(tr.tail(n).mean())


def _simulate(m15, i, side, entry, atr, tp_atr=TP_ATR):
    """Résout SL/TP sur les barres suivantes. R = +tp_atr/SL_ATR si TP, -1 si SL, sinon mark-to-market."""
    sign = 1 if side > 0 else -1
    sl = entry - sign * SL_ATR * atr
    tp = entry + sign * tp_atr * atr
    fwd = m15.iloc[i + 1: i + 1 + HORIZON]
    for _, b in fwd.iterrows():
        hi, lo = float(b["high"]), float(b["low"])
        if side > 0:
            if lo <= sl: return -1.0
            if hi >= tp: return tp_atr / SL_ATR
        else:
            if hi >= sl: return -1.0
            if lo <= tp: return tp_atr / SL_ATR
    if len(fwd):
        return (float(fwd["close"].iloc[-1]) - entry) * sign / (SL_ATR * atr)
    return 0.0


def run(bars: int = 300, tp_atr: float = TP_ATR) -> dict:
    import MetaTrader5 as mt5
    from ingestion.market.mt5_provider import get_ohlcv, ensure_init, mt5_lock
    from fusion.confluence_demo_engine import decide, _aggressive_eligible, _structure_size_factor, _counter_trend_block
    from risk.riskgate import RiskGate
    if not ensure_init():
        raise RuntimeError("MT5 non initialisé.")
    gate = RiskGate()
    modes = {"B_baseline": [], "A_riskgate": []}   # listes de (R_net, size, R_net_weighted)
    now = datetime.now(timezone.utc)

    # COÛT aller-retour par actif (2×spread live, en unités de prix) — le vrai tueur en live.
    sym_cost = {}
    with mt5_lock:
        for sym in SYMBOLS:
            try:
                si = mt5.symbol_info(sym)
                sym_cost[sym] = float((si.spread or 0) * (si.point or 0)) * 2.0 if si else 0.0
            except Exception:
                sym_cost[sym] = 0.0

    for sym in SYMBOLS:
        m15 = get_ohlcv(sym, "M15", bars + HORIZON + 60)
        h4 = get_ohlcv(sym, "H4", 300)
        if m15 is None or h4 is None or len(m15) < 250:
            continue
        start = max(220, len(m15) - bars - HORIZON)
        for i in range(start, len(m15) - HORIZON):
            sub15 = m15.iloc[:i + 1]
            sub4 = h4[h4.index <= m15.index[i]]
            if len(sub4) < 60:
                continue
            try:
                dec, feats = decide(sym, sub15, sub4, ltf_tf="M15", htf_tf="H4",
                                    venue="cfd", now=m15.index[i].to_pydatetime().replace(tzinfo=timezone.utc),
                                    run_emotion=False, freshness_frames={"M15": sub15, "H4": sub4})
            except Exception:
                continue
            aggr = _aggressive_eligible(dec, feats, 2)
            side = int(dec.side or 0) if getattr(dec, "entered", False) else (int((aggr or {}).get("side") or 0) if aggr else 0)
            if side == 0:
                continue
            atr = _atr(sub15)
            if not atr or atr <= 0:
                continue
            entry = float(sub15["close"].iloc[-1])
            npil = (aggr or {}).get("n_pillars") or sum(1 for g in dec.gates if g.passed and g.name != "data_valid")
            R = _simulate(m15, i, side, entry, atr, tp_atr)
            r_unit = SL_ATR * atr
            cost = sym_cost.get(sym, 0.0)
            cost_r = (cost / r_unit) if r_unit else 0.0    # coût exprimé en R
            R_net = R - cost_r                             # les DEUX modes paient le coût
            # B : sizing structure, LOT PLEIN (paie le coût plein)
            szB = _structure_size_factor(npil, 0.0)
            modes["B_baseline"].append((R_net, szB, R_net * szB))
            # A (modèle Florent) : tendance consciente des retournements + LOT ADAPTÉ AU COÛT
            if _counter_trend_block(feats, side, sub4, atr, 0.25):
                continue                                   # contre-tendance sans retournement prédit
            cost_factor = r_unit / (r_unit + 2.0 * cost) if r_unit else 1.0   # coût gros → lot plus petit
            szA = szB * gate.pillar_size(npil) * cost_factor
            modes["A_riskgate"].append((R_net, szA, R_net * szA))

    def _stats(rows):
        if not rows:
            return {"n": 0}
        wins = [r for r in rows if r[0] > 0]; losses = [r for r in rows if r[0] < 0]
        gw = sum(r[2] for r in wins if r[2] > 0); gl = abs(sum(r[2] for r in losses))
        return {"n": len(rows), "winrate": round(100 * len(wins) / len(rows), 1),
                "esp_R": round(sum(r[0] for r in rows) / len(rows), 3),
                "esp_R_ponderee_lot": round(sum(r[2] for r in rows) / len(rows), 3),
                "somme_R_lot": round(sum(r[2] for r in rows), 2),
                "PF": round(gw / gl, 2) if gl else None}
    return {"generated_at": now.isoformat(), "bars": bars, "symbols": SYMBOLS,
            "B_baseline": _stats(modes["B_baseline"]), "A_riskgate": _stats(modes["A_riskgate"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=300)
    ap.add_argument("--tp", type=float, default=None, help="TP en ATR (défaut: balaye plusieurs largeurs)")
    args = ap.parse_args()

    if args.tp is not None:
        res = run(args.bars, args.tp); b, a = res["B_baseline"], res["A_riskgate"]
        print(f"TP={args.tp} ATR (R:R {args.tp/SL_ATR:.1f}) — A: n={a.get('n')} PF={a.get('PF')} "
              f"esp×lot={a.get('esp_R_ponderee_lot')} | B esp×lot={b.get('esp_R_ponderee_lot')}")
        return 0

    print("BALAYAGE de la largeur de cible (coûts réels inclus) — patiente…\n")
    print("=" * 78)
    print(f"  {'TP (ATR)':>9s} {'R:R':>5s} | {'n':>4s} {'winrate':>8s} {'esp.R×lot':>10s} {'PF':>5s}  (mode A, ton modèle)")
    print("-" * 78)
    best = None
    for tp in (2.25, 3.0, 4.5, 6.0, 7.5, 9.0):
        a = run(args.bars, tp)["A_riskgate"]
        if not a.get("n"):
            continue
        val = a["esp_R_ponderee_lot"]
        star = ""
        if best is None or val > best[1]:
            best = (tp, val); star = " ←"
        print(f"  {tp:>9.2f} {tp/SL_ATR:>5.1f} | {a['n']:>4d} {a['winrate']:>7}% {val:>10} {str(a['PF']):>5}{star}")
    print("-" * 78)
    if best:
        print(f"  → MEILLEURE cible : TP={best[0]} ATR (R:R {best[0]/SL_ATR:.1f}), espérance×lot={best[1]}")
        print(f"    Déployer via .env : CONFLUENCE_DEMO_TP_ATR={best[0]}")
    print("\n  ✅ COÛTS RÉELS inclus. ⚠️ résolution barre, slippage non modélisé, échantillon modeste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
