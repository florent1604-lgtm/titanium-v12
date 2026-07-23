"""core/opportunity_scan.py — Scan d'opportunités périodique (cron in-app).

Cahier des charges (Florent, 09/07/2026) : tous les 10 jours, rebalayer TOUS
les actifs MT5, identifier les NOUVELLES opportunités « qui marchent maintenant »,
alerter (son) et auto-intégrer au moteur swing (paper) pour lancer des tests de
trade en temps réel.

Note méthode : un backtest H4 sur 1 mois seul est infaisable (~180 barres <
EMA200). Donc on scanne sur l'historique complet (validité statistique via
tools/asset_optimizer, walk-forward OOS) PUIS on applique une PORTE DE RÉCENCE
(OPP_LOOKBACK_DAYS ≈ 1 mois) : un actif n'est « nouvelle opportunité » que si sa
config est aussi rentable sur la fenêtre récente. Ça capture ce qui monte
maintenant sans sacrifier la robustesse.

N'écrase PAS data/asset_configs.json (panier validé). Écrit :
  - data/opportunities.json      (état + classement + nouvelles opportunités)
  - data/swing_auto_configs.json (actifs auto-intégrés au moteur swing)
MT5 = données seulement (compte Axi live intouché).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from utils.config import (
    OPP_CHECK_HOURS, OPP_LOOKBACK_DAYS, OPP_MAX_AUTO_ADD, OPP_MIN_POTENTIAL,
    OPP_PERSIST_DAYS, OPP_SCAN_HOUR_UTC, OPP_TOP_N, SWING_LIVE_SYMBOLS,
)
from utils.logger import get_logger

logger = get_logger(__name__)
ROOT = Path(__file__).resolve().parent.parent
OPP_PATH = ROOT / "data" / "opportunities.json"
AUTO_PATH = ROOT / "data" / "swing_auto_configs.json"
TS_BARS = {"scalp": 32, "intraday": 48, "swing": 60}

opp_state: Dict[str, Any] = {
    "last_run": None, "running": False, "last_error": None,
    "alert_pending": False, "new_hot": [], "pending": [], "candidates": {},
    "ranking": [], "validated": {}, "universe_size": 0, "known": [], "progress": None,
}


def _load_state() -> None:
    if OPP_PATH.exists():
        try:
            saved = json.loads(OPP_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                # `running` et `progress` décrivent uniquement une tâche de CE
                # processus. Après un crash/redémarrage, les restaurer crée un
                # verrou fantôme permanent : aucun ancien thread ne peut encore
                # travailler dans le nouvel event loop.
                saved.pop("running", None)
                saved.pop("progress", None)
                opp_state.update(saved)
        except Exception:
            pass
    opp_state.update(running=False, progress=None)


def _save_state() -> None:
    try:
        from utils.atomic_state import save_json_atomic
        save_json_atomic(OPP_PATH, opp_state)   # R2 : atomique + sérialisé
    except Exception as e:
        logger.warning("[OPP] sauvegarde état: %s", e)


# ── Cœur bloquant (exécuté via asyncio.to_thread) ────────────────────────────

def _scan_blocking() -> tuple:
    """Balaye l'univers (coarse) + deep sur le top N. Retourne (uni, validated, ranking)."""
    from tools.asset_optimizer import list_universe, run_pass1, run_pass2
    uni = list_universe()
    if not uni:
        raise RuntimeError("OPPORTUNITY_UNIVERSE_EMPTY")
    pass1 = run_pass1(uni)
    ranked = sorted(pass1.items(), key=lambda kv: kv[1]["best"]["potential"], reverse=True)
    shortlist = [s for s, _ in ranked[:OPP_TOP_N]]
    deep = run_pass2(uni, shortlist)

    validated: Dict[str, dict] = {}
    for sym, d in deep.items():
        vs = [r for r in d["styles"].values() if r["validated"]]
        if not vs:
            continue
        best = max(vs, key=lambda r: r["potential"])
        validated[sym] = {**best, "cost": d["cost"]}

    ranking = [{
        "symbol": s, "category": d["cost"]["category"].replace("STANDARD_", ""),
        "style": d["best"]["style"], "potential": d["best"]["potential"],
        "expectancy_bps": d["best"]["oos"].get("expectancy_bps"),
        "profit_factor": d["best"]["oos"].get("profit_factor"),
        "trades": d["best"]["oos"].get("trades"),
        "validated": d["best"].get("validated", False),
    } for s, d in ranked[:30]]
    return uni, validated, ranking


