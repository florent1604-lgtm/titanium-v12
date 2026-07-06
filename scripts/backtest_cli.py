"""scripts/backtest_cli.py — Titanium V12 : CLI de backtest walk-forward pour valider un gate.

Avant d'activer un flag qui influe sur le scoring/l'exécution (ex. SPECTRAL_REGIME_FILTER),
ce CLI compare une config baseline (gate off) à la config filtrée (gate on) en walk-forward
70/30 (in-sample / out-of-sample), et REFUSE (exit code 1) si le gate ne dégrade pas le
risque-ajusté au lieu de l'améliorer sur l'out-of-sample.

Stratégie = proxy reversal z-score (PAS le scoring /16 réel — pour valider un gate sur les
vrais signaux, charger signal_history.json et appliquer uniquement le filtre concerné).
Adapté de btc_phase0_2025.py (script prototype de l'utilisateur), généralisé en CLI multi-gate
et branché sur indicators/spectral.py (pas de réimplémentation locale du roofing/autocorr).

Usage :
    python -m scripts.backtest_cli --gate spectral_regime_filter --symbol BTC/USDT --tf 1h --days 365
"""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import aiohttp
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.binance_rest import fetch_klines_history
from indicators.spectral import compute_spectral_features


# ── Stratégie proxy (reversal z-score) ───────────────────────────────────────

def strat(price: np.ndarray, zwin: int = 50, zen: float = 1.5, stop: float = 0.03,
          maxh: int = 60, fee: float = 0.0008) -> List[Tuple[int, float]]:
    """Retourne une liste [(entry_index, pnl_pct)] — proxy générique, pas le scoring /16."""
    n = len(price)
    ma = np.full(n, np.nan)
    sd = np.full(n, np.nan)
    for t in range(zwin, n):
        w = price[t - zwin:t]
        ma[t] = w.mean()
        sd[t] = w.std() + 1e-9
    z = (price - ma) / sd
    trades: List[Tuple[int, float]] = []
    t = zwin
    while t < n - 1:
        if np.isnan(z[t]):
            t += 1
            continue
        side = 1 if z[t] < -zen else (-1 if z[t] > zen else 0)
        if not side:
            t += 1
            continue
        e = t
        ep = price[e]
        xi = None
        for u in range(e + 1, min(e + maxh, n)):
            if (side == 1 and z[u] >= 0) or (side == -1 and z[u] <= 0):
                xi = u
                break
            if side * (price[u] - ep) / ep <= -stop:
                xi = u
                break
        if xi is None:
            xi = min(e + maxh, n - 1)
        trades.append((e, side * (price[xi] - ep) / ep - fee))
        t = xi + 1
    return trades


def metrics(pnl: List[float]) -> Dict[str, float]:
    p = np.array(pnl)
    if not len(p):
        return {"n": 0, "win": 0.0, "pf": float("nan"), "ret": 0.0, "max_dd": 0.0}
    w = p[p > 0].sum()
    l = -p[p < 0].sum()
    eq = np.cumprod(1 + p)
    dd = 1 - eq / np.maximum.accumulate(eq)
    return {
        "n": len(p), "win": 100 * (p > 0).mean(),
        "pf": (w / l if l > 0 else float("inf")),
        "ret": 100 * p.sum(), "max_dd": 100 * dd.max() if len(dd) else 0.0,
    }


def equity_curve(pnl: List[float], start: float = 1000.0) -> List[float]:
    eq = [start]
    for p in pnl:
        eq.append(eq[-1] * (1 + p))
    return eq


# ── Gates ─────────────────────────────────────────────────────────────────────

def _gate_spectral_regime_filter(
    price: np.ndarray, trades: List[Tuple[int, float]], window: int,
) -> List[Tuple[int, float]]:
    """Ne garde que les trades dont l'entrée tombe pendant un cycle net (has_cycle=True),
    exactement le signal utilisé par SPECTRAL_REGIME_FILTER (indicators.spectral)."""
    kept = []
    for e, pnl in trades:
        if e < window:
            continue
        try:
            feats = compute_spectral_features(price[e - window:e])
        except Exception:
            continue
        if feats.has_cycle:
            kept.append((e, pnl))
    return kept


GATES: Dict[str, Callable[[np.ndarray, List[Tuple[int, float]], int], List[Tuple[int, float]]]] = {
    "spectral_regime_filter": _gate_spectral_regime_filter,
}


# ── Walk-forward ──────────────────────────────────────────────────────────────

