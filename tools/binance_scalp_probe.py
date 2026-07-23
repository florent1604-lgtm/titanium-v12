"""tools/binance_scalp_probe.py — Verdict RAPIDE de la these scalp sur Binance.

Reutilise TEL QUEL le moteur de Codex (entries -> Bar -> simulate ->
summarize_trade_economics) mais nourri par les prix Binance spot et les COUTS
Binance (frais taker 10 bps/cote vs maker 7.5). Balaye la grille de configs scalp
comme le vrai optimiseur, garde la meilleure par actif.

⚠️ Ceci est un PROBE IN-SAMPLE (toute l'historique, pas de split OOS/DSR) : il
repond a "le scalp peut-il seulement battre les frais Binance ?". Si meme la
MEILLEURE config perd en maker, la these est morte. Si elle gagne, on passe au
protocole M2 complet (OOS + PBO + Deflated Sharpe) avant toute conclusion prod.

Lancer : venv\\Scripts\\python.exe tools\\binance_scalp_probe.py BTCUSDT ETHUSDT SOLUSDT
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from tools.binance_history import get_klines
from tools.asset_optimizer_m2 import entries, ENTRY_VARIANTS, GRIDS, add_indicators
from validation.asset_simulation import Bar, CostModel, simulate, summarize_trade_economics

TIME_STOP_SCALP = 32
RISK = 0.07
BALANCE = 1000.0


def _net_key(econ: dict) -> str:
    for k in ("expectancy_net_bps", "net_edge_bps", "mean_net_bps", "net_expectancy_bps"):
        if k in econ:
            return k
    # sinon : le premier champ qui contient net + bps
    for k in econ:
        if "net" in k and "bps" in k:
            return k
    return "expectancy_net_bps"


def probe_symbol(symbol: str, years: float = 2.0) -> None:
    df = get_klines(symbol, "M15", years=years)
    if df is None or len(df) < 600:
        print(f"{symbol:9s} : pas assez de donnees")
        return
    frame = add_indicators(df.copy())
    days = max(1, len(pd.Series(frame.index.date).unique()))

    best = {"taker": None, "maker": None}
    for (align, rsi_gate) in ENTRY_VARIANTS:
        sig = entries(frame, align, rsi_gate)
        smap = {ts: int(s) for ts, s in zip(sig.index, sig["side"])}
        base_bars = [
            (ts, float(r.open), float(r.high), float(r.low), float(r.close), float(r.atr), smap.get(ts, 0))
            for ts, r in frame.iterrows()
        ]
        for sl_atr, ladder in GRIDS["scalp"]:
            bars = tuple(Bar(ts.to_pydatetime(), o, h, l, c, a, s)
                         for ts, o, h, l, c, a, s in base_bars)
            # commission_bps = coût ROUND-TRIP (simulate le soustrait 1×/trade ;
            # frais Binance = par côté → ×2). Red-team Codex 16/07.
            for mode, fee in (("taker", 20.0), ("maker", 15.0)):
                costs = CostModel(spread_bps=1.0, slippage_bps=1.0,
                                  swap_long_bps_per_rollover=0.0,   # spot Binance : pas de swap
                                  swap_short_bps_per_rollover=0.0,
                                  triple_swap_weekday=2, commission_bps=fee)
                trades = simulate(bars, sl_atr=float(sl_atr),
                                  tp_ladder=tuple(float(x) for x in ladder),
                                  time_stop_bars=TIME_STOP_SCALP, costs=costs)
                if not trades:
                    continue
                econ = summarize_trade_economics(
                    trades, trading_day_count=days, risk_fraction=RISK,
                    account_balance=BALANCE, observed_spread_bps=1.0,
                    spread_multiplier=1.0, commission_bps=fee)
                nk = _net_key(econ)
                net = econ.get(nk)
                if net is None:
                    continue
                cur = best[mode]
                if cur is None or net > cur["net"]:
                    best[mode] = {"net": net, "tpd": econ.get("trades_per_day"),
                                  "n": econ.get("trades"), "be": econ.get("break_even_spread_bps"),
                                  "cfg": f"align={align} rsi={rsi_gate} sl={sl_atr} tp={ladder}"}

    def fmt(b):
        if not b:
            return "aucun trade"
        return (f"net {b['net']:+.2f} bps/trade | {b['tpd']:.2f} trd/j | "
                f"{b['n']} trades | break-even {b['be']:.1f} bps")
    print(f"{symbol:9s} [{days}j de M15]")
    print(f"   MAKER (RT 15 bps = 7.5/cote) : {fmt(best['maker'])}")
    print(f"   TAKER (RT 20 bps = 10 /cote) : {fmt(best['taker'])}")
    if best["maker"]:
        print(f"   meilleure config maker : {best['maker']['cfg']}")


def main() -> None:
    syms = sys.argv[1:] or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    print("=== PROBE SCALP BINANCE (in-sample, moteur Codex, couts Binance) ===")
    print("    net > 0 = la MEILLEURE config scalp bat les frais. Puis M2 avant prod.\n")
    for s in syms:
        probe_symbol(s)
        print()


if __name__ == "__main__":
    main()
