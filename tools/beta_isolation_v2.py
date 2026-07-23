"""tools/beta_isolation_v2.py — Isolation alpha vs beta, CORRIGÉE (P0 Codex 16/07).

Remplace beta_isolation.py (garde comme diagnostic). Corrige :
 P0-1 calendrier : rendements quotidiens sur calendrier UTC COMPLET (zéro les
      jours sans sortie), plus seulement les jours de trade (échantillon biaisé).
 P0-2 unités : y = rendement NAV (R-multiple × risque fixe/sleeve), comparable à
      un rendement de marché ; plus de beta sans interprétation.
 P0-3 inférence : alpha avec ERREUR STANDARD — t-stat Newey-West (HAC, lag lié à
      l'horizon 48h≈2j) ET IC95 par block-bootstrap. Aucun label 'alpha' sans que
      l'IC exclue 0.
 Facteur : régression contre r_BTC (beta crypto COMMUN), pas contre l'actif seul.
 Long/short : n, expectancy nette, PF, maxDD, IC bootstrap par côté.

In-sample sur l'historique complet — CARACTÉRISE l'edge, ne le VALIDE pas
(seul le forward-paper gelé valide). PAPER ONLY.
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

import numpy as np
import pandas as pd

from tools.binance_history import get_klines
from tools.asset_optimizer_m2 import entries, add_indicators
from validation.asset_simulation import Bar, CostModel, simulate

WATCH = ["XRPUSDT", "LINKUSDT", "AVAXUSDT", "SOLUSDT"]   # +SOL contraste
ALIGN, RSI_GATE, SL_ATR, TP_LADDER, TIME_STOP, MAKER_RT = True, True, 1.5, (1.5, 2.5, 4.0), 48, 15.0
RISK = 0.07           # risque fixe par sleeve -> rendement NAV = R * RISK
ANN = 365.0
RNG = np.random.default_rng(20260716)


def _trades(symbol: str, years: float = 4.0):
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
    return trades, frame


def _daily_nav(trades, calendar) -> pd.Series:
    """Rendement NAV quotidien (R*RISK) sur calendrier COMPLET (zéro sinon)."""
    s = pd.Series(0.0, index=calendar)
    for t in trades:
        if not t.initial_risk_bps:
            continue
        d = pd.Timestamp(t.exit_timestamp).normalize().tz_localize(None)
        if d in s.index:
            s.loc[d] += (t.net_bps / t.initial_risk_bps) * RISK
    return s


def _nw_tstat(y, x):
    """OLS y~1+x + erreur standard Newey-West (HAC) sur alpha. Retourne
    (alpha, beta, t_alpha, r2)."""
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    resid = y - X @ b
    L = max(1, int(4 * (n / 100.0) ** (2.0 / 9.0)))     # lag NW automatique
    S = (X * resid[:, None])
    omega = S.T @ S
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        G = S[l:].T @ S[:-l]
        omega += w * (G + G.T)
    cov = XtX_inv @ omega @ XtX_inv
    se_alpha = float(np.sqrt(cov[0, 0]))
    t_alpha = float(b[0] / se_alpha) if se_alpha > 0 else float("nan")
    ss_res = float(resid @ resid); ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(b[0]), float(b[1]), t_alpha, r2


def _block_boot_alpha(y, x, blocks=5000, block=5):
    """IC95 de l'alpha par block-bootstrap (préserve l'autocorrélation)."""
    n = len(y); nb = int(np.ceil(n / block))
    alphas = []
    idx0 = np.arange(n)
    for _ in range(blocks):
        starts = RNG.integers(0, n - block + 1, size=nb)
        idx = np.concatenate([idx0[s:s + block] for s in starts])[:n]
        yy, xx = y[idx], x[idx]
        X = np.column_stack([np.ones(n), xx])
        try:
            b = np.linalg.solve(X.T @ X, X.T @ yy)
            alphas.append(b[0])
        except Exception:
            pass
    a = np.array(alphas)
    return float(np.percentile(a, 2.5)) * ANN, float(np.percentile(a, 97.5)) * ANN


def _side(trades, side):
    rs = [(t.net_bps / t.initial_risk_bps) for t in trades if t.side == side and t.initial_risk_bps]
    if not rs:
        return None
    rs = np.array(rs); n = len(rs)
    eq = np.cumsum(rs); dd = float((np.maximum.accumulate(eq) - eq).max())
    gains = rs[rs > 0].sum(); losses = -rs[rs < 0].sum()
    pf = gains / losses if losses > 0 else float("inf")
    # IC95 bootstrap de la moyenne
    boot = [RNG.choice(rs, n, replace=True).mean() for _ in range(3000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"n": n, "mean": float(rs.mean()), "pf": pf, "maxdd": dd,
            "ci": (float(lo), float(hi)), "wr": float((rs > 0).mean())}


def main() -> None:
    print("=== ISOLATION ALPHA vs BETA v2 (P0 Codex : NAV, facteur BTC, HAC + bootstrap) ===\n")
    btc, _ = _trades("BTCUSDT")   # inutile ; on veut le prix BTC comme facteur
    btc_df = get_klines("BTCUSDT", "H1", years=4)
    btc_daily = btc_df["close"].resample("1D").last().dropna().pct_change().dropna()
    btc_daily.index = btc_daily.index.tz_localize(None)

    for sym in WATCH:
        trades, frame = _trades(sym)
        if not trades:
            print(f"{sym}: pas de trade\n"); continue
        cal = pd.date_range(frame.index[0].normalize().tz_localize(None),
                            frame.index[-1].normalize().tz_localize(None), freq="D")
        strat = _daily_nav(trades, cal)
        j = pd.concat([strat.rename("s"), btc_daily.rename("m")], axis=1).dropna()
        y, x = j["s"].to_numpy(), j["m"].to_numpy()
        alpha_d, beta, t_a, r2 = _nw_tstat(y, x)
        lo, hi = _block_boot_alpha(y, x)
        aL, aS = _side(trades, +1), _side(trades, -1)
        print(f"{sym}  ({len(trades)} trades, {len(j)} jours)")
        sig = "significatif (IC exclut 0)" if lo > 0 or hi < 0 else "NON significatif (IC contient 0)"
        print(f"   alpha annualisé {alpha_d*ANN:+.3f} | t-stat NW {t_a:+.2f} | IC95 [{lo:+.2f}, {hi:+.2f}] -> {sig}")
        print(f"   beta_BTC {beta:+.2f} | R2 {r2:.2f}")
        for name, d in (("LONGS ", aL), ("SHORTS", aS)):
            if d:
                ci0 = "gagnant" if d["ci"][0] > 0 else ("perdant" if d["ci"][1] < 0 else "incertain")
                print(f"   {name}: n={d['n']:3d} mean {d['mean']:+.3f} PF {d['pf']:.2f} "
                      f"maxDD {d['maxdd']:.1f} IC95[{d['ci'][0]:+.3f},{d['ci'][1]:+.3f}] {ci0}")
        print()
    print("Verdict alpha SEULEMENT si t-stat |>2| ET IC95 exclut 0 ET pas juste du beta_BTC.")


if __name__ == "__main__":
    main()
