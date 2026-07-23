"""tools/strategy_lab.py — Laboratoire de backtest multi-actifs.

Objectif : valider (ou invalider) des variantes correctives de la stratégie
Titanium AVANT toute application en production, sur crypto + or + forex.

Constat de départ (paper 07-08/07/2026) : 31 trades, 100 % SHORT, 81 % de
sorties en SL, winrate 29 %. Causes suspectées : SL ATR×1 trop serré face à
un ladder TP 2.5/3.5/5, et biais EMA200 pris à contre-momentum.

Variantes testées (proxy fidèle du cœur Titanium : biais EMA200 + trigger
TRIX + pullback RSI + ladder TP partiel + BE après TP1) :
  V0  baseline    — SL ATR×1.0, TP 2.5/3.5/5   (config actuelle optimiseur)
  V1  respiration — SL ATR×2.0, TP 1.5/2.5/4
  V2  régime      — ADX≥25 : suivi de tendance (V1) ; ADX<20 : mean-reversion
                    aux bandes de Bollinger, SL ATR×1.5, TP 2×ATR
  V3  alignement  — biais EMA200 ET pente EMA50 dans le même sens, SL ATR×2,
                    TP 1.5/2.5/4 (filtre anti contre-mouvement)

Frais : 11 bps aller-retour crypto (taker+spread+slippage), 2 bps forex.
Données : Binance 1h (crypto) + Yahoo 1h (forex/or), ~365 jours.

Usage :
    venv\\Scripts\\python.exe tools\\strategy_lab.py            # tous
    venv\\Scripts\\python.exe tools\\strategy_lab.py --assets BTC,EURUSD
Sortie : tableau console + data/strategy_lab_report.json
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "lab_cache"
REPORT = ROOT / "data" / "strategy_lab_report.json"

ASSETS = {
    # nom → (source, symbole, frais aller-retour en bps)
    "BTC":    ("binance", "BTCUSDT", 11),
    "ETH":    ("binance", "ETHUSDT", 11),
    "PAXG":   ("binance", "PAXGUSDT", 11),
    "EURUSD": ("yahoo", "EURUSD=X", 2),
    "GBPUSD": ("yahoo", "GBPUSD=X", 2),
    "XAU":    ("yahoo", "GC=F", 4),
}
DAYS = 365
TIME_STOP_BARS = 48          # aligné sur PAPER_MAX_HOLD_HOURS
UA = {"User-Agent": "Mozilla/5.0 (TitaniumLab)"}


# ── Données ──────────────────────────────────────────────────────────────────

def _http_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_binance_1h(sym: str, days: int) -> pd.DataFrame:
    end = int(time.time() * 1000)
    start = end - days * 86400_000
    rows = []
    cur = start
    while cur < end:
        url = (f"https://api.binance.com/api/v3/klines?symbol={sym}"
               f"&interval=1h&startTime={cur}&limit=1000")
        batch = _http_json(url)
        if not batch:
            break
        rows += batch
        cur = batch[-1][6] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns="ot o h l c v ct qv n tb tq ig".split())
    df.index = pd.to_datetime(df["ot"].astype(np.int64), unit="ms", utc=True)
    return df[["o", "h", "l", "c"]].astype(float).rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close"})


def fetch_yahoo_1h(sym: str, days: int) -> pd.DataFrame:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?interval=1h&range={min(days, 729)}d")
    d = _http_json(url)["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    df = pd.DataFrame({
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
    }, index=pd.to_datetime(pd.Series(d["timestamp"]).astype(np.int64), unit="s", utc=True))
    return df.dropna()


def load_data(name: str) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}_1h.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 6 * 3600:
        return pd.read_pickle(f)
    source, sym, _ = ASSETS[name]
    df = fetch_binance_1h(sym, DAYS) if source == "binance" else fetch_yahoo_1h(sym, DAYS)
    df.to_pickle(f)
    return df


# ── Indicateurs (numpy/pandas purs — pas de lookahead) ──────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - c.shift()).abs(),
                    (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    # TRIX(15) + signal(9)
    e3 = c.ewm(span=15, adjust=False).mean().ewm(span=15, adjust=False).mean() \
          .ewm(span=15, adjust=False).mean()
    df["trix"] = e3.pct_change() * 10_000
    df["trix_sig"] = df["trix"].ewm(span=9, adjust=False).mean()
    # ADX(14)
    up_m = df["high"].diff()
    dn_m = -df["low"].diff()
    plus_dm = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
    minus_dm = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    # Bollinger(20, 2)
    m = c.rolling(20).mean()
    s = c.rolling(20).std()
    df["bb_lo"], df["bb_hi"] = m - 2 * s, m + 2 * s
    return df.dropna()


# ── Moteur de backtest (ladder TP partiel + BE, comme Titanium) ─────────────

def simulate(df: pd.DataFrame, entries: pd.DataFrame, sl_mult: float,
             tp_mults: list, fees_bps: float,
             time_stop: int = TIME_STOP_BARS) -> list:
    """entries: DataFrame(index=ts, side ±1). Entrée à l'open de la barre
    suivante ; SL/TP intrabar ; partiels 33/33/34 ; SL→BE après TP1."""
    trades = []
    o, h, l = df["open"].values, df["high"].values, df["low"].values
    atr = df["atr"].values
    idx = df.index
    pos = None
    entry_set = {ts: s for ts, s in zip(entries.index, entries["side"])}
    for i in range(1, len(df)):
        ts = idx[i]
        if pos:
            side, ep, slp, tps, filled, bars, pnl = pos
            hi, lo = h[i], l[i]
            # SL d'abord (conservateur)
            hit_sl = lo <= slp if side > 0 else hi >= slp
            if hit_sl:
                rest = 1.0 - sum(filled)
                pnl += rest * side * (slp - ep) / ep
                trades.append(pnl * 10_000 - fees_bps)
                pos = None
            else:
                parts = [0.33, 0.33, 0.34]
                for k, tp in enumerate(tps):
                    if filled[k] == 0:
                        hit = hi >= tp if side > 0 else lo <= tp
                        if hit:
                            filled[k] = parts[k]
                            pnl += parts[k] * side * (tp - ep) / ep
                            if k == 0:
                                slp = ep      # break-even après TP1
                if sum(filled) >= 0.999:
                    trades.append(pnl * 10_000 - fees_bps)
                    pos = None
                else:
                    bars += 1
                    if bars >= time_stop:
                        rest = 1.0 - sum(filled)
                        pnl += rest * side * (df["close"].values[i] - ep) / ep
                        trades.append(pnl * 10_000 - fees_bps)
                        pos = None
                    else:
                        pos = (side, ep, slp, tps, filled, bars, pnl)
        if pos is None and idx[i - 1] in entry_set:
            side = entry_set[idx[i - 1]]
            ep = o[i]
            a = atr[i - 1]
            slp = ep - side * sl_mult * a
            tps = [ep + side * m * a for m in tp_mults]
            pos = (side, ep, slp, tps, [0, 0, 0], 0, 0.0)
    return trades


# ── Variantes de stratégie ───────────────────────────────────────────────────

def entries_v0_v1(df: pd.DataFrame) -> pd.DataFrame:
    """Proxy actuel : biais EMA200 + croisement TRIX dans le sens du biais
    + pullback RSI."""
    bias = np.where(df["close"] > df["ema200"], 1, -1)
    x_up = (df["trix"] > df["trix_sig"]) & (df["trix"].shift() <= df["trix_sig"].shift())
    x_dn = (df["trix"] < df["trix_sig"]) & (df["trix"].shift() >= df["trix_sig"].shift())
    lg = (bias > 0) & x_up & (df["rsi"] < 55)
    sh = (bias < 0) & x_dn & (df["rsi"] > 45)
    side = np.where(lg, 1, np.where(sh, -1, 0))
    e = pd.DataFrame({"side": side}, index=df.index)
    return e[e["side"] != 0]


def entries_v2(df: pd.DataFrame):
    """Régime : tendance si ADX≥25 (comme V1), mean-reversion si ADX<20."""
    trend = entries_v0_v1(df)
    trend = trend[df.loc[trend.index, "adx"] >= 25]
    mr_lg = (df["adx"] < 20) & (df["close"] < df["bb_lo"]) & (df["rsi"] < 30)
    mr_sh = (df["adx"] < 20) & (df["close"] > df["bb_hi"]) & (df["rsi"] > 70)
    side = np.where(mr_lg, 1, np.where(mr_sh, -1, 0))
    mr = pd.DataFrame({"side": side}, index=df.index)
    mr = mr[mr["side"] != 0]
    return trend, mr


def entries_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Alignement double : biais EMA200 ET pente EMA50 même sens."""
    e = entries_v0_v1(df)
    slope_up = df["ema50"] > df["ema50"].shift(5)
    keep = [(s > 0 and slope_up.loc[ts]) or (s < 0 and not slope_up.loc[ts])
            for ts, s in zip(e.index, e["side"])]
    return e[keep]


