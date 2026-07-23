"""tools/beta_isolation.py — L'edge intraday de XRP/AVAX/LINK est-il un VRAI alpha
ou juste du beta de marche (etre long pendant que ca monte) ?

Deux angles :
 1) LONGS vs SHORTS separes. La strategie (biais EMA200 + TRIX) est trend-following
    donc majoritairement longue en marche haussier. Si les SHORTS gagnent AUSSI,
    il y a un timing a deux faces = vrai edge. S'ils saignent, c'est du long-beta.
 2) REGRESSION sur l'actif detenu (buy&hold) : alpha (intercept) + beta (pente) +
    R2. alpha annualise > 0 = surperformance vs simplement detenir. beta eleve +
    alpha ~0 = la strat ne fait que suivre le marche.

Config FIXE identique (align=T rsi=T sl=1.5 tp=1.5-2.5-4.0 ts=48), cout maker RT15.
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
import numpy as np
import pandas as pd

from tools.binance_history import get_klines
from tools.asset_optimizer_m2 import entries, add_indicators
from validation.asset_simulation import Bar, CostModel, simulate

WATCH = ["XRPUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT", "BTCUSDT"]  # +SOL/BTC pour contraste
ALIGN, RSI_GATE, SL_ATR, TP_LADDER, TIME_STOP, MAKER_RT = True, True, 1.5, (1.5, 2.5, 4.0), 48, 15.0
ANN = math.sqrt(365.0)


def _trades_and_market(symbol: str, years: float = 4.0):
    df = get_klines(symbol, "H1", years=years)
    if df is None or len(df) < 600:
        return None, None
    frame = add_indicators(df.copy())
    sig = entries(frame, ALIGN, RSI_GATE)
    smap = {ts: int(s) for ts, s in zip(sig.index, sig["side"])}
    bars = tuple(Bar(ts.to_pydatetime(), float(r.open), float(r.high), float(r.low),
                     float(r.close), float(r.atr), smap.get(ts, 0)) for ts, r in frame.iterrows())
    costs = CostModel(spread_bps=1.0, slippage_bps=1.0, swap_long_bps_per_rollover=0.0,
                      swap_short_bps_per_rollover=0.0, triple_swap_weekday=2, commission_bps=MAKER_RT)
    trades = simulate(bars, sl_atr=SL_ATR, tp_ladder=TP_LADDER, time_stop_bars=TIME_STOP, costs=costs)
    # marche = rendement quotidien buy&hold de l'actif
    daily_close = frame["close"].resample("1D").last().dropna()
    market = daily_close.pct_change().dropna()
    return trades, market


def _side_stats(trades, side):
    rs = [t.net_bps / t.initial_risk_bps for t in trades if t.side == side and t.initial_risk_bps]
    if not rs:
        return (0, 0.0, float("nan"), 0.0)
    n = len(rs)
    wr = sum(1 for r in rs if r > 0) / n
    sh = (np.mean(rs) / np.std(rs, ddof=1) * math.sqrt(n)) if n > 1 and np.std(rs, ddof=1) else float("nan")
    return (n, sum(rs), wr, sh)


def _alpha_beta(trades, market):
    # serie quotidienne de la strat (R par jour d'exit)
    rows = {}
    for t in trades:
        d = pd.Timestamp(t.exit_timestamp).normalize()
        rows[d] = rows.get(d, 0.0) + (t.net_bps / t.initial_risk_bps if t.initial_risk_bps else 0.0)
    strat = pd.Series(rows).sort_index()
    j = pd.concat([strat.rename("s"), market.rename("m")], axis=1).dropna()
    if len(j) < 20:
        return None
    x = j["m"].to_numpy(); y = j["s"].to_numpy()
    beta, alpha = np.polyfit(x, y, 1)
    corr = float(np.corrcoef(x, y)[0, 1])
    return {"alpha_day": float(alpha), "alpha_ann": float(alpha) * 365,
            "beta": float(beta), "r2": corr * corr, "n": len(j)}


def main() -> None:
    print("=== ISOLATION BETA vs ALPHA (config fixe intraday, maker) ===\n")
    for s in WATCH:
        trades, market = _trades_and_market(s)
        if not trades:
            print(f"{s}: pas de trade\n"); continue
        nL, rL, wL, shL = _side_stats(trades, +1)
        nS, rS, wS, shS = _side_stats(trades, -1)
        ab = _alpha_beta(trades, market)
        print(f"{s}  ({len(trades)} trades)")
        print(f"   LONGS  : {nL:4d} | R {rL:+6.2f} | winrate {wL*100:4.0f}% | Sharpe {shL:+.2f}")
        print(f"   SHORTS : {nS:4d} | R {rS:+6.2f} | winrate {wS*100:4.0f}% | Sharpe {shS:+.2f}")
        if ab:
            verdict = ("VRAI ALPHA" if ab["alpha_ann"] > 0 and (rS > 0 or nS == 0)
                       else "surtout BETA long" if ab["beta"] > 0.3 and rS <= 0
                       else "mixte")
            print(f"   alpha annualise {ab['alpha_ann']:+.3f} | beta {ab['beta']:+.2f} | "
                  f"R2 {ab['r2']:.2f} -> {verdict}")
        print()
    print("Lecture : SHORTS gagnants + alpha>0 = vrai edge 2 faces. "
          "SHORTS perdants + beta>0 = juste long pendant la hausse.")


if __name__ == "__main__":
    main()
