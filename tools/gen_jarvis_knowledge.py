"""tools/gen_jarvis_knowledge.py — Génère le pack de connaissance « vivant » de
Titanium pour JARVIS.

Produit C:\\Program Files\\JARVIS\\knowledge\\TITANIUM_CONTEXT.md : une partie
ARCHITECTURE curée (stable) + une partie ÉTAT VIVANT régénérée depuis la config
et les fichiers de données (panier swing, scan d'opportunités, forex, garde-fous)
+ optionnellement l'état paper live via l'API. Objectif : faire de JARVIS un
expert de Titanium qui ne devient jamais périmé.

Usage :
    venv\\Scripts\\python.exe tools\\gen_jarvis_knowledge.py
Appelé aussi par l'endpoint POST /context/regen (api/context_routes.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JARVIS_KNOWLEDGE = Path(r"C:\Program Files\JARVIS\knowledge")
OUT = JARVIS_KNOWLEDGE / "TITANIUM_CONTEXT.md"


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _live_api() -> dict:
    """État paper live via l'API (best-effort, timeout court)."""
    out = {}
    try:
        import urllib.request
        for key, path in (("paper", "/paper/stats"), ("swing", "/swing/status"),
                          ("forex", "/forex/status"), ("opp", "/opportunities/status"),
                          ("cortex", "/cortex/snapshot")):     # perception unifiée (axe fusion Hermes)
            try:
                with urllib.request.urlopen(f"http://localhost:8090{path}", timeout=3) as r:
                    out[key] = json.loads(r.read().decode("utf-8"))
            except Exception:
                pass
    except Exception:
        pass
    return out


