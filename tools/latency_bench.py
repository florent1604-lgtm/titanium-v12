"""tools/latency_bench.py — Benchmark de latence multi-plateformes.

Objectif : déterminer quelle plateforme publie les variations de prix EN
PREMIER, pour disposer d'un signal d'avance par rapport au broker (Axi).

Deux mesures complémentaires par run :
1. **Latence de transport** : (heure locale de réception) − (timestamp
   d'événement de l'exchange). Comparable entre plateformes car le biais
   d'horloge locale est commun à toutes.
2. **Lead/lag inter-plateformes** : cross-corrélation des rendements sur une
   grille de 200 ms. Si le meilleur lag entre A et B est positif, A imprime
   les mouvements avant B (avance en ms).

Plateformes : Binance, Bybit, OKX, Coinbase, Kraken (WS trades publics) +
Axi via MetaTrader5 si LATENCY_MT5_ENABLED=1 et le terminal MT5 est ouvert.

Usage standalone (sans redémarrer le bot) :
    venv\\Scripts\\python.exe tools\\latency_bench.py --duration 60
Sinon via l'API : POST /latency/run puis GET /latency/report.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import (  # noqa: E402
    LATENCY_DEFAULT_SECONDS, LATENCY_MT5_ENABLED, LATENCY_MT5_SYMBOL,
    LATENCY_SYMBOL,
)
from utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "latency_report.json"
GRID_MS     = 200          # résolution de la grille lead/lag
MAX_LAG_BIN = 15           # lags testés : ±15 bins = ±3 s

# Tick = (local_ms, price, exch_ms | None)
Tick = Tuple[float, float, Optional[float]]

# État partagé avec l'API (/latency/status, /latency/report)
latency_state: Dict[str, Any] = {"status": "idle", "report": None, "started_at": None}


def _now_ms() -> float:
    return time.time() * 1000.0


def _split_symbol(symbol: str) -> Tuple[str, str]:
    base, _, quote = symbol.partition("/")
    return base.upper(), (quote or "USDT").upper()


# ── Collecteurs WS par plateforme ────────────────────────────────────────────

async def _ws_collect(session: aiohttp.ClientSession, url: str,
                      subscribe: Optional[dict], parse, ticks: List[Tick],
                      stop_at: float, name: str) -> None:
    """Boucle WS générique : connexion, souscription, parsing des trades."""
    while _now_ms() < stop_at:
        try:
            async with session.ws_connect(url, heartbeat=15) as ws:
                if subscribe:
                    await ws.send_json(subscribe)
                while _now_ms() < stop_at:
                    msg = await ws.receive(timeout=max((stop_at - _now_ms()) / 1000, 0.1))
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                        continue
                    local = _now_ms()
                    try:
                        for price, exch_ms in parse(json.loads(msg.data)):
                            ticks.append((local, price, exch_ms))
                    except Exception:
                        pass
        except asyncio.TimeoutError:
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[LATENCY] %s — reconnexion: %s", name, e)
            await asyncio.sleep(1)


def _parse_binance(d: dict):
    if "p" in d and "E" in d:
        yield float(d["p"]), float(d["E"])

def _parse_bybit(d: dict):
    for t in d.get("data", []) if isinstance(d.get("data"), list) else []:
        if "p" in t and "T" in t:
            yield float(t["p"]), float(t["T"])

def _parse_okx(d: dict):
    for t in d.get("data", []) if isinstance(d.get("data"), list) else []:
        if "px" in t and "ts" in t:
            yield float(t["px"]), float(t["ts"])

def _parse_coinbase(d: dict):
    if d.get("type") in ("match", "last_match") and "price" in d:
        ts = datetime.fromisoformat(d["time"].replace("Z", "+00:00")).timestamp() * 1000
        yield float(d["price"]), ts

def _parse_kraken(d: dict):
    if d.get("channel") == "trade":
        for t in d.get("data", []):
            ts = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
            yield float(t["price"]), ts


def _platform_specs(base: str, quote: str) -> Dict[str, dict]:
    return {
        "binance": {
            "url": f"wss://stream.binance.com:9443/ws/{base.lower()}{quote.lower()}@trade",
            "subscribe": None, "parse": _parse_binance,
        },
        "bybit": {
            "url": "wss://stream.bybit.com/v5/public/spot",
            "subscribe": {"op": "subscribe", "args": [f"publicTrade.{base}{quote}"]},
            "parse": _parse_bybit,
        },
        "okx": {
            "url": "wss://ws.okx.com:8443/ws/v5/public",
            "subscribe": {"op": "subscribe",
                          "args": [{"channel": "trades", "instId": f"{base}-{quote}"}]},
            "parse": _parse_okx,
        },
        "coinbase": {
            "url": "wss://ws-feed.exchange.coinbase.com",
            "subscribe": {"type": "subscribe", "product_ids": [f"{base}-USD"],
                          "channels": ["matches"]},
            "parse": _parse_coinbase,
        },
        "kraken": {
            "url": "wss://ws.kraken.com/v2",
            "subscribe": {"method": "subscribe",
                          "params": {"channel": "trade", "symbol": [f"{base}/USD"]}},
            "parse": _parse_kraken,
        },
    }


async def _mt5_collect(ticks: List[Tick], stop_at: float) -> None:
    """Poll des ticks Axi via le terminal MetaTrader5 (si installé et ouvert)."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        logger.warning("[LATENCY] MetaTrader5 non installé — Axi ignoré "
                       "(pip install MetaTrader5)")
        return
    if not await asyncio.to_thread(mt5.initialize):
        logger.warning("[LATENCY] mt5.initialize() a échoué — terminal MT5 fermé ?")
        return
    try:
        last_msc = 0
        while _now_ms() < stop_at:
            tick = await asyncio.to_thread(mt5.symbol_info_tick, LATENCY_MT5_SYMBOL)
            if tick and tick.time_msc != last_msc:
                last_msc = tick.time_msc
                mid = (tick.bid + tick.ask) / 2
                ticks.append((_now_ms(), mid, float(tick.time_msc)))
            await asyncio.sleep(0.05)
    finally:
        await asyncio.to_thread(mt5.shutdown)


