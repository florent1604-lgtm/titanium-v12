"""execution/demo_position_manager.py — Gestion DYNAMIQUE des positions démo (Florent 26/07).

Le post-mortem (tools/trade_postmortem) a montré : **23 % des pertes** avaient atteint
**+0.8 R en leur faveur AVANT de repartir au SL** — un SL FIGÉ les a laissées revenir en
perte. Ce gestionnaire réajuste le SL EN COURS DE ROUTE (« ne pas rester figé ») :

  · BREAKEVEN : dès +DEMO_BREAKEVEN_R en faveur, le SL remonte à l'entrée (+ buffer coûts)
    → une perte potentielle devient ~0 ;
  · TRAILING  : au-delà de +DEMO_TRAIL_START_R, le SL suit le plus-haut favorable à
    DEMO_TRAIL_DIST_R derrière → on SÉCURISE le gain même si le TP lointain n'est jamais
    touché (répond aussi à l'axe #4 : TP disproportionné quand le SL est resserré).

SÛRETÉ (mêmes principes que l'exécuteur) :
  · compte DÉMO uniquement (assert_demo_or_raise, mur démo↔réel) ;
  · NOS positions seulement (magic 500786 ou commentaire « titanium… ») ;
  · le SL ne bouge JAMAIS dans le sens défavorable (jamais élargir le risque) ;
  · respect de la distance de stop minimale du broker ;
  · fail-safe par position (une erreur n'arrête pas la boucle) ; ne TOUCHE PAS le TP.

État du R initial persisté (data/demo_pos_state.json) pour survivre aux redémarrages.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger
from execution import demo_mt5_executor as dx

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "demo_pos_state.json"
MAGIC = 500786


def _cfg_float(name: str, default: float) -> float:
    import os
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _load_state() -> Dict[str, dict]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, dict]) -> None:
    try:
        from utils.atomic_state import save_json_atomic
        save_json_atomic(STATE_PATH, state)
    except Exception as exc:  # noqa: BLE001 — non fatal
        logger.debug("[DEMO-MANAGE] sauvegarde état: %r", exc)


def _is_ours(pos) -> bool:
    if int(getattr(pos, "magic", 0)) == MAGIC:
        return True
    return str(getattr(pos, "comment", "") or "").startswith("titanium")


def manage_once(mt5: Any, *, breakeven_r: float, trail_start_r: float,
                trail_dist_r: float) -> Dict[str, Any]:
    """Un passage de gestion sur toutes NOS positions démo ouvertes. Fail-safe."""
    # Mur démo↔réel : refus absolu hors compte démo attendu.
    try:
        dx.assert_demo_or_raise(mt5)
    except Exception as exc:  # noqa: BLE001
        return {"managed": 0, "moved": 0, "reason": f"NOT_DEMO: {exc}"}

    try:
        positions = mt5.positions_get()
    except Exception as exc:  # noqa: BLE001
        return {"managed": 0, "moved": 0, "reason": f"POSITIONS_UNAVAILABLE: {exc!r}"}
    if not positions:
        return {"managed": 0, "moved": 0}

    state = _load_state()
    moved = 0
    managed = 0
    live_tickets = set()

    for pos in positions:
        if not _is_ours(pos):
            continue
        managed += 1
        tk = str(pos.ticket)
        live_tickets.add(tk)
        try:
            side = 1 if int(pos.type) == 0 else -1      # 0=buy→long, 1=sell→short
            entry = float(pos.price_open)
            cur = float(pos.price_current)
            cur_sl = float(pos.sl) if pos.sl else None

            # R initial = distance entrée↔SL d'origine. Enregistré la 1re fois qu'on voit
            # la position (le SL n'a pas encore bougé). Persisté pour survivre au restart.
            st = state.get(tk)
            if st is None:
                if cur_sl is None or abs(entry - cur_sl) <= 0:
                    continue                              # pas de SL exploitable → on ne gère pas
                st = {"entry": entry, "r": abs(entry - cur_sl), "phase": "init", "peak_fav_r": 0.0}
                state[tk] = st
            r = float(st["r"])
            if r <= 0:
                continue

            # Identité de la position — nécessaire à l'enregistreur d'excursions (les YEUX
            # de Cloe) à la clôture, quand MT5 ne la voit plus. Écrit à CHAQUE passage tant
            # qu'il manque : rétro-comble les positions déjà suivies avant la greffe.
            if st.get("side") is None or st.get("symbol") is None:
                st["side"] = side
                st["symbol"] = pos.symbol
                if st.get("tp_initial_R") is None and pos.tp:
                    st["tp_initial_R"] = round((float(pos.tp) - entry) / r * side, 4)

            fav_r = (cur - entry) / r * side               # excursion favorable en R
            st["peak_fav_r"] = max(float(st.get("peak_fav_r", 0.0)), fav_r)
            peak = float(st["peak_fav_r"])

            # ── YEUX DE CLOE : MAE/MFE/giveback, gratuit (on est déjà dans la boucle,
            # aucun appel MT5 en plus). Fail-safe : n'interrompt jamais la gestion.
            try:
                from feedback.excursion_tracker import observe as _observe_excursion
                _observe_excursion(st, side=side, entry=entry, cur=cur, r=r)
            except Exception:  # noqa: BLE001
                pass

            # Distance de stop minimale du broker (mêmes bornes que l'exécuteur).
            si = mt5.symbol_info(pos.symbol)
            tick = mt5.symbol_info_tick(pos.symbol)
            point = float(getattr(si, "point", 0) or 0)
            stops_lvl = float(getattr(si, "trade_stops_level", 0) or 0)
            spread = float((tick.ask - tick.bid)) if tick else 0.0
            min_dist = max(stops_lvl * point, spread) * 1.2

            new_sl = None
            # 1) BREAKEVEN : SL → entrée (+ buffer coûts) dès +breakeven_r.
            if st["phase"] == "init" and fav_r >= breakeven_r:
                buffer = max(spread, 0.05 * r)
                new_sl = entry + side * buffer
                st["phase"] = "breakeven"
            # 2) TRAILING : suit le plus-haut favorable à trail_dist_r derrière.
            if peak >= trail_start_r:
                trail_sl = entry + side * (peak - trail_dist_r) * r
                # garder le meilleur des deux (breakeven éventuel + trailing)
                if new_sl is None or side * (trail_sl - new_sl) > 0:
                    new_sl = trail_sl
                if st["phase"] != "trailing":
                    st["phase"] = "trailing"

            if new_sl is None:
                continue

            # Ne JAMAIS élargir le risque : le SL ne bouge que dans le sens favorable.
            if cur_sl is not None and side * (new_sl - cur_sl) <= 0:
                continue
            # Respect de la distance minimale au prix courant (sinon rejet 10016).
            if side * (cur - new_sl) < min_dist:
                continue

            digits = int(getattr(si, "digits", 5))
            req = {
                "action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket,
                "symbol": pos.symbol, "sl": round(new_sl, digits),
                "tp": round(float(pos.tp), digits) if pos.tp else 0.0,
                "magic": MAGIC,
            }
            res = mt5.order_send(req)
            done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            if getattr(res, "retcode", None) == done:
                moved += 1
                logger.info("[DEMO-MANAGE] %s #%s SL %.5f→%.5f (%s, fav=%.2fR peak=%.2fR)",
                            pos.symbol, tk, cur_sl or 0.0, new_sl, st["phase"], fav_r, peak)
            else:
                logger.debug("[DEMO-MANAGE] %s #%s modif SL refusée retcode=%s %s",
                             pos.symbol, tk, getattr(res, "retcode", None),
                             getattr(res, "comment", ""))
        except Exception as exc:  # noqa: BLE001 — une position ne casse pas la boucle
            logger.debug("[DEMO-MANAGE] %s: %r", getattr(pos, "symbol", "?"), exc)
            continue

    # Purge des tickets fermés (évite un état qui gonfle indéfiniment).
    # ⚠️ Un ticket qui disparaît = une position qui vient de SE FERMER : c'est le SEUL
    # instant où l'on connaît encore son contexte d'entrée ET son résultat. On enregistre
    # la CONSÉQUENCE ici (yeux de Cloe) AVANT d'oublier. Fail-safe intégral.
    for tk in list(state.keys()):
        if tk not in live_tickets:
            try:
                from feedback.excursion_tracker import record_closed
                record_closed(mt5, tk, state[tk])
            except Exception:  # noqa: BLE001 — l'enregistrement ne casse jamais la purge
                pass
            state.pop(tk, None)
    _save_state(state)
    return {"managed": managed, "moved": moved}


async def manage_loop() -> None:
    """Boucle async de gestion dynamique. Gated DEMO_EXEC_ENABLED + DEMO_MANAGE_ENABLED."""
    import asyncio
    import os
    from data.mt5_provider import mt5_lock

    if os.getenv("DEMO_EXEC_ENABLED", "0") != "1" or os.getenv("DEMO_MANAGE_ENABLED", "0") != "1":
        logger.info("[DEMO-MANAGE] désarmé (DEMO_EXEC_ENABLED/DEMO_MANAGE_ENABLED)")
        return
    seconds = int(_cfg_float("DEMO_MANAGE_SECONDS", 15))
    be_r = _cfg_float("DEMO_BREAKEVEN_R", 0.8)
    ts_r = _cfg_float("DEMO_TRAIL_START_R", 1.2)
    td_r = _cfg_float("DEMO_TRAIL_DIST_R", 0.8)
    logger.info("[DEMO-MANAGE] boucle active — breakeven=+%.2fR trailing dès +%.2fR (dist %.2fR), %ss",
                be_r, ts_r, td_r, seconds)
    import MetaTrader5 as mt5
    await asyncio.sleep(35)      # laisser le démarrage se stabiliser
    while True:
        try:
            def _work():
                with mt5_lock:
                    return manage_once(mt5, breakeven_r=be_r, trail_start_r=ts_r, trail_dist_r=td_r)
            rep = await asyncio.to_thread(_work)
            if rep.get("moved"):
                logger.info("[DEMO-MANAGE] %s SL réajusté(s) sur %s position(s) gérée(s)",
                            rep["moved"], rep["managed"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DEMO-MANAGE] boucle: %r", exc)
        await asyncio.sleep(seconds)