# ── Métriques ────────────────────────────────────────────────────────────────

def metrics(trades: list) -> dict:
    if len(trades) < 5:
        return {"trades": len(trades), "note": "échantillon insuffisant"}
    t = np.array(trades)
    wins, losses = t[t > 0], t[t <= 0]
    eq = np.cumsum(t)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return {
        "trades":        len(t),
        "winrate_pct":   round(100 * len(wins) / len(t), 1),
        "expectancy_bps": round(float(t.mean()), 1),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2)
                          if losses.sum() < 0 else float("inf"),
        "total_bps":     round(float(t.sum()), 0),
        "max_dd_bps":    round(dd, 0),
        "sharpe_trade":  round(float(t.mean() / (t.std() or 1)), 3),
    }


def run(asset_names=None) -> dict:
    report = {"days": DAYS, "generated": pd.Timestamp.utcnow().isoformat(),
              "assets": {}}
    for name in (asset_names or ASSETS):
        fees = ASSETS[name][2]
        try:
            df = add_indicators(load_data(name))
        except Exception as e:
            report["assets"][name] = {"error": str(e)}
            print(f"[{name}] données indisponibles: {e}")
            continue
        res = {}
        e01 = entries_v0_v1(df)
        res["V0_baseline_sl1.0_tp2.5/3.5/5"] = metrics(
            simulate(df, e01, 1.0, [2.5, 3.5, 5.0], fees))
        res["V1_respiration_sl2.0_tp1.5/2.5/4"] = metrics(
            simulate(df, e01, 2.0, [1.5, 2.5, 4.0], fees))
        tr, mr = entries_v2(df)
        t_tr = simulate(df, tr, 2.0, [1.5, 2.5, 4.0], fees)
        t_mr = simulate(df, mr, 1.5, [2.0, 2.0, 2.0], fees)
        res["V2_regime_adx"] = metrics(t_tr + t_mr)
        res["V3_alignement_ema50"] = metrics(
            simulate(df, entries_v3(df), 2.0, [1.5, 2.5, 4.0], fees))
        report["assets"][name] = {"bars": len(df), "fees_bps": fees,
                                  "variants": res}
        print(f"\n═══ {name} ({len(df)} barres 1h, frais {fees} bps) ═══")
        for v, m in res.items():
            print(f"  {v:<38} {m}")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"\nRapport → {REPORT}")
    return report


if __name__ == "__main__":
    names = None
    if "--assets" in sys.argv:
        names = sys.argv[sys.argv.index("--assets") + 1].split(",")
    run(names)
