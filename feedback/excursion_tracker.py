"""feedback/excursion_tracker.py — LES YEUX DE CLOE : ce que le prix a VRAIMENT fait.

Florent 28/07/2026 : « ces données doivent nourrir naturellement l'esprit de Cloe ».

Aujourd'hui Cloe reçoit la SENSATION (11k décisions journalisées) et la STATISTIQUE
(agrégats), mais jamais la CONSÉQUENCE : elle sait « j'ai décidé X », jamais « et voilà
de combien je me suis trompée ». Sans conséquence, pas d'apprentissage.

Ce module enregistre, pour CHAQUE position fermée, la vie réelle du prix :
  · `mae_R`  — excursion ADVERSE maximale (en R) : jusqu'où ça a fait mal ;
  · `mfe_R`  — excursion FAVORABLE maximale : jusqu'où on aurait pu aller ;
  · `giveback_R` — ce qu'on a RESTITUÉ après le sommet (le regret) ;
  · `time_to_mfe` — combien de temps pour atteindre ce sommet ;
  · `censored` — vrai si fermé par SL/timeout → le MFE est TRONQUÉ (on ne saura jamais
    où ça serait allé). SANS ce drapeau, toute estimation future du MFE est biaisée à la
    baisse, définitivement et sans rattrapage possible.

Le R est FIGÉ À L'ENTRÉE (distance entrée↔SL initial), jamais recalculé — sinon les
lignes seraient inininterprétables plus tard.

DEUX SOURCES, la meilleure gagne :
  1. `observe()` — suivi en direct, gratuit (greffé sur la boucle de gestion existante
     qui sonde déjà toutes les 15 s). Résolution 15 s → SOUS-ESTIME les mèches.
  2. `_exact_from_m1()` — à la clôture, on relit les bougies M1 entre entrée et sortie
     → extrêmes EXACTS. C'est cette version qui est enregistrée quand elle est disponible.

À la clôture, on joint le CONTEXTE D'ENTRÉE depuis le journal non censuré (piliers,
régime géométrique, ÉMOTION, fondamentaux, coût) : perception complète + conséquence
mesurée = la matière dont Cloe a besoin pour grandir.

FAIL-SAFE ABSOLU : toute exception est avalée. Un enregistreur cassé ne doit JAMAIS
empêcher ni perturber un trade. Écriture append-only, rotation mensuelle.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "excursions"
SCHEMA_VERSION = 1

# Sorties considérées comme TRONQUANT le MFE (on ne saura jamais où le prix serait allé).
_CENSORING_EXITS = {"sl", "timeout", "manual"}


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


# ── 1. Suivi en direct (gratuit, greffé sur la boucle existante) ─────────────

def observe(st: Dict[str, Any], *, side: int, entry: float, cur: float,
            r: float, ts: Optional[float] = None) -> None:
    """Met à jour MAE/MFE/giveback dans l'état de la position. PURE : aucun appel MT5.

    `st` est le dict d'état déjà persisté par le gestionnaire de positions ; on ne fait
    qu'y ajouter nos champs. Idempotent, monotone (les extrema ne reculent jamais)."""
    try:
        if not r or r <= 0 or not math.isfinite(cur) or not math.isfinite(entry):
            return
        ts = ts if ts is not None else _now()
        fav_r = (cur - entry) / r * side          # >0 = en notre faveur, <0 = contre nous

        if st.get("ts_entry_obs") is None:
            st["ts_entry_obs"] = ts

        # MFE — sommet favorable (+ l'instant où il a été atteint)
        if fav_r > st.get("mfe_R", float("-inf")):
            st["mfe_R"] = fav_r
            st["ts_mfe"] = ts

        # MAE — creux adverse (valeur ≤ 0)
        if fav_r < st.get("mae_R", float("inf")):
            st["mae_R"] = fav_r

        # GIVEBACK — restitution APRÈS le sommet (le regret, mesuré).
        # ⚠️ Seulement s'il y a eu un VRAI gain à restituer (mfe > 0) : sinon on
        # recompterait une simple excursion adverse déjà mesurée par le MAE.
        if st.get("ts_mfe") is not None and ts > st["ts_mfe"] and st.get("mfe_R", 0.0) > 0:
            gb = float(st.get("mfe_R", 0.0)) - fav_r
            if gb > st.get("giveback_R", 0.0):
                st["giveback_R"] = gb
    except Exception:  # noqa: BLE001 — un observateur ne casse jamais la gestion
        pass


