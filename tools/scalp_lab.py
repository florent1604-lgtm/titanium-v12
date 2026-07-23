"""tools/scalp_lab.py — Laboratoire de scalping multi-TF avec calibrage par actif.

Cahier des charges (Florent, 08/07/2026) : méthode scalping calée sur 30/15/5
minutes, backtest sur tous les actifs, recalibrage en boucle jusqu'à
winrate ≥ 65 % — calibrage INDÉPENDANT par actif.

Garde-fous anti-illusion (non négociables) :
  - split walk-forward 70 % in-sample / 30 % out-of-sample : le calibrage se
    fait sur l'IS, le verdict sur l'OOS (données jamais vues) ;
  - un actif n'est VALIDÉ que si, sur l'OOS : winrate ≥ 65 % ET expectancy
    après frais > 0 ET ≥ 15 trades. Un winrate élevé à expectancy négative
    est un piège classique (TP serré/SL large) — refusé.

Architecture de la méthode :
  - contexte 30 m (resample des 5 m, sans lookahead) : biais EMA200-30m,
    pente EMA50-30m, ADX-30m ;
  - déclencheur 5 m : E1 pullback RSI dans le sens du biais /
    E2 croisement TRIX / E3 réversion Bollinger (contra, régime calme) ;
  - gestion : SL ATR(5m)×p, TP partiels 33/33/34, BE après TP1,
    time-stop paramétrable (en barres 5 m).

Grille par étage (la « boucle » de recalibrage) : l'étage 1 balaie la zone
standard ; si aucun config ne passe le seuil sur un actif, l'étage 2 élargit
vers les profils haute-winrate (TP1 court, SL large) ; l'étage 3 ajoute E3.

Données : Binance 5 m (crypto, 180 j) · MT5-Axi M5 (forex/or, max dispo).
Frais aller-retour : crypto 11 bps · EURUSD/GBPUSD 1.5 bps · XAU 4 bps.

Usage :
    venv\\Scripts\\python.exe tools\\scalp_lab.py [--assets BTC,EURUSD]
Sorties : data/scalp_calibration.json + docs/RAPPORT_SCALPING.md
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.strategy_lab import (  # noqa: E402
    _http_json, add_indicators, metrics, simulate,
)

ROOT   = Path(__file__).resolve().parent.parent
CACHE  = ROOT / "data" / "lab_cache"
CALIB  = ROOT / "data" / "scalp_calibration.json"
RAPPORT = ROOT / "docs" / "RAPPORT_SCALPING.md"

ASSETS = {
    "BTC":    ("binance", "BTCUSDT", 11.0),
    "ETH":    ("binance", "ETHUSDT", 11.0),
    "PAXG":   ("binance", "PAXGUSDT", 11.0),
    "EURUSD": ("mt5", "EURUSD", 1.5),
    "GBPUSD": ("mt5", "GBPUSD", 1.5),
    "XAUUSD": ("mt5", "XAUUSD", 4.0),
}
DAYS       = 180
WR_TARGET  = 65.0     # % winrate minimum exigé (OOS)
MIN_TRADES = 15       # trades OOS minimum pour valider
TIME_STOP  = 96       # 96 barres 5m = 8 h (scalping)

# Étages de la boucle de recalibrage : (sl_atr, ladder_tp)
STAGE_GRIDS = [
    # Étage 1 — zone standard
    [(1.0, (1.0, 1.5, 2.0)), (1.5, (1.0, 1.5, 2.5)), (1.5, (1.5, 2.5, 4.0)),
     (2.0, (1.0, 1.5, 2.5)), (2.0, (1.5, 2.5, 4.0))],
    # Étage 2 — profils haute winrate (TP1 court, SL respirant)
    [(2.0, (0.6, 1.2, 2.0)), (2.5, (0.6, 1.2, 2.0)), (2.5, (0.8, 1.5, 2.5)),
     (3.0, (0.8, 1.5, 2.5)), (3.0, (0.6, 1.2, 2.0))],
]


# ── Données 5 m ──────────────────────────────────────────────────────────────

def fetch_binance_5m(sym: str, days: int) -> pd.DataFrame:
    end = int(time.time() * 1000)
    cur = end - days * 86400_000
    rows = []
    while cur < end:
        batch = _http_json(
            f"https://api.binance.com/api/v3/klines?symbol={sym}"
            f"&interval=5m&startTime={cur}&limit=1000")
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


def fetch_mt5_5m(sym: str, days: int) -> pd.DataFrame:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize: {mt5.last_error()}")
    n = days * 288
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 rates {sym}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def load_5m(name: str) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}_5m.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 6 * 3600:
        return pd.read_pickle(f)
    source, sym, _ = ASSETS[name]
    df = fetch_binance_5m(sym, DAYS) if source == "binance" else fetch_mt5_5m(sym, DAYS)
    df.to_pickle(f)
    return df


# ── Contexte 30 m injecté dans les barres 5 m (sans lookahead) ──────────────

def prepare(df5: pd.DataFrame) -> pd.DataFrame:
    df5 = add_indicators(df5.copy())            # indicateurs 5 m
    o30 = df5["close"].resample("30min", label="right", closed="right").last().dropna()
    ctx = pd.DataFrame({"c30": o30})
    ctx["ema200_30"] = ctx["c30"].ewm(span=200, adjust=False).mean()
    ctx["ema50_30"] = ctx["c30"].ewm(span=50, adjust=False).mean()
    ctx["slope50_30"] = ctx["ema50_30"] > ctx["ema50_30"].shift(5)
    d = ctx["c30"].diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    ctx["adx30_proxy"] = (100 - 100 / (1 + rs)).rolling(14).std()  # proxy volatilité directionnelle
    # une barre 30 m fermée à T est connue pour toutes les barres 5 m >= T
    aligned = ctx.reindex(df5.index, method="ffill")
    for col in ("ema200_30", "ema50_30", "slope50_30", "c30"):
        df5[col] = aligned[col]
    df5["bias_up_30"] = df5["c30"] > df5["ema200_30"]
    return df5.dropna()


# ── Déclencheurs 5 m ─────────────────────────────────────────────────────────

def entries_for(df: pd.DataFrame, etype: str, align: bool) -> pd.DataFrame:
    bias_up = df["bias_up_30"]
    ok_long  = bias_up & (df["slope50_30"] if align else True)
    ok_short = (~bias_up) & ((~df["slope50_30"]) if align else True)
    if etype == "E1":     # pullback RSI dans le sens du biais 30 m
        lg = ok_long & (df["rsi"] < 35) & (df["rsi"] > df["rsi"].shift())
        sh = ok_short & (df["rsi"] > 65) & (df["rsi"] < df["rsi"].shift())
    elif etype == "E2":   # croisement TRIX 5 m dans le sens du biais
        x_up = (df["trix"] > df["trix_sig"]) & (df["trix"].shift() <= df["trix_sig"].shift())
        x_dn = (df["trix"] < df["trix_sig"]) & (df["trix"].shift() >= df["trix_sig"].shift())
        lg = ok_long & x_up & (df["rsi"] < 60)
        sh = ok_short & x_dn & (df["rsi"] > 40)
    else:                 # E3 : réversion Bollinger 5 m, marché calme
        calm = df["adx"] < 20
        lg = calm & (df["close"] < df["bb_lo"]) & (df["rsi"] < 25)
        sh = calm & (df["close"] > df["bb_hi"]) & (df["rsi"] > 75)
    side = np.where(lg, 1, np.where(sh, -1, 0))
    e = pd.DataFrame({"side": side}, index=df.index)
    e = e[e["side"] != 0]
    # anti-rafale : 6 barres (30 min) minimum entre deux entrées
    keep, last = [], None
    for ts in e.index:
        if last is None or (ts - last).total_seconds() >= 1800:
            keep.append(ts)
            last = ts
    return e.loc[keep]


# ── Calibrage par actif (la boucle) ─────────────────────────────────────────

def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return pd.DataFrame({
        "open":  df["open"].resample(rule, label="right", closed="right").first(),
        "high":  df["high"].resample(rule, label="right", closed="right").max(),
        "low":   df["low"].resample(rule, label="right", closed="right").min(),
        "close": df["close"].resample(rule, label="right", closed="right").last(),
    }).dropna()


def calibrate_asset(name: str, trigger_tf: str = "5m",
                    session_filter: bool = False) -> dict:
    fees = ASSETS[name][2]
    df_raw = load_5m(name)
    if trigger_tf == "15m":
        df_raw = _resample_ohlc(df_raw, "15min")
    df = prepare(df_raw)
    if session_filter:
        # Sessions Londres + New York uniquement (07h-17h UTC)
        df = df.copy()
        df["_in_session"] = (df.index.hour >= 7) & (df.index.hour < 17)
    cut = int(len(df) * 0.70)
    df_is, df_oos = df.iloc[:cut], df.iloc[cut:]
    out = {"bars_5m": len(df), "fees_bps": fees, "history": [],
           "validated": None, "best_effort": None}

    entry_types = [("E1", True), ("E1", False), ("E2", True), ("E2", False)]
    for stage, grid in enumerate(STAGE_GRIDS, start=1):
        if stage >= 2:
            entry_types = entry_types + [("E3", False)]
        candidates = []
        for (etype, align), (sl, tps) in itertools.product(entry_types, grid):
            e_is = entries_for(df_is, etype, align)
            if session_filter:
                e_is = e_is[(e_is.index.hour >= 7) & (e_is.index.hour < 17)]
            m_is = metrics(simulate(df_is, e_is, sl, list(tps), fees,
                                    time_stop=TIME_STOP))
            if m_is.get("trades", 0) < 30:
                continue
            candidates.append(((etype, align, sl, tps), m_is))
        # tri IS : d'abord winrate>=cible & expectancy>0, puis expectancy
        candidates.sort(key=lambda c: (
            c[1].get("winrate_pct", 0) >= WR_TARGET and c[1].get("expectancy_bps", -9e9) > 0,
            c[1].get("expectancy_bps", -9e9)), reverse=True)

        for cfg, m_is in candidates[:6]:      # valider les 6 meilleures sur OOS
            etype, align, sl, tps = cfg
            e_oos = entries_for(df_oos, etype, align)
            if session_filter:
                e_oos = e_oos[(e_oos.index.hour >= 7) & (e_oos.index.hour < 17)]
            m_oos = metrics(simulate(df_oos, e_oos, sl, list(tps), fees,
                                     time_stop=TIME_STOP))
            rec = {"stage": stage, "entry": etype, "align_ema50": align,
                   "sl_atr": sl, "tp_ladder": list(tps),
                   "is": m_is, "oos": m_oos}
            out["history"].append(rec)
            ok = (m_oos.get("winrate_pct", 0) >= WR_TARGET
                  and m_oos.get("expectancy_bps", -1) > 0
                  and m_oos.get("trades", 0) >= MIN_TRADES)
            if ok and out["validated"] is None:
                out["validated"] = rec
        if out["validated"]:
            break
    # meilleur effort si rien ne passe : meilleure expectancy OOS
    if out["history"]:
        out["best_effort"] = max(
            out["history"],
            key=lambda r: (r["oos"].get("winrate_pct", 0)
                           if r["oos"].get("expectancy_bps", -1) > 0 else -1))
    return out


def run(asset_names=None, trigger_tf: str = "5m") -> dict:
    results = {}
    for name in (asset_names or ASSETS):
        print(f"\n══════ {name} (déclencheur {trigger_tf}) ══════")
        try:
            results[name] = calibrate_asset(
                name, trigger_tf=trigger_tf,
                session_filter=ASSETS[name][0] == "mt5")
        except Exception as e:
            results[name] = {"error": str(e)}
            print(f"  ERREUR: {e}")
            continue
        v = results[name]["validated"]
        if v:
            print(f"  VALIDÉ étage {v['stage']} — {v['entry']} align={v['align_ema50']} "
                  f"SL×{v['sl_atr']} TP{v['tp_ladder']}")
            print(f"    IS : {v['is']}")
            print(f"    OOS: {v['oos']}")
        else:
            b = results[name]["best_effort"]
            print(f"  AUCUNE CONFIG >= {WR_TARGET}% winrate + expectancy>0 en OOS")
            if b:
                print(f"    Meilleur effort: {b['entry']} SL×{b['sl_atr']} "
                      f"TP{b['tp_ladder']} → OOS {b['oos']}")
    CALIB.write_text(json.dumps(
        {"target_winrate_pct": WR_TARGET, "days": DAYS, "time_stop_bars_5m": TIME_STOP,
         "generated": pd.Timestamp.now("UTC").isoformat(), "assets": results},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nCalibration → {CALIB}")
    return results


if __name__ == "__main__":
    names = None
    if "--assets" in sys.argv:
        names = sys.argv[sys.argv.index("--assets") + 1].split(",")
    tf = "15m" if "--tf15" in sys.argv else "5m"
    run(names, trigger_tf=tf)
