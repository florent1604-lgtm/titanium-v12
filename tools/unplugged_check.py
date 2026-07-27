"""tools/unplugged_check.py — TEST DU FIL DÉBRANCHÉ (réorg Phase 4, 27/07/2026).

Invariant central de la vision « IA locale qui DÉCIDE » : le noyau (SMC + géométrie + risque)
doit produire un SIGNAL **et** une décision RiskGate **sans aucune dépendance LLM/réseau**.

Ce script coupe tout enrichissement externe (émotion off, réseau non sollicité) et exécute le
chemin de décision RÉEL sur des données MT5 locales : build_feats → decide() (fusion N3) →
RiskGate.evaluate() (N4). Si les deux produisent une sortie, l'invariant tient.

Lecture seule (données MT5 locales), aucun ordre. N'appelle NI Ollama NI le réseau externe.
Usage : venv\\Scripts\\python.exe -m tools.unplugged_check [SYMBOLE ...]
"""
from __future__ import annotations

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


def _atr(df, n: int = 14) -> float:
    try:
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = (h - l).combine((h - pc).abs(), max).combine((l - pc).abs(), max)
        return float(tr.tail(n).mean())
    except Exception:
        return 0.0


def check(symbols) -> int:
    from ingestion.market.mt5_provider import get_ohlcv, ensure_init
    import fusion.confluence_adapter as ca
    from fusion.confluence_demo_engine import decide
    from core.state_builder import build_system_state
    from risk.riskgate import RiskGate

    if not ensure_init():
        print("MT5 non initialisé — impossible de charger des données locales.")
        return 1

    now = datetime.now(timezone.utc)
    tfs = ca.freshness_timeframes("M15", "H4")
    gate = RiskGate()
    ok_all = True
    print("=" * 78)
    print("  TEST DU FIL DÉBRANCHÉ — noyau de décision SANS LLM ni réseau externe")
    print("=" * 78)
    print(f"  {'ACTIF':10s} {'signal (decide)':22s} {'RiskGate':10s} {'motif':22s}")
    for sym in symbols:
        try:
            frames = {tf: get_ohlcv(sym, tf, 300) for tf in tfs}
            # run_emotion=False : on DÉBRANCHE explicitement l'enrichissement (émotion/LLM/réseau)
            decision, feats = decide(sym, frames.get("M15"), frames.get("H4"),
                                     ltf_tf="M15", htf_tf="H4", venue="cfd", now=now,
                                     run_emotion=False, freshness_frames=frames)
            atr = _atr(frames.get("M15"))
            st = build_system_state(symbol=sym, venue="cfd", ltf="M15", feats=feats,
                                    decision=decision, atr=atr,
                                    price=float(frames["M15"]["close"].iloc[-1]))
            st.risk.equity = 1000.0                      # equity fictive pour le sizing
            d = gate.evaluate(st)
            sig = f"{decision.verdict}/{decision.code}"
            has_signal = bool(decision.verdict) and bool(decision.code)
            has_decision = bool(d.verdict)
            ok_all = ok_all and has_signal and has_decision
            print(f"  {sym:10s} {sig:22s} {d.verdict:10s} {d.reason:22s}")
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            print(f"  {sym:10s} ERREUR: {exc!r}")
    print("-" * 78)
    if ok_all:
        print("  ✅ INVARIANT TENU : signal + décision RiskGate produits SANS LLM ni réseau.")
    else:
        print("  ❌ Un cas n'a pas produit signal+décision — dépendance à investiguer.")
    return 0 if ok_all else 2


def main() -> int:
    syms = sys.argv[1:] or ["EURUSD", "BTCUSD", "XAUUSD", "US500"]
    return check(syms)


if __name__ == "__main__":
    raise SystemExit(main())