def _recent_metrics(sym: str, vc: dict) -> Dict[str, Any] | None:
    """Porte de récence : métriques de la config sur les OPP_LOOKBACK_DAYS
    derniers jours (indicateurs calculés sur l'historique complet, trades sur la
    fenêtre récente uniquement)."""
    from tools.asset_optimizer import (
        load, add_indicators, entries, simulate, metrics, STYLES,
    )
    spec = STYLES[vc["style"]]
    df = load(sym, vc["tf"], spec["bars"])
    if df is None or len(df) < 300:
        return None
    df = add_indicators(df)
    cutoff = df.index[-1] - pd.Timedelta(days=OPP_LOOKBACK_DAYS)
    sub = df[df.index >= cutoff]
    if len(sub) < 30:
        return None
    e = entries(sub, vc["align_ema50"], vc["rsi_gate"])
    if len(e) < 3:
        return None
    return metrics(simulate(sub, e, vc["sl_atr"], tuple(vc["tp_ladder"]),
                            vc["fees_bps"], spec["time_stop"],
                            vc.get("carry_bps_per_bar", 0.0)))


def _auto_integrate(hots: List[dict]) -> List[str]:
    """Écrit les nouveaux actifs dans swing_auto_configs.json + reload à chaud."""
    if not hots:
        return []
    existing = {}
    if AUTO_PATH.exists():
        try:
            existing = json.loads(AUTO_PATH.read_text(encoding="utf-8")).get("assets", {})
        except Exception:
            existing = {}
    for h in hots:
        existing[h["symbol"]] = {
            "style": h["style"], "tf": h["tf"], "sl_atr": h["sl_atr"],
            "tp_ladder": h["tp_ladder"], "align_ema50": h["align_ema50"],
            "rsi_gate": h["rsi_gate"], "time_stop_bars": TS_BARS.get(h["style"], 60),
            "oos": h["oos"], "potential": h["potential"], "category": h["category"],
            "recent": h.get("recent"), "discovered": datetime.now(timezone.utc).isoformat(),
        }
    AUTO_PATH.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(),
        "note": "Actifs auto-découverts par le scan d'opportunités — paper only.",
        "assets": existing}, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from core.swing_engine import reload_configs
        cfgs = reload_configs()
        logger.info("[OPP] Auto-intégrés au moteur swing: %s", [h["symbol"] for h in hots])
        return cfgs
    except Exception as e:
        logger.warning("[OPP] reload swing échoué: %s", e)
        return []


def _voice_alert(hots: List[dict]) -> None:
    """Alerte vocale JARVIS/Titan best-effort (le beep dashboard est le canal sûr)."""
    msg = f"{len(hots)} nouvelle{'s' if len(hots) > 1 else ''} opportunité de trade détectée : " \
          + ", ".join(h["symbol"] for h in hots[:3])
    for mod, fn in (("assistant.titan_core", "speak"),
                    ("assistant.signal_alert", "speak_alert")):
        try:
            m = __import__(mod, fromlist=[fn])
            getattr(m, fn)(msg)
            return
        except Exception:
            continue


# ── Orchestration asynchrone ─────────────────────────────────────────────────