def _print_row(label: str, m: Dict[str, float]) -> None:
    pf = m["pf"]
    pf_s = f"{pf:.2f}" if np.isfinite(pf) else "inf"
    print(f"  {label:<22}n={m['n']:<6}win={m['win']:>6.1f}%  PF={pf_s:>6}  "
          f"ret={m['ret']:>8.1f}%  maxDD={m['max_dd']:>5.1f}%")


def run_gate_validation(
    close: np.ndarray, gate_name: str, window: int, split_ratio: float = 0.70,
) -> bool:
    """Walk-forward 70/30 : le gate n'est validé QUE s'il améliore le PF out-of-sample.

    Retourne True si le gate est validé (peut être activé), False sinon.
    """
    gate_fn = GATES[gate_name]
    split = int(len(close) * split_ratio)
    segments = {"IN-SAMPLE (70%)": close[:split], "OUT-OF-SAMPLE (30%)": close[split:]}

    oos_baseline_pf = oos_filtered_pf = float("nan")
    for label, seg in segments.items():
        if len(seg) < window * 2:
            print(f"\n{label} : segment trop court ({len(seg)} barres) — ignoré")
            continue
        trades = strat(seg)
        baseline = [p for _, p in trades]
        filtered = [p for _, p in gate_fn(seg, trades, window)]
        m_base = metrics(baseline)
        m_filt = metrics(filtered)
        print(f"\n{label} — {len(seg)} bougies")
        _print_row("baseline (gate off)", m_base)
        _print_row(f"{gate_name} (gate on)", m_filt)
        if label.startswith("OUT-OF-SAMPLE"):
            oos_baseline_pf, oos_filtered_pf = m_base["pf"], m_filt["pf"]

    print()
    if not np.isfinite(oos_baseline_pf) and not np.isfinite(oos_filtered_pf):
        print("⚠️  Out-of-sample insuffisant pour conclure — ne pas activer le flag.")
        return False
    improved = (
        np.isfinite(oos_filtered_pf)
        and (not np.isfinite(oos_baseline_pf) or oos_filtered_pf > oos_baseline_pf)
    )
    if improved:
        print(f"✅ Gate '{gate_name}' validé — PF out-of-sample amélioré "
              f"({oos_baseline_pf:.2f} → {oos_filtered_pf:.2f}). Peut être activé.")
    else:
        print(f"❌ Gate '{gate_name}' REFUSÉ — PF out-of-sample non amélioré "
              f"({oos_baseline_pf:.2f} → {oos_filtered_pf:.2f}). Ne pas activer le flag.")
    return improved


async def _main_async(args: argparse.Namespace) -> int:
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        print(f"Téléchargement {args.symbol} {args.tf} — {args.days}j d'historique ...")
        df = await fetch_klines_history(session, args.symbol, args.tf, args.days)
    if df is None or df.empty:
        print("Échec : aucune donnée récupérée.", file=sys.stderr)
        return 2
    close = df["close"].to_numpy(dtype=float)
    print(f"{len(close)} bougies récupérées.")

    validated = run_gate_validation(close, args.gate, window=args.window, split_ratio=args.split)

    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            split = int(len(close) * args.split)
            oos = close[split:]
            trades = strat(oos)
            baseline_eq = equity_curve([p for _, p in trades])
            filtered_eq = equity_curve([p for _, p in GATES[args.gate](oos, trades, args.window)])
            fig, ax = plt.subplots(figsize=(9, 4.5))
            ax.plot(baseline_eq, color="#5A6B8C", lw=1.6, label=f"Baseline ({baseline_eq[-1]:.0f}$)")
            ax.plot(filtered_eq, color="#34D399", lw=2, label=f"{args.gate} ({filtered_eq[-1]:.0f}$)")
            ax.axhline(1000, color="#F4C95D", ls="--", lw=1)
            ax.set_title(f"{args.symbol} {args.tf} — OOS equity — gate {args.gate}")
            ax.legend()
            ax.grid(alpha=.2)
            fig.tight_layout()
            out = f"backtest_{args.gate}_{args.symbol.replace('/', '')}_oos.png"
            fig.savefig(out, dpi=150)
            print(f"Graphe sauvegardé : {out}")
        except Exception as e:
            print(f"(matplotlib indisponible : {e})")

    return 0 if validated else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", required=True, choices=sorted(GATES.keys()))
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--window", type=int, default=100, help="fenêtre glissante pour le gate (barres)")
    ap.add_argument("--split", type=float, default=0.70, help="ratio in-sample walk-forward")
    ap.add_argument("--plot", action="store_true", help="sauvegarde un graphe equity (matplotlib)")
    args = ap.parse_args()
    sys.exit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
