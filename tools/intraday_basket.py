"""tools/intraday_basket.py — Le PANIER intraday H1 crypto comme portefeuille.

Etape 1 de la piste post-scalp (decision Florent 16/07). Le run M2 Binance a
montre : scalp mort, mais intraday H1 positif sur 6/10 cryptos, aucun ne passant
seul le seuil DSR. Question : un PORTEFEUILLE des cryptos intraday diversifie-t-il
assez pour franchir la barre qu'aucun ne franchit seul ?

Methode honnete : UNE config intraday FIXE et identique pour tous (pas de
cherry-pick par actif), sur les 10 cryptos, cout MAKER round-trip reel (15 bps).
On mesure : Sharpe individuel, Sharpe du portefeuille equi-risque, correlation
moyenne. Reutilise le moteur Codex (entries/simulate). In-sample sur l'historique
complet — c'est un DIAGNOSTIC de diversification, pas un verdict M2 (ca vient apres).
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

import math
import statistics as stats
import pandas as pd

from tools.binance_history import get_klines
from tools.asset_optimizer_m2 import entries, add_indicators
from validation.asset_simulation import Bar, CostModel, simulate

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "ADAUSDT", "AVAXUSDT", "BNBUSDT", "LINKUSDT", "LTCUSDT"]
# Config intraday FIXE (pas d'optimisation par actif) — la plus frequente gagnante.
ALIGN, RSI_GATE = True, True
SL_ATR = 1.5
TP_LADDER = (1.5, 2.5, 4.0)
TIME_STOP = 48                 # intraday H1
MAKER_RT_BPS = 15.0            # cout round-trip maker (7.5/cote)
ANN = math.sqrt(365.0)         # crypto 24/7


def daily_returns(symbol: str, years: float = 4.0) -> pd.Series | None:
    """Rendement quotidien (en R = net_bps/risk) de la config intraday fixe."""
    df = get_klines(symbol, "H1", years=years)
    if df is None or len(df) < 600:
        return None
    frame = add_indicators(df.copy())
    sig = entries(frame, ALIGN, RSI_GATE)
    smap = {ts: int(s) for ts, s in zip(sig.index, sig["side"])}
    bars = tuple(Bar(ts.to_pydatetime(), float(r.open), float(r.high), float(r.low),
                     float(r.close), float(r.atr), smap.get(ts, 0))
                 for ts, r in frame.iterrows())
    costs = CostModel(spread_bps=1.0, slippage_bps=1.0, swap_long_bps_per_rollover=0.0,
                      swap_short_bps_per_rollover=0.0, triple_swap_weekday=2,
                      commission_bps=MAKER_RT_BPS)
    trades = simulate(bars, sl_atr=SL_ATR, tp_ladder=TP_LADDER,
                      time_stop_bars=TIME_STOP, costs=costs)
    if not trades:
        return None
    rows = {}
    for t in trades:
        r = t.net_bps / t.initial_risk_bps if t.initial_risk_bps else 0.0
        day = pd.Timestamp(t.exit_timestamp).normalize()
        rows[day] = rows.get(day, 0.0) + r        # somme des R du jour
    return pd.Series(rows).sort_index()


def sharpe(series: pd.Series) -> float:
    if series is None or len(series) < 5 or series.std(ddof=1) == 0:
        return float("nan")
    return series.mean() / series.std(ddof=1) * ANN


def main() -> None:
    print("=== PANIER INTRADAY H1 CRYPTO (config fixe, cout maker RT 15 bps) ===\n")
    series = {}
    print("%-9s %8s %8s %8s"%("crypto", "Sharpe", "R total", "trades/j"))
    for s in SYMBOLS:
        ds = daily_returns(s)
        if ds is None:
            print("%-9s   pas de donnee/trade"%s); continue
        series[s] = ds
        days = (ds.index.max() - ds.index.min()).days or 1
        print("%-9s %8.2f %8.2f %8.3f"%(s, sharpe(ds), ds.sum(), len(ds)/days))

    if len(series) < 2:
        print("\npas assez d'actifs pour un panier"); return

    # Portefeuille equi-risque : somme des R quotidiens, aligne sur le calendrier.
    alld = pd.concat(series.values(), axis=1).fillna(0.0)
    alld.columns = list(series.keys())
    port = alld.sum(axis=1) / len(series)      # equi-poids
    # correlation moyenne entre actifs (sur jours communs de trade)
    corr = alld.replace(0.0, float("nan")).corr()
    import numpy as np
    m = corr.to_numpy()
    off = m[~np.eye(len(m), dtype=bool)]
    avg_corr = float(np.nanmean(off)) if off.size else float("nan")

    ind = [sharpe(v) for v in series.values()]
    ind_mean = stats.mean([x for x in ind if x == x])
    print("\n--- PORTEFEUILLE ---")
    print(f"  Sharpe moyen des actifs seuls : {ind_mean:+.2f}")
    print(f"  Sharpe du PORTEFEUILLE        : {sharpe(port):+.2f}")
    print(f"  correlation moyenne inter-actifs : {avg_corr:+.2f}")
    print(f"  R total portefeuille : {port.sum():+.2f} sur {len(port)} jours de trade")
    gain = sharpe(port) - ind_mean
    print(f"\n  >>> gain de diversification : {gain:+.2f} de Sharpe "
          f"({'le panier AIDE' if gain>0.1 else 'peu/pas de gain (cryptos trop correles)'})")


if __name__ == "__main__":
    main()