async def run_scan_once(manual: bool = False) -> Dict[str, Any]:
    if opp_state.get("running"):
        return {"status": "already_running"}
    opp_state.update(running=True, progress="scan univers…")
    _save_state()
    try:
        uni, validated, ranking = await asyncio.to_thread(_scan_blocking)
        known = set(opp_state.get("known", [])) | set(SWING_LIVE_SYMBOLS)
        opp_state["progress"] = "porte de récence…"

        # Candidats de CE scan : validés + potentiel + rentables sur le dernier mois.
        current: Dict[str, dict] = {}
        for sym, vc in sorted(validated.items(), key=lambda kv: kv[1]["potential"], reverse=True):
            if sym in known or vc["potential"] < OPP_MIN_POTENTIAL:
                continue
            recent = await asyncio.to_thread(_recent_metrics, sym, vc)
            if (not recent or recent.get("expectancy_bps", -1) <= 0
                    or recent.get("profit_factor", 0) <= 1 or recent.get("trades", 0) < 3):
                continue
            current[sym] = {
                "symbol": sym, "style": vc["style"], "tf": vc["tf"],
                "sl_atr": vc["sl_atr"], "tp_ladder": vc["tp_ladder"],
                "align_ema50": vc["align_ema50"], "rsi_gate": vc["rsi_gate"],
                "potential": vc["potential"], "oos": vc["oos"], "recent": recent,
                "category": vc["cost"]["category"].replace("STANDARD_", ""),
            }

        # FILTRE DE PERSISTANCE : un candidat doit ressortir OPP_PERSIST_DAYS scans
        # consécutifs avant auto-intégration. On incrémente le streak s'il était
        # déjà candidat au scan précédent, sinon on repart à 1. Ceux absents ce
        # scan sont abandonnés (streak remis à zéro).
        prev = opp_state.get("candidates", {})
        now_iso = datetime.now(timezone.utc).isoformat()
        candidates: Dict[str, dict] = {}
        confirmed: List[dict] = []
        for sym, c in current.items():
            streak = int(prev.get(sym, {}).get("streak", 0)) + 1
            c = {**c, "streak": streak, "first_seen": prev.get(sym, {}).get("first_seen", now_iso),
                 "last_seen": now_iso}
            candidates[sym] = c
            if streak >= OPP_PERSIST_DAYS:
                confirmed.append(c)

        to_add = [c for c in confirmed if c["symbol"] not in known][:OPP_MAX_AUTO_ADD]
        _auto_integrate(to_add)
        pending = [c for c in candidates.values() if c["streak"] < OPP_PERSIST_DAYS]

        opp_state.update(
            last_run=now_iso, running=False, progress=None, universe_size=len(uni),
            ranking=ranking, candidates=candidates, new_hot=to_add, pending=pending,
            validated={s: {"potential": v["potential"], "style": v["style"]}
                       for s, v in validated.items()},
            known=list(known | {h["symbol"] for h in to_add}),
            alert_pending=bool(to_add), last_error=None,
        )
        _save_state()
        if to_add:
            logger.info("[OPP] %d opportunité(s) CONFIRMÉE(s) (%d j consécutifs) intégrée(s): %s",
                        len(to_add), OPP_PERSIST_DAYS, [h["symbol"] for h in to_add])
            _voice_alert(to_add)
        if pending:
            logger.info("[OPP] %d candidat(s) en attente de persistance: %s",
                        len(pending), [f"{c['symbol']}({c['streak']}/{OPP_PERSIST_DAYS})" for c in pending])
        if not to_add and not pending:
            logger.info("[OPP] Scan terminé — aucun candidat")
        return {"status": "ok", "confirmed": to_add, "pending": pending}
    except Exception as e:
        opp_state.update(running=False, progress=None, last_error=str(e))
        _save_state()
        logger.warning("[OPP] scan échoué: %s", e)
        return {"status": "error", "error": str(e)}


def _scheduled_due(last_iso: str | None) -> bool:
    """Quotidien ancré à OPP_SCAN_HOUR_UTC (ouverture Asie). Due si on n'a pas
    scanné depuis le dernier créneau planifié (aujourd'hui à l'heure d'ancrage,
    ou hier si on est avant)."""
    now = datetime.now(timezone.utc)
    sched = now.replace(hour=OPP_SCAN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now < sched:
        sched -= timedelta(days=1)
    return (not last_iso) or (datetime.fromisoformat(last_iso) < sched)


async def opportunity_scan_loop() -> None:
    """Cron in-app : scan QUOTIDIEN ancré à l'ouverture de la session asiatique
    (OPP_SCAN_HOUR_UTC). Filtre de persistance de OPP_PERSIST_DAYS jours avant
    auto-intégration. Planning persisté → survit aux redémarrages."""
    _load_state()
    logger.info("[OPP] Scan quotidien actif — %02d:00 UTC (Asie), persistance %d j, vérif %dh",
                OPP_SCAN_HOUR_UTC, OPP_PERSIST_DAYS, OPP_CHECK_HOURS)
    while True:
        try:
            if _scheduled_due(opp_state.get("last_run")) and not opp_state.get("running"):
                logger.info("[OPP] Déclenchement du scan quotidien…")
                await run_scan_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[OPP] boucle: %s", e)
        await asyncio.sleep(OPP_CHECK_HOURS * 3600)


def get_status() -> Dict[str, Any]:
    last = opp_state.get("last_run")
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=OPP_SCAN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now >= nxt:
        nxt += timedelta(days=1)
    return {
        "last_run": last, "next_run": nxt.isoformat(), "running": opp_state.get("running"),
        "progress": opp_state.get("progress"), "last_error": opp_state.get("last_error"),
        "alert_pending": opp_state.get("alert_pending"), "new_hot": opp_state.get("new_hot", []),
        "pending": opp_state.get("pending", []), "ranking": opp_state.get("ranking", []),
        "universe_size": opp_state.get("universe_size"),
        "schedule": f"quotidien {OPP_SCAN_HOUR_UTC:02d}:00 UTC (Asie)",
        "persist_days": OPP_PERSIST_DAYS, "lookback_days": OPP_LOOKBACK_DAYS,
        "min_potential": OPP_MIN_POTENTIAL,
    }


def ack_alert() -> None:
    opp_state["alert_pending"] = False
    _save_state()
