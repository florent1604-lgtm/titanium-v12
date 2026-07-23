"""core/lead_lag_engine.py — Boucle de CONCORDANCE inter-actifs + débrief.

Enveloppe le scanner exploratoire (tools/lead_lag_scan) dans une boucle qui :
  · récupère les clôtures (crypto = Binance 24/7 ; CFD = MT5 quand ouvert) ;
  · scanne toutes les paires ordonnées (qui anticipe qui, à quel décalage) ;
  · accumule la PERSISTANCE à travers les fenêtres (le vrai « stigmate de marché ») ;
  · débriefe sur Telegram dès qu'un candidat FORT + PERSISTANT émerge (anti-spam).

⚠️ EXPLORATOIRE — PRÉ-M2. Ces candidats ne décident RIEN : ils alimentent la validation
statistique de Codex (collab/PLAN_CONFLUENCE_LEAD_LAG_M2.md). Rien de câblé au trading.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable, List, Optional

from tools import lead_lag_scan as ll
from utils.logger import get_logger

logger = get_logger(__name__)

TRACKERS: Dict[str, ll.PersistenceTracker] = {}     # un traqueur de persistance par TF
LAST: dict = {"ts": None, "by_tf": {}}
_debriefed: dict = {}                 # (tf,leader,follower) -> dernier débrief (anti-spam)
_DEBRIEF_INTERVAL = 3600              # 1 débrief / paire / heure max


def _crypto_fetch(symbol: str, tf: str = "M15"):
    """Clôtures crypto Binance sur `tf`, bougies CLÔTURÉES uniquement. P0 red-team Codex :
    la dernière kline Binance est EN FORMATION ; la garder (sur N fetchs séquentiels de la
    même barre) fabrique un faux lead/lag de transport → on la retire, index trié/unique."""
    from data.binance_ohlcv import get_ohlcv
    df = get_ohlcv(symbol, tf, 500, min_bars=100)
    if df is None or len(df) < 3:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df["close"].iloc[:-1]        # retire la bougie en formation


async def run_cycle(symbols: List[str], *, tfs=("M15",), fetch_fn: Optional[Callable] = None,
                    max_lag: int = 12, notify: bool = True) -> dict:
    """Un cycle MULTI-TIMEFRAME : pour chaque TF, scan + persistance + (option) débrief.
    fetch_fn(symbol, tf) injectable (tests). Ne lève jamais (fail-safe). Les liens macro
    sont souvent plus nets en H1/H4 que sur le M15 bruité."""
    fetch_fn = fetch_fn or _crypto_fetch
    now = datetime.now(timezone.utc)
    out = {"ts": now.isoformat(), "by_tf": {}}
    for tf in tfs:
        tracker = TRACKERS.setdefault(tf, ll.PersistenceTracker(window=30))
        try:
            report = await asyncio.to_thread(
                ll.run_scan, symbols, lambda s, _tf=tf: fetch_fn(s, _tf),
                max_lag=max_lag, tracker=tracker)
        except Exception as e:  # noqa: BLE001
            logger.warning("[LEADLAG] cycle %s: %s", tf, e)
            continue
        strong = ll.strong_candidates(report)
        LAST["by_tf"][tf] = {"report": report, "strong": strong}
        out["by_tf"][tf] = {"n_pairs": report.get("n_pairs", 0), "strong": strong}
        logger.info("[LEADLAG] %s : %d actifs, %d paires, %d candidats persistants",
                    tf, report.get("n_assets", 0), report.get("n_pairs", 0), len(strong))
        if notify and strong:
            await _debrief(tf, strong, now)
    LAST["ts"] = now.isoformat()
    return out


async def _debrief(tf: str, strong: List[dict], now: datetime) -> None:
    """Débrief Telegram des candidats forts+persistants (anti-spam par TF+paire). Fail-safe."""
    fresh = []
    for d in strong:
        key = (tf, d["leader"], d["follower"])
        if now.timestamp() - _debriefed.get(key, 0.0) >= _DEBRIEF_INTERVAL:
            _debriefed[key] = now.timestamp()
            fresh.append(d)
    if not fresh:
        return
    try:
        from notifications.telegram import _tg_post, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS):
            return
        lines = [f"🔗 <b>Concordance inter-actifs [{tf}] — candidat</b> (exploratoire, à valider M2)"]
        for d in fresh[:6]:
            p = d.get("persistence") or {}
            hr = f"{d['hit_rate']*100:.0f}%" if d.get("hit_rate") else "?"
            fr = f"{d['flip_rate']*100:.0f}%" if d.get("flip_rate") else "?"
            lines.append(
                f"• <b>{d['leader']}</b> ⟶ <b>{d['follower']}</b> (lag {d['lag']}) "
                f"corr {d['corr']:+.2f} · dir {hr} · retourn. {fr} · "
                f"persist {int(p.get('rate',0)*100)}%")
        lines.append("<i>Pré-M2 : piste de recherche, pas un signal de trading.</i>")
        await _tg_post("\n".join(lines))
        logger.info("[LEADLAG] débrief Telegram %s : %d candidats", tf, len(fresh))
    except Exception as e:  # noqa: BLE001
        logger.warning("[LEADLAG] débrief: %s", e)


def status_snapshot() -> dict:
    by_tf = {}
    for tf, data in (LAST.get("by_tf") or {}).items():
        rep = data.get("report") or {}
        by_tf[tf] = {
            "n_assets": rep.get("n_assets", 0), "assets": rep.get("assets", []),
            "n_pairs": rep.get("n_pairs", 0),
            "top": (rep.get("pairs") or [])[:12],
            "strong": data.get("strong", []),
        }
    return {"ts": LAST.get("ts"), "timeframes": list(by_tf.keys()), "by_tf": by_tf,
            "note": "EXPLORATOIRE pré-M2 — candidats à valider (Codex). Ne décide rien."}