# ── 2. Extrêmes EXACTS depuis les bougies M1 (à la clôture) ─────────────────

def _exact_from_m1(mt5: Any, symbol: str, side: int, entry: float, r: float,
                   ts_entry: float, ts_exit: float) -> Optional[Dict[str, Any]]:
    """Relit les bougies M1 entre entrée et sortie → MAE/MFE EXACTS (mèches incluses).
    Le sondage 15 s rate les mèches ; ceci ne les rate pas. None si indisponible."""
    try:
        t0 = datetime.fromtimestamp(ts_entry - 60, tz=timezone.utc)
        t1 = datetime.fromtimestamp(ts_exit + 60, tz=timezone.utc)
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, t0, t1)
        if rates is None or len(rates) == 0:
            return None

        best_fav_r, best_fav_ts = float("-inf"), None
        worst_adv_r = float("inf")
        giveback = 0.0
        for row in rates:
            hi, lo, bt = float(row["high"]), float(row["low"]), float(row["time"])
            # extrême FAVORABLE de la bougie (haut si long, bas si short)
            fav_px = hi if side > 0 else lo
            adv_px = lo if side > 0 else hi
            fav_r = (fav_px - entry) / r * side
            adv_r = (adv_px - entry) / r * side
            if fav_r > best_fav_r:
                best_fav_r, best_fav_ts = fav_r, bt
            if adv_r < worst_adv_r:
                worst_adv_r = adv_r
            # restitution : creux survenu APRÈS le sommet (et seulement si gain réel)
            if best_fav_ts is not None and bt > best_fav_ts and best_fav_r > 0:
                giveback = max(giveback, best_fav_r - adv_r)

        if best_fav_ts is None or not math.isfinite(best_fav_r):
            return None
        return {
            "mae_R": round(worst_adv_r, 4),
            "mfe_R": round(best_fav_r, 4),
            "giveback_R": round(giveback, 4),
            "time_to_mfe_sec": int(max(0.0, best_fav_ts - ts_entry)),
            "time_to_mfe_bars": int(max(0.0, (best_fav_ts - ts_entry) / 60.0)),
            "excursion_source": "m1_bars",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("[EXCURSION] M1 exact indisponible %s: %r", symbol, exc)
        return None


# ── 3. Sortie réelle (prix, P&L, motif) ─────────────────────────────────────

def _exit_from_history(mt5: Any, ticket: int) -> Dict[str, Any]:
    """Récupère la sortie réelle via l'historique des deals. Motif déduit du commentaire
    broker ([sl]/[tp]) — c'est lui qui détermine `censored`."""
    out: Dict[str, Any] = {"exit_reason": "unknown", "pnl_money": None,
                           "exit_price": None, "ts_exit": None}
    try:
        deals = mt5.history_deals_get(position=ticket)
        if not deals:
            return out
        pnl = 0.0
        last = None
        for d in deals:
            pnl += float(getattr(d, "profit", 0) or 0) + \
                   float(getattr(d, "swap", 0) or 0) + \
                   float(getattr(d, "commission", 0) or 0)
            if getattr(d, "entry", None) == getattr(mt5, "DEAL_ENTRY_OUT", 1):
                last = d
        last = last or deals[-1]
        cmt = str(getattr(last, "comment", "") or "").lower()
        reason = "sl" if "sl" in cmt else ("tp" if "tp" in cmt else "manual")
        out.update({"exit_reason": reason, "pnl_money": round(pnl, 2),
                    "exit_price": float(getattr(last, "price", 0) or 0) or None,
                    "ts_exit": float(getattr(last, "time", 0) or 0) or None})
    except Exception as exc:  # noqa: BLE001
        logger.debug("[EXCURSION] historique deal #%s: %r", ticket, exc)
    return out


# ── 4. Contexte d'entrée : ce que TOUS les organes percevaient ───────────────

def _entry_context(ticket: int) -> Dict[str, Any]:
    """Rejoint le journal non censuré : piliers, régime géométrique, ÉMOTION,
    fondamentaux, coût — la perception complète du bot au moment d'entrer.
    C'est ce qui, associé à la conséquence, nourrit l'esprit de Cloe."""
    ctx: Dict[str, Any] = {}
    try:
        import sqlite3
        db = ROOT / "data" / "journal" / "titanium_journal.sqlite3"
        if not db.exists():
            return ctx
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute(
                "SELECT payload FROM journal_events WHERE kind='fill' "
                "AND payload LIKE ? ORDER BY ts_utc DESC LIMIT 1",
                (f'%"ticket": {ticket}%',)).fetchone()
        finally:
            con.close()
        if not row:
            return ctx
        pl = json.loads(row[0])
        for k in ("n_pillars", "pillars", "why", "trend_h4", "regime_geo", "lyapunov",
                  "topo_alert", "emotion", "fundamentals", "macro", "roundtrip_cost",
                  "exposure_gross_pct", "equity", "engine", "lot"):
            if k in pl:
                ctx[k] = pl[k]
    except Exception as exc:  # noqa: BLE001
        logger.debug("[EXCURSION] contexte d'entrée #%s: %r", ticket, exc)
    return ctx


# ── 5. Écriture append-only, rotation mensuelle ─────────────────────────────

def _append(record: Dict[str, Any]) -> None:
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"excursions-{datetime.now(timezone.utc):%Y-%m}.ndjson"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("[EXCURSION] écriture: %r", exc)


def record_closed(mt5: Any, ticket: str, st: Dict[str, Any],
                  symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Appelé quand une position DISPARAÎT (donc s'est fermée). Assemble la ligne
    immuable : contexte d'entrée + excursions exactes + conséquence. Fail-safe."""
    try:
        tk = int(ticket)
        entry = float(st.get("entry") or 0.0)
        r = float(st.get("r") or 0.0)
        side = int(st.get("side") or 0)
        sym = symbol or st.get("symbol") or "?"
        if not entry or r <= 0 or side == 0:
            return None

        ex = _exit_from_history(mt5, tk)
        ts_entry = float(st.get("ts_entry_obs") or 0.0)
        ts_exit = float(ex.get("ts_exit") or _now())

        # extrêmes EXACTS si possible, sinon repli sur le suivi 15 s (honnête sur la source)
        exc = None
        if ts_entry:
            exc = _exact_from_m1(mt5, sym, side, entry, r, ts_entry, ts_exit)
        if exc is None:
            exc = {"mae_R": round(float(st.get("mae_R", 0.0)), 4),
                   "mfe_R": round(float(st.get("mfe_R", 0.0)), 4),
                   "giveback_R": round(float(st.get("giveback_R", 0.0)), 4),
                   "time_to_mfe_sec": int(max(0.0, float(st.get("ts_mfe") or 0) - ts_entry))
                   if ts_entry and st.get("ts_mfe") else None,
                   "time_to_mfe_bars": None,
                   "excursion_source": "polling_15s"}

        pnl_money = ex.get("pnl_money")
        exit_px = ex.get("exit_price")
        pnl_r = round((exit_px - entry) / r * side, 4) if (exit_px and r) else None

        rec: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "trade_id": tk,
            "symbol": sym,
            "direction": "long" if side > 0 else "short",
            "ts_entry": datetime.fromtimestamp(ts_entry, timezone.utc).isoformat() if ts_entry else None,
            "ts_exit": datetime.fromtimestamp(ts_exit, timezone.utc).isoformat(),
            "entry_price": entry,
            "exit_price": exit_px,
            "r_unit_price": round(r, 8),
            "sl_initial_R": -1.0,                    # par construction (R = entrée↔SL)
            "tp_initial_R": st.get("tp_initial_R"),
            **exc,
            "pnl_R": pnl_r,
            "pnl_money": pnl_money,
            "exit_reason": ex.get("exit_reason"),
            # ⚠️ MFE tronqué : sans ce drapeau, toute estimation future serait biaisée bas
            "censored": ex.get("exit_reason") in _CENSORING_EXITS,
            "l2_quality": st.get("l2_quality", "unavailable"),
            "context": _entry_context(tk),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        _append(rec)
        logger.info("[EXCURSION] #%s %s %s MAE=%.2fR MFE=%.2fR giveback=%.2fR sortie=%s%s",
                    tk, sym, rec["direction"], rec.get("mae_R") or 0.0,
                    rec.get("mfe_R") or 0.0, rec.get("giveback_R") or 0.0,
                    rec["exit_reason"], " [tronqué]" if rec["censored"] else "")
        return rec
    except Exception as exc:  # noqa: BLE001 — jamais de remontée vers le trading
        logger.debug("[EXCURSION] record_closed #%s: %r", ticket, exc)
        return None
