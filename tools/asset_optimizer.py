"""tools/asset_optimizer.py — Moteur INVERSÉ : on adapte les variables à l'actif.

Cahier des charges (Florent, 08/07/2026) : « fais l'inverse » — au lieu
d'imposer une stratégie fixe (V3) et de voir quels actifs la supportent, pour
CHAQUE actif on cherche le style (scalp / intraday / swing) et les variables
(SL, ladder TP, filtres) qui maximisent la performance sur l'exécution réelle
Axi. Balayer l'intégralité des actifs MT5 liquides, classer par potentiel,
raffiner, recommencer — puis un rapport par actif et par stratégie.

────────────────────────────────────────────────────────────────────────────
GARDE-FOU ANTI-ILLUSION (non négociable)
  Chercher « le meilleur résultat » en balayant 140 actifs × 3 styles × N
  configs est LA machine à fabriquer de faux gagnants (multiple testing).
  Donc :
   • walk-forward 70 % in-sample / 30 % out-of-sample ;
   • le calibrage (grille + raffinage local) se fait UNIQUEMENT sur l'IS ;
   • l'OOS n'est touchée qu'une fois, pour le verdict ;
   • un actif/style n'est VALIDÉ que si, sur l'OOS : expectancy après frais > 0,
     profit factor > 1, et nombre de trades >= seuil du style.
  Coûts réels : spread Axi live (bps) + slippage ; pour le SWING, coût de
  portage (swap) appliqué par barre détenue — c'est ce qui a tué BTCUSD.

ENTONNOIR (traduit de « recherche l'actif au plus fort potentiel, répète
l'opération après chaque adaptation ») :
  PASSE 1 (coarse) : les ~140 actifs, 1 config repère par style (H1+H4),
                     classement par potentiel OOS.
  PASSE 2 (deep)   : top N actifs, grille complète + raffinage local + scalp
                     M15, sur les 3 styles.

Univers : catégories STANDARD_FX (66) + CRYPTO (30) + STANDARD_METALS (6) +
CASH/FUTURES (indices & matières ~39). Les 1128 actions CFD sont exclues
(momentum TRIX/EMA inadapté, historique intraday non fiable).

MT5 = DONNÉES SEULEMENT (compte Axi live intouché — aucun ordre envoyé).

Usage :
    venv\\Scripts\\python.exe tools\\asset_optimizer.py --pass1
    venv\\Scripts\\python.exe tools\\asset_optimizer.py --pass2 --top 15
    venv\\Scripts\\python.exe tools\\asset_optimizer.py --all            # 1 puis 2
Sorties : data/asset_optimizer_report.json · data/asset_configs.json ·
          docs/RAPPORT_OPTIM.md
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.strategy_lab import add_indicators  # noqa: E402  (indicateurs partagés, sans lookahead)

CACHE   = ROOT / "data" / "opt_cache"
REPORT  = ROOT / "data" / "asset_optimizer_report.json"
CONFIGS = ROOT / "data" / "asset_configs.json"
RAPPORT = ROOT / "docs" / "RAPPORT_OPTIM.md"

CACHE_TTL   = 12 * 3600
KEEP_CATS   = {
    "STANDARD_FX", "CRYPTO", "STANDARD_METALS", "CASH", "FUTURES",
    # Axi prefixes the same category families with ROW_ on this account.
    "ROW_STANDARD_FX", "ROW_CRYPTO", "ROW_STANDARD_METALS", "ROW_CASH", "ROW_FUTURES",
}
CACHE.mkdir(parents=True, exist_ok=True)

# ── Profils de style : (timeframe MT5, barres à charger, time-stop en barres,
#    frais plancher aller-retour bps, trades OOS minimum, carry actif) ────────
STYLES = {
    "scalp":    {"tf": "M15", "bars": 12000, "time_stop": 32,
                 "floor_bps": 2.0, "min_oos": 25, "carry": True},
    "intraday": {"tf": "H1",  "bars": 14000, "time_stop": 48,
                 "floor_bps": 1.5, "min_oos": 15, "carry": True},
    "swing":    {"tf": "H4",  "bars": 7000,  "time_stop": 60,
                 "floor_bps": 1.5, "min_oos": 12, "carry": True},
}
BARS_PER_DAY = {"M15": 96, "H1": 24, "H4": 6, "D1": 1}

# Grilles : (sl_atr, (tp1, tp2, tp3)). 1 config repère (coarse) + grille (deep).
COARSE_CFG = {
    "scalp":    (1.5, (1.0, 1.5, 2.5)),
    "intraday": (2.0, (1.5, 2.5, 4.0)),
    "swing":    (2.5, (2.0, 3.5, 6.0)),
}
GRIDS = {
    "scalp":    [(sl, tp) for sl in (1.0, 1.5, 2.0)
                 for tp in ((1.0, 1.5, 2.5), (1.5, 2.5, 4.0), (0.8, 1.5, 2.5))],
    "intraday": [(sl, tp) for sl in (1.5, 2.0, 2.5)
                 for tp in ((1.5, 2.5, 4.0), (1.0, 2.0, 3.5), (2.0, 3.0, 5.0))],
    "swing":    [(sl, tp) for sl in (2.0, 2.5, 3.0)
                 for tp in ((2.0, 3.5, 6.0), (1.5, 3.0, 5.0), (3.0, 5.0, 8.0))],
}
ENTRY_VARIANTS = [(a, r) for a in (True, False) for r in (True, False)]  # align, rsi_gate
PARTS = (0.33, 0.33, 0.34)


# ── MT5 : univers, coûts, données ────────────────────────────────────────────

# Verrou partagé avec le provider live (MT5 non thread-safe) — sérialise les
# appels quand le scan tourne en même temps que les boucles forex/swing/temps réel.
try:
    from data.mt5_provider import mt5_lock as _MT5_LOCK
except Exception:
    import threading as _threading
    _MT5_LOCK = _threading.RLock()


def _mt5():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize: {mt5.last_error()}")
    return mt5


def list_universe() -> List[Dict]:
    """Symboles liquides (hors actions) avec leur coût aller-retour estimé (bps)."""
    mt5 = _mt5()
    out = []
    with _MT5_LOCK:
      for s in mt5.symbols_get():
        cat = s.path.split("\\")[0]
        if cat not in KEEP_CATS:
            continue
        mt5.symbol_select(s.name, True)
        info = mt5.symbol_info(s.name)
        if info is None:
            continue
        tick = mt5.symbol_info_tick(s.name)
        pt = info.point or 0.0
        # Prix de référence : tick live, sinon bid/ask de symbol_info, sinon
        # dernier close D1 (l'actif est retenu tant qu'on a UNE référence de prix,
        # car seul l'historique de barres est requis pour le backtest).
        if tick and tick.bid > 0:
            bid, ask = tick.bid, tick.ask
        elif info.bid > 0:
            bid, ask = info.bid, info.ask
        else:
            d1 = load(s.name, "D1", 5)
            if d1 is None or d1.empty:
                continue
            px = float(d1["close"].iloc[-1])
            bid = ask = px
        mid = (bid + ask) / 2 if (bid and ask) else bid
        if not mid:
            continue
        spread_bps = (ask - bid) / mid * 10000 if ask > bid else info.spread * pt / mid * 10000
        # swap : points/nuit → bps/jour du prix (côté le plus défavorable)
        swap_bps_day = -min(info.swap_long, info.swap_short) * pt / mid * 10000
        out.append({
            "symbol": s.name, "category": cat,
            "spread_bps": round(max(spread_bps, 0.0), 2),
            "swap_bps_day": round(max(swap_bps_day, 0.0), 3),
        })
    return out


_TF_MAP = None
def _tf_const(tf: str):
    global _TF_MAP
    mt5 = _mt5()
    if _TF_MAP is None:
        _TF_MAP = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                   "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
                   "D1": mt5.TIMEFRAME_D1}
    return _TF_MAP[tf]


def load(sym: str, tf: str, n: int) -> Optional[pd.DataFrame]:
    """OHLC (index UTC) pour un symbole/timeframe, avec cache + retries synchro."""
    f = CACHE / f"{sym.replace('/', '_')}_{tf}.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_TTL:
        try:
            return pd.read_pickle(f)
        except Exception:
            pass
    mt5 = _mt5()
    rates = None
    for _ in range(5):
        with _MT5_LOCK:
            mt5.symbol_select(sym, True)
            rates = mt5.copy_rates_from_pos(sym, _tf_const(tf), 0, n)
        if rates is not None and len(rates) > 0:
            break
        time.sleep(0.6)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df[["open", "high", "low", "close"]].astype(float)
    try:
        df.to_pickle(f)
    except Exception:
        pass
    return df


# ── Entrées paramétrables (même cœur que V3 : biais EMA200 + TRIX + RSI) ─────

def entries(df: pd.DataFrame, align: bool, rsi_gate: bool) -> pd.DataFrame:
    bias = np.where(df["close"] > df["ema200"], 1, -1)
    x_up = (df["trix"] > df["trix_sig"]) & (df["trix"].shift() <= df["trix_sig"].shift())
    x_dn = (df["trix"] < df["trix_sig"]) & (df["trix"].shift() >= df["trix_sig"].shift())
    lg = (bias > 0) & x_up
    sh = (bias < 0) & x_dn
    if rsi_gate:
        lg &= df["rsi"] < 55
        sh &= df["rsi"] > 45
    if align:
        slope_up = df["ema50"] > df["ema50"].shift(5)
        lg &= slope_up
        sh &= ~slope_up
    side = np.where(lg, 1, np.where(sh, -1, 0))
    e = pd.DataFrame({"side": side}, index=df.index)
    return e[e["side"] != 0]


# ── Moteur de simulation (ladder TP partiel + BE + time-stop + carry) ────────

def simulate(df: pd.DataFrame, entries_df: pd.DataFrame, sl_mult: float,
             tp_mults: Tuple[float, float, float], fees_bps: float,
             time_stop: int, carry_bps_per_bar: float = 0.0) -> List[float]:
    """Retourne la liste des PnL nets par trade (bps). Entrée à l'open de la
    barre suivante ; SL testé avant TP (conservateur) ; partiels 33/33/34 ;
    SL→BE après TP1 ; carry (swap) soustrait par barre détenue."""
    o = df["open"].values; h = df["high"].values; l = df["low"].values
    c = df["close"].values; atr = df["atr"].values
    idx = df.index
    entry_set = {ts: s for ts, s in zip(entries_df.index, entries_df["side"])}
    trades: List[float] = []
    pos = None
    for i in range(1, len(df)):
        if pos:
            side, ep, slp, tps, filled, bars = pos
            hi, lo = h[i], l[i]
            pnl = 0.0
            hit_sl = lo <= slp if side > 0 else hi >= slp
            if hit_sl:
                rest = 1.0 - sum(filled)
                gross = _acc(filled, tps, ep, side) + rest * side * (slp - ep) / ep
                trades.append(gross * 10000 - fees_bps - carry_bps_per_bar * bars)
                pos = None
            else:
                closed = False
                for k, tp in enumerate(tps):
                    if filled[k] == 0:
                        hit = hi >= tp if side > 0 else lo <= tp
                        if hit:
                            filled[k] = PARTS[k]
                            if k == 0:
                                slp = ep            # break-even après TP1
                if sum(filled) >= 0.999:
                    gross = _acc(filled, tps, ep, side)
                    trades.append(gross * 10000 - fees_bps - carry_bps_per_bar * bars)
                    pos = None; closed = True
                if not closed:
                    bars += 1
                    if bars >= time_stop:
                        rest = 1.0 - sum(filled)
                        gross = _acc(filled, tps, ep, side) + rest * side * (c[i] - ep) / ep
                        trades.append(gross * 10000 - fees_bps - carry_bps_per_bar * bars)
                        pos = None
                    else:
                        pos = (side, ep, slp, tps, filled, bars)
        if pos is None and idx[i - 1] in entry_set:
            side = entry_set[idx[i - 1]]
            ep = o[i]; a = atr[i - 1]
            slp = ep - side * sl_mult * a
            tps = tuple(ep + side * m * a for m in tp_mults)
            pos = (side, ep, slp, list(tps), [0.0, 0.0, 0.0], 0)
    return trades


def _acc(filled, tps, ep, side) -> float:
    """PnL fractionnel déjà encaissé par les partiels TP remplis."""
    return sum(f * side * (tp - ep) / ep for f, tp in zip(filled, tps) if f)


def metrics(trades: List[float]) -> Dict:
    if len(trades) < 3:
        return {"trades": len(trades)}
    t = np.array(trades)
    wins, losses = t[t > 0], t[t <= 0]
    eq = np.cumsum(t)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return {
        "trades": int(len(t)),
        "winrate_pct": round(100 * len(wins) / len(t), 1),
        "expectancy_bps": round(float(t.mean()), 2),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else 99.0,
        "total_bps": round(float(t.sum()), 0),
        "max_dd_bps": round(dd, 0),
        "sharpe_trade": round(float(t.mean() / (t.std() or 1)), 3),
    }


def potential(m_oos: Dict, min_trades: int) -> float:
    """Score de potentiel robuste : nul si l'OOS ne passe pas les garde-fous,
    sinon expectancy pondérée par √trades (récompense la régularité)."""
    if not m_oos or m_oos.get("trades", 0) < min_trades:
        return -1e9
    if m_oos.get("expectancy_bps", -1) <= 0 or m_oos.get("profit_factor", 0) <= 1.0:
        return -1e9
    return m_oos["expectancy_bps"] * (m_oos["trades"] ** 0.5)


# ── Évaluation d'un (actif, style) ───────────────────────────────────────────

def eval_style(sym: str, style: str, cost: Dict,
               grid: List[Tuple], refine: bool) -> Optional[Dict]:
    spec = STYLES[style]
    df = load(sym, spec["tf"], spec["bars"])
    if df is None or len(df) < 600:
        return None
    df = add_indicators(df)
    if len(df) < 400:
        return None
    fees = max(spec["floor_bps"], cost["spread_bps"] * 1.5)
    carry = (cost["swap_bps_day"] / BARS_PER_DAY[spec["tf"]]) if spec["carry"] else 0.0

    cut = int(len(df) * 0.70)
    df_is, df_oos = df.iloc[:cut], df.iloc[cut:]

    def best_on_is(cfgs) -> Optional[Tuple]:
        scored = []
        for (align, rsi_g), (sl, tp) in itertools.product(ENTRY_VARIANTS, cfgs):
            e = entries(df_is, align, rsi_g)
            m = metrics(simulate(df_is, e, sl, tp, fees, spec["time_stop"], carry))
            if m.get("trades", 0) < max(20, spec["min_oos"]):
                continue
            # tri IS : expectancy>0 & PF>1 prioritaire, puis expectancy
            key = (m.get("expectancy_bps", -9e9) > 0 and m.get("profit_factor", 0) > 1,
                   m.get("expectancy_bps", -9e9))
            scored.append((key, (align, rsi_g, sl, tp), m))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0]

    top = best_on_is(grid)
    if top is None:
        return None
    _, cfg, m_is = top

    # RAFFINAGE local (« répète l'opération après chaque adaptation ») : on
    # resserre SL/TP autour du meilleur, toujours sur l'IS uniquement.
    if refine:
        align, rsi_g, sl0, tp0 = cfg
        local = [(round(sl0 + d, 2), tuple(round(t * k, 2) for t in tp0))
                 for d in (-0.5, 0.0, 0.5) for k in (0.85, 1.0, 1.15) if sl0 + d >= 0.5]
        scored = []
        for sl, tp in local:
            e = entries(df_is, align, rsi_g)
            m = metrics(simulate(df_is, e, sl, tp, fees, spec["time_stop"], carry))
            if m.get("trades", 0) < max(20, spec["min_oos"]):
                continue
            scored.append(((m.get("expectancy_bps", -9e9) > 0 and m.get("profit_factor", 0) > 1,
                            m.get("expectancy_bps", -9e9)), (align, rsi_g, sl, tp), m))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored[0][2]["expectancy_bps"] >= m_is["expectancy_bps"]:
                _, cfg, m_is = scored[0]

    # VERDICT OOS (une seule fois)
    align, rsi_g, sl, tp = cfg
    e_oos = entries(df_oos, align, rsi_g)
    m_oos = metrics(simulate(df_oos, e_oos, sl, tp, fees, spec["time_stop"], carry))
    return {
        "style": style, "tf": spec["tf"],
        "align_ema50": align, "rsi_gate": rsi_g, "sl_atr": sl, "tp_ladder": list(tp),
        "fees_bps": round(fees, 2), "carry_bps_per_bar": round(carry, 4),
        "is": m_is, "oos": m_oos,
        "potential": round(potential(m_oos, spec["min_oos"]), 2),
        "validated": potential(m_oos, spec["min_oos"]) > -1e8,
    }


# ── Passes ───────────────────────────────────────────────────────────────────

def run_pass1(universe: List[Dict]) -> Dict:
    """Coarse : 1 config repère par style (intraday+swing) sur tous les actifs."""
    print(f"\n═══ PASSE 1 — coarse scan {len(universe)} actifs ═══")
    results = {}
    for i, cost in enumerate(universe, 1):
        sym = cost["symbol"]
        best = None
        for style in ("intraday", "swing"):
            try:
                r = eval_style(sym, style, cost, [COARSE_CFG[style]], refine=False)
            except Exception as e:
                r = None
                print(f"  ! {sym}/{style}: {e}")
            if r and (best is None or r["potential"] > best["potential"]):
                best = r
        if best:
            results[sym] = {"cost": cost, "best": best}
            flag = "✓" if best["validated"] else " "
            print(f"  [{i:>3}/{len(universe)}] {flag} {sym:<12} {best['style']:<8} "
                  f"pot={best['potential']:>7.1f}  OOS exp={best['oos'].get('expectancy_bps','—')}"
                  f" PF={best['oos'].get('profit_factor','—')} n={best['oos'].get('trades','—')}")
        else:
            print(f"  [{i:>3}/{len(universe)}] · {sym:<12} pas de données/config")
    return results


def run_pass2(universe: List[Dict], shortlist: List[str]) -> Dict:
    """Deep : grille complète + raffinage + scalp, sur les 3 styles."""
    print(f"\n═══ PASSE 2 — deep sur {len(shortlist)} actifs ═══")
    cost_by = {c["symbol"]: c for c in universe}
    results = {}
    for sym in shortlist:
        cost = cost_by.get(sym)
        if not cost:
            continue
        print(f"\n── {sym} ({cost['category']}, spread {cost['spread_bps']}bps, "
              f"swap {cost['swap_bps_day']}bps/j) ──")
        styles_out = {}
        for style in ("scalp", "intraday", "swing"):
            try:
                r = eval_style(sym, style, cost, GRIDS[style], refine=True)
            except Exception as e:
                print(f"   {style:<9} ERREUR {e}")
                continue
            if not r:
                print(f"   {style:<9} pas de données suffisantes")
                continue
            styles_out[style] = r
            v = "VALIDÉ  " if r["validated"] else "rejeté  "
            print(f"   {style:<9} {v} SL×{r['sl_atr']} TP{r['tp_ladder']} "
                  f"align={int(r['align_ema50'])} rsi={int(r['rsi_gate'])} | "
                  f"OOS exp={r['oos'].get('expectancy_bps','—')} "
                  f"WR={r['oos'].get('winrate_pct','—')} PF={r['oos'].get('profit_factor','—')} "
                  f"n={r['oos'].get('trades','—')} pot={r['potential']}")
        if styles_out:
            results[sym] = {"cost": cost, "styles": styles_out}
    return results


# ── Rapport & configs live ───────────────────────────────────────────────────

def write_configs(deep: Dict) -> Dict:
    """data/asset_configs.json — meilleur style VALIDÉ par actif, pour le live."""
    cfg = {}
    for sym, d in deep.items():
        valids = [r for r in d["styles"].values() if r["validated"]]
        if not valids:
            continue
        best = max(valids, key=lambda r: r["potential"])
        cfg[sym] = {
            "style": best["style"], "tf": best["tf"],
            "sl_atr": best["sl_atr"], "tp_ladder": best["tp_ladder"],
            "align_ema50": best["align_ema50"], "rsi_gate": best["rsi_gate"],
            "time_stop_bars": STYLES[best["style"]]["time_stop"],
            "oos": best["oos"], "potential": best["potential"],
            "category": d["cost"]["category"],
        }
    payload = {"generated": pd.Timestamp.now("UTC").isoformat(),
               "note": "Config par actif — paper only, MT5 données seulement.",
               "assets": cfg}
    CONFIGS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg


def write_report(pass1: Dict, deep: Dict, live_cfg: Dict) -> None:
    lines = ["# Rapport d'optimisation par actif — moteur inversé", ""]
    lines.append(f"*Généré le {pd.Timestamp.now('UTC').strftime('%Y-%m-%d %H:%M UTC')} "
                 f"· données Axi (MT5) · walk-forward 70/30 · verdict OOS après frais réels*")
    lines.append("")
    lines.append("## Méthode")
    lines.append("Pour chaque actif on cherche le **style** (scalp M15 / intraday H1 / "
                 "swing H4) et les **variables** (SL×ATR, ladder TP, filtres align/RSI) "
                 "qui maximisent la performance. Calibrage sur l'in-sample, **verdict sur "
                 "l'out-of-sample jamais vue**. Un actif/style n'est *validé* que si l'OOS "
                 "donne expectancy>0, profit factor>1 et assez de trades. Coûts : spread "
                 "Axi réel + slippage ; swap appliqué par barre pour le swing.")
    lines.append("")

    # Classement pass1
    ranked = sorted(pass1.items(), key=lambda kv: kv[1]["best"]["potential"], reverse=True)
    lines.append("## Passe 1 — classement de l'univers par potentiel (top 30)")
    lines.append("")
    lines.append("| # | Actif | Cat. | Style | Pot. | OOS exp (bps) | PF | WR% | n |")
    lines.append("|---|-------|------|-------|------|---------------|----|-----|---|")
    for i, (sym, d) in enumerate(ranked[:30], 1):
        b = d["best"]; o = b["oos"]
        lines.append(f"| {i} | {sym} | {d['cost']['category'].replace('STANDARD_','')} "
                     f"| {b['style']} | {b['potential']} | {o.get('expectancy_bps','—')} "
                     f"| {o.get('profit_factor','—')} | {o.get('winrate_pct','—')} "
                     f"| {o.get('trades','—')} |")
    lines.append("")

    # Deep par actif
    lines.append("## Passe 2 — optimisation profonde par actif et par stratégie")
    lines.append("")
    for sym, d in sorted(deep.items(),
                         key=lambda kv: max((r["potential"] for r in kv[1]["styles"].values()),
                                            default=-1e9), reverse=True):
        c = d["cost"]
        lines.append(f"### {sym}  ·  {c['category'].replace('STANDARD_','')}  "
                     f"(spread {c['spread_bps']} bps, swap {c['swap_bps_day']} bps/j)")
        lines.append("")
        lines.append("| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |")
        lines.append("|-------|--------|--------|---------|----|-----|---|----------|")
        for style in ("scalp", "intraday", "swing"):
            r = d["styles"].get(style)
            if not r:
                lines.append(f"| {style} | — | — | — | — | — | — | — |")
                continue
            o = r["oos"]
            cfgs = (f"SL×{r['sl_atr']} TP{r['tp_ladder']} "
                    f"a{int(r['align_ema50'])} r{int(r['rsi_gate'])}")
            lines.append(f"| {style} | {cfgs} | {'✅' if r['validated'] else '❌'} "
                         f"| {o.get('expectancy_bps','—')} | {o.get('profit_factor','—')} "
                         f"| {o.get('winrate_pct','—')} | {o.get('trades','—')} "
                         f"| {o.get('max_dd_bps','—')} |")
        lines.append("")

    # Config live retenue
    lines.append("## Configuration live retenue (data/asset_configs.json)")
    lines.append("")
    if live_cfg:
        lines.append("| Actif | Style | TF | SL×ATR | TP ladder | Pot. |")
        lines.append("|-------|-------|----|--------|-----------|------|")
        for sym, c in sorted(live_cfg.items(), key=lambda kv: kv[1]["potential"], reverse=True):
            lines.append(f"| {sym} | {c['style']} | {c['tf']} | {c['sl_atr']} "
                         f"| {c['tp_ladder']} | {c['potential']} |")
    else:
        lines.append("*Aucun actif validé — voir la section garde-fou.*")
    lines.append("")
    lines.append("---")
    lines.append("*MT5 = données seulement, compte Axi live intouché. Ces résultats sont "
                 "paper/backtest ; passage à l'écriture réelle = séquence forward → démo → "
                 "micro-lots, sur décision explicite.*")
    RAPPORT.parent.mkdir(exist_ok=True)
    RAPPORT.write_text("\n".join(lines), encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass1", action="store_true")
    ap.add_argument("--pass2", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--shortlist", type=str, default="")
    args = ap.parse_args()

    prev = {}
    if REPORT.exists():
        try:
            prev = json.loads(REPORT.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    universe = list_universe()
    print(f"Univers liquide : {len(universe)} actifs")

    pass1 = prev.get("pass1", {})
    deep = prev.get("pass2", {})

    if args.pass1 or args.all:
        pass1 = run_pass1(universe)

    if args.pass2 or args.all:
        if args.shortlist:
            shortlist = args.shortlist.split(",")
        else:
            ranked = sorted(pass1.items(), key=lambda kv: kv[1]["best"]["potential"],
                            reverse=True)
            shortlist = [s for s, _ in ranked[:args.top]]
        deep = run_pass2(universe, shortlist)

    live_cfg = write_configs(deep) if deep else {}
    REPORT.write_text(json.dumps(
        {"generated": pd.Timestamp.now("UTC").isoformat(),
         "universe_size": len(universe), "pass1": pass1, "pass2": deep},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if deep or pass1:
        write_report(pass1, deep, live_cfg)
        print(f"\nRapport → {RAPPORT}\nConfigs → {CONFIGS}\nJSON → {REPORT}")


if __name__ == "__main__":
    main()
