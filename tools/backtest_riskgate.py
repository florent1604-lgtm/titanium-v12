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


def _simulate(m15, i, side, entry, atr):
    """Résout SL/TP sur les barres suivantes. R = +TP_ATR/SL_ATR si TP, -1 si SL, sinon mark-to-market."""
    sign = 1 if side > 0 else -1
    sl = entry - sign * SL_ATR * atr
    tp = entry + sign * TP_ATR * atr
    fwd = m15.iloc[i + 1: i + 1 + HORIZON]
    for _, b in fwd.iterrows():
        hi, lo = float(b["high"]), float(b["low"])
        if side > 0:
            if lo <= sl: return -1.0
            if hi >= tp: return TP_ATR / SL_ATR
        else:
            if hi >= sl: return -1.0
            if lo <= tp: return TP_ATR / SL_ATR
    if len(fwd):
        return (float(fwd["close"].iloc[-1]) - entry) * sign / (SL_ATR * atr)
    return 0.0


def run(bars: int = 300) -> dict:
    from ingestion.market.mt5_provider import get_ohlcv, ensure_init
    from fusion.confluence_demo_engine import decide, _aggressive_eligible, _structure_size_factor, _counter_trend_block
    from risk.riskgate import RiskGate
    if not ensure_init():
        raise RuntimeError("MT5 non initialisé.")
    gate = RiskGate()
    modes = {"B_baseline": [], "A_riskgate": []}   # listes de (R, size, R_weighted)
    now = datetime.now(timezone.utc)

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
            R = _simulate(m15, i, side, entry, atr)
            # B : sizing structure (plus de piliers = plus gros)
            szB = _structure_size_factor(npil, 0.0)
            modes["B_baseline"].append((R, szB, R * szB))
            # A : filtre tendance + barème piliers RiskGate
            if _counter_trend_block(feats, side, sub4, atr, 0.25):
                continue                                   # RiskGate DENY contre-tendance → pas de trade
            szA = szB * gate.pillar_size(npil)
            modes["A_riskgate"].append((R, szA, R * szA))

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
    ap = argparse.ArgumentParser(); ap.add_argument("--bars", type=int, default=300)
    args = ap.parse_args()
    print("Backtest RiskGate (rejeu M15/H4) — patiente…\n")
    res = run(args.bars)
    b, a = res["B_baseline"], res["A_riskgate"]
    print("=" * 74)
    print(f"  BACKTEST RiskGate — {len(res['symbols'])} actifs, {res['bars']} barres/actif")
    print("=" * 74)
    print(f"  {'mode':14s} {'n':>5s} {'winrate':>8s} {'esp.R':>7s} {'esp.R×lot':>10s} {'somme':>8s} {'PF':>5s}")
    for name, s in (("B baseline", b), ("A RiskGate", a)):
        if s.get("n"):
            print(f"  {name:14s} {s['n']:>5d} {s['winrate']:>7}% {s['esp_R']:>7} "
                  f"{s['esp_R_ponderee_lot']:>10} {s['somme_R_lot']:>8} {str(s['PF']):>5}")
    if b.get("n") and a.get("n"):
        d = round((a["esp_R_ponderee_lot"] - b["esp_R_ponderee_lot"]), 3)
        print(f"\n  → La correction RiskGate change l'espérance pondérée-lot de {d:+} R "
              f"({'AMÉLIORE' if d > 0 else 'DÉGRADE' if d < 0 else 'neutre'}).")
    print("\n  ⚠️ résolution barre, sans frais détaillés, filtre coût non rejoué (valide sizing+tendance).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
