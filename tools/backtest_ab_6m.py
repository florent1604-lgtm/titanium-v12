"""tools/backtest_ab_6m.py — Backtest A/B : ancienne vs nouvelle formule SL/TP.

Protocole :
  - 6 mois de bougies 5m Binance (pagination REST correcte avec startTime,
    contrairement à fetch_klines_history qui refetche 1000x les mêmes bougies).
  - Entrées identiques dans les deux bras : momentum EMA5/20 (même règle que
    engine/optimizer._backtest_config). Ce N'EST PAS le scoring SMC complet —
    delta volume, news et futures ne sont pas rejouables hors-ligne. Le test
    mesure l'impact de la CORRECTION DES SORTIES, pas l'edge de la stratégie.
  - Coûts réalistes identiques des deux côtés : frais taker 4bps + slippage
    5bps + demi-spread 2bps par côté = 22 bps aller-retour.
  - Bras OLD  : formule d'origine (frais inversés, pas de plancher TP).
  - Bras NEW  : formule corrigée (plancher TP >= 2x coûts) + time-stop 72h.
  - Sortie : premier niveau touché ferme tout (pas de cascade partielle).

Usage :
  python tools/backtest_ab_6m.py            # BTC + PAXG, 180 jours
  python tools/backtest_ab_6m.py --days 90
"""
from __future__ import annotations
import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REST = "https://api.binance.com/api/v3/klines"
CACHE_DIR = Path(__file__).resolve().parent / ".bt_cache"

# Coûts par côté (bps) — mêmes valeurs que utils/config.py
FEE_BPS, SLIP_BPS, SPREAD_BPS = 4.0, 5.0, 2.0
COST_SIDE = (FEE_BPS + SLIP_BPS + SPREAD_BPS) / 10_000       # 11 bps
RT_COST   = 2 * COST_SIDE                                     # 22 bps

# Paramètres par symbole — mêmes défauts que SYM_OVERRIDES
PARAMS = {
    "BTCUSDT":  {"atr_mult": 1.0, "tp_ratios": (1.5, 2.1, 2.6), "sl_floor": 0.0010},
    "PAXGUSDT": {"atr_mult": 1.2, "tp_ratios": (1.0, 1.5, 2.0), "sl_floor": 0.0025},
}
FEE = 0.0004                       # le "fee" que l'ancienne formule injectait
MIN_TP1_COST_MULT = 2.0            # même garde-fou que risk_manager
TIME_STOP_BARS = 72 * 12           # 72h en bougies 5m


def fetch_5m(symbol: str, days: int) -> pd.DataFrame:
    """Fetch paginé de bougies 5m, avec cache disque."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"{symbol}_5m_{days}d.csv"
    if cache.exists():
        return pd.read_csv(cache, index_col="ts", parse_dates=["ts"])

    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    rows, cursor = [], start_ms
    while cursor < end_ms:
        url = (f"{REST}?symbol={symbol}&interval=5m&limit=1000"
               f"&startTime={cursor}&endTime={end_ms}")
        with urllib.request.urlopen(url, timeout=20) as r:
            batch = json.load(r)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 300_000     # +5min après la dernière bougie
        print(f"\r  {symbol}: {len(rows)} bougies...", end="", flush=True)
        time.sleep(0.15)
    print()

    df = pd.DataFrame({
        "ts":    [pd.to_datetime(int(k[0]), unit="ms", utc=True) for k in rows],
        "open":  [float(k[1]) for k in rows],
        "high":  [float(k[2]) for k in rows],
        "low":   [float(k[3]) for k in rows],
        "close": [float(k[4]) for k in rows],
    }).set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_csv(cache)
    return df


def compute_levels_old(price: float, atr_v: float, p: dict, is_long: bool):
    """Formule D'ORIGINE — frais inversés, aucun plancher de rentabilité."""
    sl_dist = max(atr_v * p["atr_mult"], price * p["sl_floor"])
    r = p["tp_ratios"]
    if is_long:
        sl  = price - sl_dist - price * FEE
        tps = [price + sl_dist * ri - price * FEE for ri in r]
    else:
        sl  = price + sl_dist + price * FEE
        tps = [price - sl_dist * ri + price * FEE for ri in r]
    return sl, tps


def compute_levels_new(price: float, atr_v: float, p: dict, is_long: bool):
    """Formule CORRIGÉE — mêmes maths que execution/risk_manager.py."""
    sl_dist = max(atr_v * p["atr_mult"], price * p["sl_floor"])
    r = p["tp_ratios"]
    cost_dist = price * RT_COST
    d1 = max(sl_dist * r[0], price * RT_COST * MIN_TP1_COST_MULT)
    d2 = max(sl_dist * r[1], d1 * 1.4)
    d3 = max(sl_dist * r[2], d2 * 1.25)
    if is_long:
        return price - sl_dist, [price + d + cost_dist for d in (d1, d2, d3)]
    return price + sl_dist, [price - d - cost_dist for d in (d1, d2, d3)]