# ── Analyse ──────────────────────────────────────────────────────────────────

def _price_grid(ticks: List[Tick], t0: float, t1: float) -> Optional[np.ndarray]:
    """Dernier prix connu par bin de GRID_MS ms (forward-fill), NaN avant le 1er tick."""
    n_bins = int((t1 - t0) // GRID_MS)
    if n_bins < 20 or len(ticks) < 10:
        return None
    grid = np.full(n_bins, np.nan)
    for local, price, _ in ticks:
        i = int((local - t0) // GRID_MS)
        if 0 <= i < n_bins:
            grid[i] = price
    # forward-fill
    mask = np.isnan(grid)
    idx  = np.where(~mask, np.arange(n_bins), 0)
    np.maximum.accumulate(idx, out=idx)
    filled = grid[idx]
    filled[mask & (idx == 0) & np.isnan(grid[0].repeat(1))] = np.nan
    return filled


def _best_lag_ms(a: np.ndarray, b: np.ndarray) -> Optional[Tuple[float, float]]:
    """Lag (ms) maximisant la corrélation des rendements. >0 ⇒ A précède B."""
    ra, rb = np.diff(np.log(a)), np.diff(np.log(b))
    valid = ~(np.isnan(ra) | np.isnan(rb))
    if valid.sum() < 50:
        return None
    best_corr, best_lag = 0.0, 0
    n = len(ra)
    for lag in range(-MAX_LAG_BIN, MAX_LAG_BIN + 1):
        # corrèle ra[t] avec rb[t+lag] : lag > 0 ⇒ B réagit après A
        if lag >= 0:
            x, y = ra[:n - lag or None], rb[lag:]
        else:
            x, y = ra[-lag:], rb[:n + lag]
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 50 or np.nanstd(x[m]) == 0 or np.nanstd(y[m]) == 0:
            continue
        c = float(np.corrcoef(x[m], y[m])[0, 1])
        if c > best_corr:
            best_corr, best_lag = c, lag
    if best_corr < 0.05:
        return None
    return best_lag * GRID_MS, round(best_corr, 3)


def _analyze(data: Dict[str, List[Tick]], symbol: str, duration_s: int,
             started_at: str) -> Dict[str, Any]:
    platforms: Dict[str, Any] = {}
    active = {k: v for k, v in data.items() if len(v) >= 10}

    t0 = min((v[0][0] for v in active.values()), default=0)
    t1 = max((v[-1][0] for v in active.values()), default=0)

    for name, ticks in data.items():
        entry: Dict[str, Any] = {"ticks": len(ticks)}
        if len(ticks) >= 10:
            deltas = np.array([loc - ex for loc, _, ex in ticks if ex is not None])
            span_s = max((ticks[-1][0] - ticks[0][0]) / 1000, 1e-9)
            entry["ticks_per_sec"] = round(len(ticks) / span_s, 2)
            if len(deltas) >= 10:
                entry["transport_ms"] = {
                    "median": round(float(np.median(deltas)), 1),
                    "p10":    round(float(np.percentile(deltas, 10)), 1),
                    "p90":    round(float(np.percentile(deltas, 90)), 1),
                }
        else:
            entry["note"] = "trop peu de ticks — plateforme injoignable ou marché inactif"
        platforms[name] = entry

    grids = {k: g for k, v in active.items()
             if (g := _price_grid(v, t0, t1)) is not None}

    matrix: Dict[str, Dict[str, Any]] = {}
    lead_scores: Dict[str, List[float]] = {k: [] for k in grids}
    names = sorted(grids)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            res = _best_lag_ms(grids[a], grids[b])
            if res is None:
                continue
            lag_ms, corr = res
            matrix.setdefault(a, {})[b] = {"lag_ms": lag_ms, "corr": corr}
            lead_scores[a].append(lag_ms)      # >0 : A mène B
            lead_scores[b].append(-lag_ms)
    ranking = sorted(
        ({"platform": k, "lead_score_ms": round(float(np.mean(v)), 1)}
         for k, v in lead_scores.items() if v),
        key=lambda x: -x["lead_score_ms"],
    )

    verdict = ""
    if ranking:
        leader = ranking[0]
        laggard = ranking[-1]
        verdict = (f"{leader['platform']} imprime les mouvements en premier "
                   f"(avance moyenne {leader['lead_score_ms']:+.0f} ms) ; "
                   f"{laggard['platform']} est la plus tardive "
                   f"({laggard['lead_score_ms']:+.0f} ms). "
                   f"Fenêtre d'avance exploitable ≈ "
                   f"{leader['lead_score_ms'] - laggard['lead_score_ms']:.0f} ms.")
        if "axi_mt5" in {r["platform"] for r in ranking}:
            axi = next(r for r in ranking if r["platform"] == "axi_mt5")
            verdict += (f" Par rapport à Axi (MT5) : les venues plus rapides voient "
                        f"le mouvement ~{axi['lead_score_ms'] * -1:.0f} ms avant le broker.")

    return {
        "symbol":     symbol,
        "duration_s": duration_s,
        "started_at": started_at,
        "grid_ms":    GRID_MS,
        "platforms":  platforms,
        "lead_lag":   {"matrix": matrix, "ranking": ranking},
        "verdict":    verdict,
        "note": ("lead_score_ms > 0 = la plateforme voit les mouvements avant les "
                 "autres. transport_ms = réception locale − timestamp exchange "
                 "(comparatif ; inclut le décalage d'horloge local, commun à toutes)."),
    }


# ── Orchestration ────────────────────────────────────────────────────────────

async def run_benchmark(duration_s: int = LATENCY_DEFAULT_SECONDS,
                        symbol: str = LATENCY_SYMBOL,
                        session: Optional[aiohttp.ClientSession] = None) -> Dict[str, Any]:
    """Lance la collecte multi-plateformes puis l'analyse. Sauve le rapport."""
    base, quote = _split_symbol(symbol)
    started_at  = datetime.now(timezone.utc).isoformat()
    latency_state.update(status="running", started_at=started_at)
    stop_at = _now_ms() + duration_s * 1000

    own_session = session is None
    session = session or aiohttp.ClientSession()
    data: Dict[str, List[Tick]] = {}
    try:
        tasks = []
        for name, spec in _platform_specs(base, quote).items():
            data[name] = []
            tasks.append(asyncio.create_task(
                _ws_collect(session, spec["url"], spec["subscribe"],
                            spec["parse"], data[name], stop_at, name),
                name=f"latency_{name}"))
        if LATENCY_MT5_ENABLED:
            data["axi_mt5"] = []
            tasks.append(asyncio.create_task(
                _mt5_collect(data["axi_mt5"], stop_at), name="latency_axi_mt5"))

        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if own_session:
            await session.close()

    report = _analyze(data, symbol, duration_s, started_at)
    latency_state.update(status="done", report=report)
    try:
        REPORT_PATH.parent.mkdir(exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception as e:
        logger.warning("[LATENCY] Sauvegarde rapport échouée: %s", e)
    logger.info("[LATENCY] Rapport prêt — %s", report.get("verdict") or "pas de verdict")
    return report


if __name__ == "__main__":
    dur = LATENCY_DEFAULT_SECONDS
    if "--duration" in sys.argv:
        dur = int(sys.argv[sys.argv.index("--duration") + 1])
    print(f"Benchmark {LATENCY_SYMBOL} pendant {dur}s sur "
          f"Binance/Bybit/OKX/Coinbase/Kraken"
          f"{' + Axi MT5' if LATENCY_MT5_ENABLED else ''}…")
    rep = asyncio.run(run_benchmark(dur))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