def build_markdown() -> str:
    from utils.config import (
        SWING_LIVE_SYMBOLS, SWING_CAPITAL, SWING_RISK_PCT, FOREX_SYMBOLS,
        FOREX_MONITOR_SYMBOLS, OPP_SCAN_HOUR_UTC, OPP_PERSIST_DAYS,
        OPP_LOOKBACK_DAYS, OPP_MIN_POTENTIAL, SCORE_MIN_REQUIRED, SYMBOLS,
    )
    cfg = _load_json(ROOT / "data" / "asset_configs.json").get("assets", {})
    auto = _load_json(ROOT / "data" / "swing_auto_configs.json").get("assets", {})
    opp = _load_json(ROOT / "data" / "opportunities.json")
    live = _live_api()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    L = []
    A = L.append
    A(f"# TITANIUM v12 — Pack de connaissance expert (pour JARVIS)")
    A(f"\n*Régénéré le {now}. Ce fichier est produit automatiquement par "
      f"`tools/gen_jarvis_knowledge.py` — ne pas éditer à la main.*\n")

    # CORTEX : perception unifiée du cerveau de trading (fusion Hermes, afférent, lecture seule).
    cortex = live.get("cortex") or {}
    if cortex.get("engines"):
        A("## Cortex — état du cerveau de trading (perception unifiée)")
        A(f"Santé globale : **{cortex.get('overall_health','?')}** "
          f"(instant {cortex.get('ts','?')[:19]}). Chaque moteur observe ; **aucun ne décide "
          "d'ordre sans les garde-fous déterministes** (le cerveau propose, il ne tire jamais).")
        for name, h in cortex["engines"].items():
            extra = " · ".join(f"{k}={v}" for k, v in h.items()
                               if k not in ("health", "note", "last_cycle_at"))
            A(f"- **{name}** : `{h.get('health','?')}` — {extra}")
        A("")

    A("## Qui tu es")
    A("Tu es JARVIS, l'assistant EXPERT de Titanium v12, le bot de trading "
      "algorithmique de Florent. Tu connais son architecture, ses stratégies et "
      "son état en temps réel. Tu donnes ton avis, argumenté, en te basant sur "
      "les données ci-dessous et l'API live. Tu parles à Florent (français, "
      "concis). Règles d'or :")
    A("- **Tout est PAPER / données seulement.** Titanium n'envoie AUCUN ordre "
      "réel ; MT5 (compte Axi live) sert uniquement de flux de données. Ne laisse "
      "jamais entendre le contraire.")
    A("- **Pour toute modif de code**, tu ne modifies rien toi-même : tu proposes "
      "un patch (diff + justification) que Florent valide. Tu peux signaler "
      "failles et optimisations, classées par gravité.")
    A("- **Honnêteté sur l'incertitude** : petits échantillons, backtest ≠ fills "
      "réels, winrate élevé ≠ rentable après frais. Signale-le.")

    A("\n## Architecture (stable)")
    A("- **Bot** : Python/FastAPI, `C:\\Users\\flore\\Desktop\\v12\\main.py`, port "
      "**8090**, venv `venv\\Scripts\\python.exe`. Dashboard unifié servi sur / et "
      "recopié dans la fenêtre JARVIS.")
    A(f"- **Scoring** : `core/signal_engine.py` scanne les cryptos {list(SYMBOLS)} "
      f"toutes les 5 s, score SMC (EMA200, OB/FVG, BOS, RSI, ADX, TRIX, delta "
      f"volume, sweep de liquidité, carnet L2). Signal émis si score ≥ "
      f"{SCORE_MIN_REQUIRED}.")
    A("- **Paper trading** : `execution/paper_trading.py` (slippage, spread, frais, "
      "funding). TP1/TP2/TP3 → 33/33/34 %, SL au break-even après TP1.")
    A("- **Fundamentals** : score macro 0-100 (NewsAPI+GDELT+RSS) qui module/annule "
      "les signaux.")
    A("- **Moteur forex V3 (MT5-Axi)** : `core/forex_engine.py`, stratégie V3 sur "
      f"{FOREX_SYMBOLS} (H1, paper). Biais EMA200 + pente EMA50 alignée + croisement "
      "TRIX + pullback RSI ; SL=ATR×2 ; TP 1.5/2.5/4×ATR ; BE après TP1 ; time-stop "
      f"48 h. Surveillés data-seule : {FOREX_MONITOR_SYMBOLS}.")
    A("- **Moteur SWING** : `core/swing_engine.py`, paper, panier validé au **tester "
      "natif MT5** (fills réels 3,5 ans) + actifs auto-découverts. Chaque actif a SA "
      "config (SL/TP/align/RSI/TF/time-stop).")
    A("- **Optimiseur inversé** : `tools/asset_optimizer.py`. Pour CHAQUE actif "
      "cherche le style (scalp M15 / intraday H1 / swing H4) + variables qui "
      "maximisent la perf. Walk-forward 70/30, verdict sur OOS jamais vue. Conclusion "
      "clé : le **swing H4 domine**, le scalping n'est pas rentable après frais.")
    A(f"- **Scan d'opportunités** : `core/opportunity_scan.py`, QUOTIDIEN à "
      f"{OPP_SCAN_HOUR_UTC:02d}:00 UTC (ouverture Asie). Rebalaye les 141 actifs MT5 "
      f"+ porte de récence {OPP_LOOKBACK_DAYS} j. **Filtre de persistance** : un actif "
      f"doit ressortir {OPP_PERSIST_DAYS} scans consécutifs (potentiel ≥ "
      f"{OPP_MIN_POTENTIAL}) avant auto-intégration au moteur swing + alerte sonore.")
    A("- **Temps réel** : WS `/ws/realtime` (~5 Hz) — ticks MT5 à la ms + carnet L2 "
      "Binance (crypto). ⚠️ Axi ne diffuse PAS le DOM niveau 2 via MT5 (L1 seulement).")
    A("- **Garde-fou clé** : rien n'est tradé en réel. Passage à l'écriture = "
      "séquence forward paper → démo `order_send` → micro-lots, sur décision "
      "explicite de Florent uniquement.")

    A("\n## Stratégies & vocabulaire")
    A("- **V3** : biais EMA200 + pente EMA50 même sens (anti contre-mouvement) + "
      "croisement TRIX(15,9) + pullback RSI. SL ATR, ladder TP partiel, BE après TP1.")
    A("- **Walk-forward / OOS** : calibrage sur in-sample, verdict sur out-of-sample "
      "jamais vue. Un winrate élevé à expectancy négative = piège (TP serré/SL large).")
    A("- **Expectancy (bps/trade)**, **Profit Factor (PF)**, **Sharpe**, **swap/carry** "
      "(coût de portage overnight — a tué le CFD BTC), **DOM/L2** (profondeur de "
      "carnet), **SMC** (OB/FVG/BOS/sweep).")

    A("\n## ÉTAT VIVANT (régénéré)")
    if cfg:
        A("\n### Panier swing de base (validé tester natif)")
        A("| Actif | TF | SL×ATR | TP | PF réel | P&L natif 3½a |")
        A("|---|---|---|---|---|---|")
        for sym in SWING_LIVE_SYMBOLS:
            c = cfg.get(sym, {})
            nv = c.get("native_revalidation", {})
            A(f"| {sym} | {c.get('tf','?')} | {c.get('sl_atr','?')} | "
              f"{'/'.join(map(str,c.get('tp_ladder',[])))} | {nv.get('profit_factor','—')} | "
              f"{nv.get('net_pnl_eur','—')} € |")
    if auto:
        A("\n### Actifs auto-découverts (scan d'opportunités, paper)")
        for sym, c in auto.items():
            A(f"- **{sym}** {c.get('style')} {c.get('tf')} SL×{c.get('sl_atr')} "
              f"TP {'/'.join(map(str,c.get('tp_ladder',[])))} · potentiel {c.get('potential')}")
    if opp:
        A("\n### Dernier scan d'opportunités")
        A(f"- Dernier run : {opp.get('last_run','—')} · univers {opp.get('universe_size','—')} actifs")
        pend = opp.get("pending", [])
        if pend:
            A("- En observation (persistance) : " + ", ".join(
                f"{c['symbol']} ({c['streak']}/{OPP_PERSIST_DAYS})" for c in pend))
        nh = opp.get("new_hot", [])
        if nh:
            A("- Confirmés/intégrés : " + ", ".join(h["symbol"] for h in nh))
    if live:
        A("\n### État paper live (API, au moment de la génération)")
        p = live.get("paper", {})
        if p:
            A(f"- **Crypto paper** : equity {p.get('equity','—')} $, PnL "
              f"{p.get('total_pnl','—')} $, winrate {p.get('winrate_pct','—')} %, "
              f"trades {p.get('total_trades','—')}")
        sw = live.get("swing", {})
        if sw:
            A(f"- **Swing paper** : equity {sw.get('equity','—')} €, PnL "
              f"{sw.get('total_pnl_eur','—')} €, trades {sw.get('trades','—')}, "
              f"symboles {sw.get('symbols','—')}")
        fx = live.get("forex", {})
        if fx:
            A(f"- **Forex paper** : equity {fx.get('equity','—')} €, PnL "
              f"{fx.get('total_pnl_eur','—')} €, MT5 "
              f"{'connecté' if fx.get('mt5',{}).get('connected') else 'hors ligne'}")

    A("\n## Endpoints utiles (localhost:8090)")
    A("`/paper/stats` `/paper/positions` `/api/state` · `/forex/status` `/forex/optim` "
      "`/forex/backtests` · `/swing/status` `/swing/state` · `/opportunities/status` "
      "(POST `/opportunities/run`) · `/fundamentals/score` · WS `/ws/realtime` "
      "(ticks+L2) · `/context/expert` (ce contexte en JSON).")

    A("\n## Comment te comporter avec Florent")
    A("- Réponds court, à l'oral. Donne ton **avis** (ex : « je me méfierais de "
      "BCH-JPY, PF 99 = artéfact petit échantillon »).")
    A("- Sur grosse variation d'un actif, tu peux lancer une recherche web (profil "
      "Chrome dédié) et lui livrer un briefing.")
    A("- S'il te demande d'intervenir sur le code : lis, explique, et **propose un "
      "patch à valider** (jamais d'application autonome). Signale toute faille/"
      "optimisation dans un dossier d'anomalies.")
    return "\n".join(L)


def write() -> Path:
    JARVIS_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    md = build_markdown()
    OUT.write_text(md, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    p = write()
    print(f"Pack de connaissance écrit → {p} ({p.stat().st_size} octets)")