def run_arm(df: pd.DataFrame, p: dict, use_new: bool) -> dict:
    """Simule un bras. Entrées EMA5/20, coûts 22bps RT appliqués au retour."""
    close = df["close"].values
    high, low = df["high"].values, df["low"].values
    n = len(close)

    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    atr = np.concatenate([[tr[0]], pd.Series(tr).rolling(14).mean().bfill().values])

    returns, durations = [], []
    in_trade = False
    entry = sl = 0.0
    tps: list = []
    is_long = True
    entry_i = 0

    # Pré-calcul des EMA pour détecter les CROISEMENTS (événements, pas états).
    # Entrer sur l'état ema_f>ema_s génère ~40 trades/jour et les coûts (22bps)
    # noient tout signal ; le vrai bot filtré par score /16 fait ~2 trades/jour.
    ema_f_arr = pd.Series(close).ewm(span=5).mean().values
    ema_s_arr = pd.Series(close).ewm(span=20).mean().values

    for i in range(20, n):
        if not in_trade:
            cross_up   = ema_f_arr[i] > ema_s_arr[i] and ema_f_arr[i-1] <= ema_s_arr[i-1]
            cross_down = ema_f_arr[i] < ema_s_arr[i] and ema_f_arr[i-1] >= ema_s_arr[i-1]
            if cross_up and close[i] > close[i - 1]:
                is_long, in_trade = True, True
            elif cross_down and close[i] < close[i - 1]:
                is_long, in_trade = False, True
            else:
                continue
            entry, entry_i = close[i], i
            fn = compute_levels_new if use_new else compute_levels_old
            sl, tps = fn(entry, atr[i], p, is_long)
            continue

        exit_px = None
        if use_new and (i - entry_i) >= TIME_STOP_BARS:
            exit_px = close[i]                              # time-stop
        elif is_long:
            if low[i] <= sl:      exit_px = sl
            elif high[i] >= tps[2]: exit_px = tps[2]
            elif high[i] >= tps[1]: exit_px = tps[1]
            elif high[i] >= tps[0]: exit_px = tps[0]
        else:
            if high[i] >= sl:     exit_px = sl
            elif low[i] <= tps[2]: exit_px = tps[2]
            elif low[i] <= tps[1]: exit_px = tps[1]
            elif low[i] <= tps[0]: exit_px = tps[0]

        if exit_px is not None:
            raw = (exit_px - entry) / entry if is_long else (entry - exit_px) / entry
            returns.append(raw - RT_COST)                   # coûts réalistes
            durations.append(i - entry_i)
            in_trade = False

    if len(returns) < 2:
        return {"trades": 0}
    r = np.array(returns)
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(equity)
    max_dd = float(((equity - peak) / peak).min())
    n_days = len(df) / 288
    tpd = len(r) / n_days
    sharpe = float(r.mean() / r.std() * math.sqrt(252 * tpd)) if r.std() > 1e-12 else 0.0
    return {
        "trades":       len(r),
        "winrate":      float((r > 0).mean()),
        "expectancy_bps": float(r.mean() * 10_000),
        "total_return": float(equity[-1] - 1),
        "max_drawdown": max_dd,
        "sharpe":       round(sharpe, 2),
        "avg_dur_h":    round(float(np.mean(durations)) * 5 / 60, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    args = ap.parse_args()

    print(f"Backtest A/B — {args.days} jours, bougies 5m, coûts {RT_COST*10000:.0f} bps RT\n")
    for sym, p in PARAMS.items():
        df = fetch_5m(sym, args.days)
        print(f"── {sym} — {len(df)} bougies ({df.index[0].date()} → {df.index[-1].date()})")
        for label, use_new in (("ANCIENNE formule", False), ("NOUVELLE formule", True)):
            s = run_arm(df, p, use_new)
            if s.get("trades", 0) == 0:
                print(f"  {label}: pas assez de trades")
                continue
            print(f"  {label}: {s['trades']} trades | winrate {s['winrate']*100:.1f}% | "
                  f"expectancy {s['expectancy_bps']:+.1f} bps/trade | "
                  f"retour total {s['total_return']*100:+.1f}% | "
                  f"maxDD {s['max_drawdown']*100:.1f}% | sharpe {s['sharpe']} | "
                  f"durée moy {s['avg_dur_h']}h")
        print()


if __name__ == "__main__":
    main()
