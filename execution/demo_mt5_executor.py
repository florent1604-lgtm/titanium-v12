"""execution/demo_mt5_executor.py — Exécution DEMO MT5 (étape D). rev.2 (revue Codex).

Étape (D) « ordres DEMO » du chemin gated. VRAIS `order_send`, UNIQUEMENT sur un
compte DÉMO vérifié programmatiquement (mur vers le compte RÉEL, non négociable).

Corrections revue Codex 2026-07-13 (REQUEST CHANGES) :
  P0-1 kill-switch journalier ACTIF : référence d'equity de début de journée
       persistante/datée/atomique (`data/demo_day_ref.json`) ; corruption ⇒ refus.
  P0-2 dédup/plafond FAIL-CLOSED : toute indisponibilité `positions_get` ⇒ refus
       `POSITIONS_UNAVAILABLE` (voir demo_bridge).
  P0-3 sizing : arrondi INFÉRIEUR au pas + refus si lot min > budget risque +
       vérification de la perte réelle via `order_calc_profit`.
  P0-4 course compte : `assert_demo_or_raise` RE-JOUÉ juste avant `order_check`
       et `order_send`, sous le même mt5_lock (tenu par l'appelant).
  P1   side strict (long|buy|short|sell) ; `order_check` avant `order_send`.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
DAY_REF_PATH = ROOT / "data" / "demo_day_ref.json"

EXPECTED_DEMO_LOGIN = int(os.getenv("DEMO_EXPECTED_LOGIN", "50061786"))
REAL_ACCOUNT_LOGIN = 60261188   # Axi-US52-Live — interdit d'exécution

_LONG = {"long", "buy"}
_SHORT = {"short", "sell"}


def _cfg_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _cfg_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class DemoGuards:
    enabled: bool = os.getenv("DEMO_EXEC_ENABLED", "0") == "1"
    risk_pct: float = _cfg_float("DEMO_RISK_PCT", 0.5)
    max_positions: int = _cfg_int("DEMO_MAX_POSITIONS", 3)
    # Multi-positions PAR ACTIF (Florent 25/07 : « on autorise la prise de multi position
    # par actif en cas de setup meilleur jusqu'à 3 »). Défaut 1 → comportement historique
    # (une seule position par symbole). >1 → on empile, mais SEULEMENT si le nouveau setup
    # est STRICTEMENT meilleur (plus de piliers) et de MÊME sens (pas de hedge). Cf. demo_bridge.
    max_pos_per_symbol: int = _cfg_int("DEMO_MAX_POS_PER_SYMBOL", 1)
    daily_loss_limit_pct: float = _cfg_float("DEMO_DAILY_LOSS_LIMIT_PCT", 5.0)
    max_spread_points: int = _cfg_int("DEMO_MAX_SPREAD_POINTS", 40)      # legacy (non utilisé)
    # Garde de spread en POURCENTAGE (instrument-agnostique). Les « points » ne sont pas
    # comparables entre actifs (BTC point=0.01 → un spread normal de 0.02% = 1200 points).
    max_spread_pct: float = _cfg_float("DEMO_MAX_SPREAD_PCT", 0.5)
    min_free_margin_pct: float = _cfg_float("DEMO_MIN_FREE_MARGIN_PCT", 40.0)
    risk_tolerance: float = _cfg_float("DEMO_RISK_TOLERANCE", 1.15)   # marge de vérif sizing
    # Phase de TEST (Florent 25/07) : adapter le budget de risque au LOT MINIMUM de chaque
    # actif (sinon RISK_LOT_MIN_EXCEEDS bloque les actifs chers, ex. BTCUSD). Défaut OFF →
    # sizing normal inchangé. Borné par min_lot_max_risk_pct (plafond de sécurité).
    min_lot_test: bool = os.getenv("DEMO_MIN_LOT_TEST", "0") == "1"
    min_lot_max_risk_pct: float = _cfg_float("DEMO_MIN_LOT_MAX_RISK_PCT", 5.0)
    # Garde de spread ADAPTATIF par actif, équilibré à la POSITION (Florent 25/07) : le
    # spread ne bloque que s'il dépasse cette FRACTION de la distance de SL (propre à chaque
    # actif via l'ATR). Si la position est viable (spread petit vs son risque), elle PASSE —
    # quel que soit le % absolu. `max_spread_pct` ne reste qu'un plafond de sanité (cote cassée).
    max_spread_frac_of_sl: float = _cfg_float("DEMO_MAX_SPREAD_FRAC_OF_SL", 0.75)

    @classmethod
    def from_env(cls) -> "DemoGuards":
        return cls(
            enabled=os.getenv("DEMO_EXEC_ENABLED", "0") == "1",
            risk_pct=_cfg_float("DEMO_RISK_PCT", 0.5),
            max_positions=_cfg_int("DEMO_MAX_POSITIONS", 3),
            max_pos_per_symbol=_cfg_int("DEMO_MAX_POS_PER_SYMBOL", 1),
            daily_loss_limit_pct=_cfg_float("DEMO_DAILY_LOSS_LIMIT_PCT", 5.0),
            max_spread_points=_cfg_int("DEMO_MAX_SPREAD_POINTS", 40),
            max_spread_pct=_cfg_float("DEMO_MAX_SPREAD_PCT", 0.5),
            min_free_margin_pct=_cfg_float("DEMO_MIN_FREE_MARGIN_PCT", 40.0),
            risk_tolerance=_cfg_float("DEMO_RISK_TOLERANCE", 1.15),
            min_lot_test=os.getenv("DEMO_MIN_LOT_TEST", "0") == "1",
            min_lot_max_risk_pct=_cfg_float("DEMO_MIN_LOT_MAX_RISK_PCT", 5.0),
            max_spread_frac_of_sl=_cfg_float("DEMO_MAX_SPREAD_FRAC_OF_SL", 0.75),
        )


class DemoExecutionRefused(Exception):
    """Levée fail-closed quand une condition de sécurité n'est pas remplie."""


# ── Garde-fou N°1 : compte DÉMO attendu ──────────────────────────────────────

def assert_demo_or_raise(mt5: Any) -> dict:
    info = mt5.account_info()
    if info is None:
        raise DemoExecutionRefused("RISK_NO_ACCOUNT: aucun compte MT5 connecté.")
    demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
    if info.trade_mode != demo_mode:
        raise DemoExecutionRefused(
            f"RISK_NOT_DEMO: compte NON démo (trade_mode={info.trade_mode}, "
            f"login={info.login}).")
    if int(info.login) == REAL_ACCOUNT_LOGIN:
        raise DemoExecutionRefused(f"RISK_REAL_LOGIN: login réel {info.login} — refus absolu.")
    if int(info.login) != EXPECTED_DEMO_LOGIN:
        raise DemoExecutionRefused(
            f"RISK_UNEXPECTED_LOGIN: login {info.login} ≠ démo attendu {EXPECTED_DEMO_LOGIN}.")
    return {"login": info.login, "server": info.server, "currency": info.currency,
            "balance": info.balance, "equity": info.equity,
            "free_margin": getattr(info, "margin_free", None)}


# ── Garde-fou N°1bis : référence d'equity journalière (kill-switch) ───────────

def establish_day_ref(current_equity: float, *, path: Path = DAY_REF_PATH,
                      today: Optional[str] = None) -> float:
    """Retourne l'equity de début de journée (UTC). Initialise/roll-over si
    besoin (atomique). Corruption d'un fichier existant ⇒ refus (fail-closed)."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if path.exists():
        try:
            ref = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise DemoExecutionRefused("RISK_DAYREF_CORRUPT: référence journalière illisible.")
        if (isinstance(ref, dict) and ref.get("date") == today
                and isinstance(ref.get("start_equity"), (int, float))
                and math.isfinite(ref["start_equity"]) and ref["start_equity"] > 0):
            return float(ref["start_equity"])
    try:
        from utils.atomic_state import save_json_atomic
        save_json_atomic(path, {"date": today, "start_equity": float(current_equity),
                                "written": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        raise DemoExecutionRefused(f"RISK_DAYREF_WRITE: écriture référence impossible ({exc}).")
    return float(current_equity)


def preflight(mt5: Any, guards: Optional[DemoGuards] = None,
              day_start_equity: Optional[float] = None) -> dict:
    guards = guards or DemoGuards()
    if not guards.enabled:
        return {"ok": False, "reason": "DEMO_EXEC_ENABLED=0 (désarmé)."}
    try:
        account = assert_demo_or_raise(mt5)
    except DemoExecutionRefused as exc:
        return {"ok": False, "reason": str(exc)}
    if day_start_equity and day_start_equity > 0:
        dd = (day_start_equity - account["equity"]) / day_start_equity * 100.0
        if dd >= guards.daily_loss_limit_pct:
            return {"ok": False, "account": account,
                    "reason": f"KILL_SWITCH: perte journalière {dd:.1f}% ≥ "
                              f"{guards.daily_loss_limit_pct}%."}
    eq = account["equity"] or 0.0
    fm = account["free_margin"] or 0.0
    if eq > 0 and (fm / eq * 100.0) < guards.min_free_margin_pct:
        return {"ok": False, "account": account,
                "reason": f"RISK_LOW_MARGIN: marge libre < {guards.min_free_margin_pct}%."}
    return {"ok": True, "account": account, "guards": guards}


# ── Garde-fou N°3 : sizing arrondi INFÉRIEUR + refus si min > budget ─────────

def compute_lot(mt5: Any, symbol: str, entry: float, sl: float,
                risk_money: float) -> float:
    si = mt5.symbol_info(symbol)
    if si is None:
        raise DemoExecutionRefused(f"RISK_NO_SYMBOL: {symbol} indisponible.")
    tick_size = getattr(si, "trade_tick_size", 0) or getattr(si, "point", 0)
    tick_value = getattr(si, "trade_tick_value", 0)
    dist = abs(float(entry) - float(sl))
    if not (tick_size and tick_value) or dist <= 0 or risk_money <= 0:
        raise DemoExecutionRefused(f"RISK_SIZING: paramètres invalides pour {symbol}.")
    money_per_lot = dist / tick_size * tick_value
    if money_per_lot <= 0:
        raise DemoExecutionRefused(f"RISK_SIZING: money_per_lot ≤ 0 pour {symbol}.")
    raw = risk_money / money_per_lot
    step = getattr(si, "volume_step", 0.01) or 0.01
    vmin = getattr(si, "volume_min", 0.01) or 0.01
    vmax = getattr(si, "volume_max", 100.0) or 100.0
    # arrondi INFÉRIEUR au pas (ne jamais dépasser le budget risque)
    lot = math.floor(raw / step) * step
    lot = round(lot, 4)
    if lot < vmin - 1e-9:
        raise DemoExecutionRefused(
            f"RISK_LOT_MIN_EXCEEDS: lot min {vmin} dépasse le budget risque "
            f"({risk_money:.2f}) pour {symbol}.")
    return round(min(lot, vmax), 4)


def _min_lot_risk(mt5: Any, symbol: str, entry: float, sl: float) -> Optional[float]:
    """Risque monétaire du LOT MINIMUM de l'actif = money_per_lot × volume_min.
    Sert à la phase de test pour adapter le budget au lot min. Fail-safe : None si
    indéterminable → aucune adaptation, le refus normal est conservé."""
    try:
        si = mt5.symbol_info(symbol)
        if si is None:
            return None
        tick_size = getattr(si, "trade_tick_size", 0) or getattr(si, "point", 0)
        tick_value = getattr(si, "trade_tick_value", 0)
        dist = abs(float(entry) - float(sl))
        if not (tick_size and tick_value) or dist <= 0:
            return None
        money_per_lot = dist / tick_size * tick_value
        vmin = getattr(si, "volume_min", 0.01) or 0.01
        risk = money_per_lot * vmin
        return risk if risk > 0 and math.isfinite(risk) else None
    except Exception:  # noqa: BLE001
        return None


def _verify_risk(mt5: Any, symbol: str, is_long: bool, lot: float, entry: float,
                 sl: float, risk_money: float, tolerance: float) -> Optional[str]:
    """Vérifie la perte réelle au SL via order_calc_profit. FAIL-CLOSED (rev.3,
    revue Codex) : si order_calc_profit est absent, lève, renvoie None ou une
    valeur non finie → REFUS (on ne peut pas prouver le risque → on n'ouvre pas).
    Retourne un motif de refus, ou None si la perte est finie et dans le budget."""
    calc = getattr(mt5, "order_calc_profit", None)
    if calc is None:
        return "RISK_CALC_UNAVAILABLE: order_calc_profit indisponible."
    otype = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL
    try:
        profit = calc(otype, symbol, lot, entry, sl)
    except Exception as exc:  # noqa: BLE001
        return f"RISK_CALC_ERROR: order_calc_profit a levé ({exc!r})."
    if profit is None:
        return "RISK_CALC_NONE: order_calc_profit a renvoyé None."
    try:
        loss = abs(float(profit))
    except (TypeError, ValueError):
        return f"RISK_CALC_INVALID: profit non numérique ({profit!r})."
    if not math.isfinite(loss):
        return "RISK_CALC_NONFINITE: profit non fini (NaN/inf)."
    if loss > risk_money * tolerance:
        return (f"RISK_EXCEEDED: perte au SL {loss:.2f} > budget "
                f"{risk_money:.2f}×{tolerance} pour {symbol}.")
    return None


# ── Ouverture d'un ordre marché (fail-closed, séquence sûre) ─────────────────

def place_market_order(mt5: Any, symbol: str, side: str, atr: float,
                       sl_atr_mult: float = 2.0, tp_atr_mult: float = 3.0,
                       guards: Optional[DemoGuards] = None,
                       day_start_equity: Optional[float] = None,
                       day_ref_path: Optional[Path] = None,
                       magic: int = 500786, comment: str = "titanium-demo",
                       size_factor: float = 1.0) -> dict:
    guards = guards or DemoGuards()
    # CONVICTION → TAILLE : le cerveau/émotion (brain_gate) fournit un facteur ∈ [0,1] qui
    # module le risque ENGAGÉ (jamais au-dessus du risk_pct configuré). Borné [0.05, 1.0].
    try:
        size_factor = max(0.05, min(1.0, float(size_factor)))
    except (TypeError, ValueError):
        size_factor = 1.0

    # P1 : side dans l'ensemble fermé (sinon refus, plus de « défaut short »).
    s = str(side).strip().lower()
    if s not in _LONG | _SHORT:
        return {"sent": False, "reason": f"INVALID_SIDE: {side!r}."}
    is_long = s in _LONG

    # rev.3 : config non finie/non positive → refus (protège d'un .env corrompu).
    for cname, cval in (("risk_pct", guards.risk_pct),
                        ("daily_loss_limit_pct", guards.daily_loss_limit_pct),
                        ("min_free_margin_pct", guards.min_free_margin_pct),
                        ("risk_tolerance", guards.risk_tolerance)):
        if not (isinstance(cval, (int, float)) and math.isfinite(cval) and cval > 0):
            return {"sent": False, "reason": f"CONFIG_INVALID: {cname}={cval!r}."}

    # Préflight (compte démo + marge). Kill-switch appliqué ensuite avec la réf. jour.
    pf = preflight(mt5, guards)
    if not pf["ok"]:
        return {"sent": False, "reason": pf["reason"]}
    equity = pf["account"]["equity"]

    # P0-1 : référence journalière + kill-switch ACTIF.
    # `day_ref_path` est INJECTABLE : sans ça, un test avec un faux MT5 écrivait la
    # référence de PRODUCTION avec son equity fictive (incident 15/07/2026 :
    # start_equity=1000.0 écrit alors que le compte réel était à 950.08) — le
    # kill-switch se serait appuyé sur une base inventée par un test.
    if day_start_equity is None:
        try:
            day_start_equity = establish_day_ref(
                equity, path=day_ref_path or DAY_REF_PATH)
        except DemoExecutionRefused as exc:
            return {"sent": False, "reason": str(exc)}
    if day_start_equity and day_start_equity > 0:
        dd = (day_start_equity - equity) / day_start_equity * 100.0
        if dd >= guards.daily_loss_limit_pct:
            return {"sent": False, "reason": f"KILL_SWITCH: perte journalière "
                                             f"{dd:.1f}% ≥ {guards.daily_loss_limit_pct}%."}

    # Marché ouvert + cotation
    if not mt5.symbol_select(symbol, True):
        return {"sent": False, "reason": f"MARKET_UNAVAILABLE: {symbol}."}
    si = mt5.symbol_info(symbol)
    disabled = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)
    if si is None or si.trade_mode == disabled:
        return {"sent": False, "reason": f"MARKET_CLOSED: {symbol}."}
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or not (tick.ask and tick.bid):
        return {"sent": False, "reason": f"MARKET_CLOSED: pas de cotation {symbol}."}

    # Plafond de SANITÉ absolu (cote cassée). Le vrai garde de spread est ADAPTATIF
    # (équilibré à la position), calculé plus bas une fois le SL connu.
    mid = (tick.ask + tick.bid) / 2.0
    spread_abs = tick.ask - tick.bid
    spread_pct = (spread_abs / mid * 100.0) if mid > 0 else 1e9
    if spread_pct > guards.max_spread_pct:
        return {"sent": False, "reason": f"RISK_SPREAD_ABS: {spread_pct:.3f}% > "
                                         f"{guards.max_spread_pct}% (cote anormale) pour {symbol}."}

    price = tick.ask if is_long else tick.bid
    sign = 1 if is_long else -1
    sl = price - sign * sl_atr_mult * atr
    tp = price + sign * tp_atr_mult * atr
    # Distance MINIMALE de stop du broker (sinon retcode 10016 « Invalid stops »,
    # fréquent le week-end quand l'ATR est petit face à un spread large). On élargit
    # SL/TP au besoin ; compute_lot resize ensuite le lot -> le RISQUE reste borné.
    try:
        _pt = float(getattr(si, "point", 0) or 0)
        _stops = float(getattr(si, "trade_stops_level", 0) or 0)
        _min_dist = max(_stops * _pt, float(tick.ask - tick.bid)) * 1.5
        if _min_dist > 0:
            if abs(price - sl) < _min_dist:
                sl = price - sign * _min_dist
            if abs(price - tp) < _min_dist:
                tp = price + sign * _min_dist
    except Exception:  # noqa: BLE001 — l'ajustement ne doit jamais bloquer un ordre
        pass
    # Garde de spread ADAPTATIF (équilibré à la position, Florent) : ne bloque QUE si le
    # spread dépasse une fraction de la distance de SL — propre à chaque actif via l'ATR.
    # Si la position est viable (spread petit vs son risque), elle PASSE.
    _sl_dist = abs(price - sl)
    _spread_frac = (spread_abs / _sl_dist) if _sl_dist > 0 else 1e9
    if _spread_frac > guards.max_spread_frac_of_sl:
        return {"sent": False, "reason": f"RISK_SPREAD_REL: spread = {_spread_frac * 100:.0f}% du SL "
                f"(> {guards.max_spread_frac_of_sl * 100:.0f}%) pour {symbol}."}
    risk_money = equity * guards.risk_pct / 100.0 * size_factor   # conviction → taille
    # PHASE DE TEST (DEMO_MIN_LOT_TEST) : si le budget ne couvre pas le LOT MINIMUM de
    # l'actif, on l'adapte AUTOMATIQUEMENT (par actif) pour placer un lot min — MAIS borné
    # par un plafond de sécurité (DEMO_MIN_LOT_MAX_RISK_PCT % de l'equity). Sinon le refus
    # RISK_LOT_MIN_EXCEEDS reste conservé (fail-safe si _min_lot_risk indéterminable).
    if guards.min_lot_test:
        mlr = _min_lot_risk(mt5, symbol, price, sl)
        if mlr is not None and mlr > risk_money:
            ceiling = equity * guards.min_lot_max_risk_pct / 100.0
            if mlr <= ceiling:
                risk_money = mlr * guards.risk_tolerance
    try:
        lot = compute_lot(mt5, symbol, price, sl, risk_money)
    except DemoExecutionRefused as exc:
        return {"sent": False, "reason": str(exc)}

    # P0-3 : vérif de la perte réelle au SL.
    refus = _verify_risk(mt5, symbol, is_long, lot, price, sl, risk_money, guards.risk_tolerance)
    if refus:
        return {"sent": False, "reason": refus}

    digits = getattr(si, "digits", 5)
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL,
        "price": price, "sl": round(sl, digits), "tp": round(tp, digits),
        "deviation": 20, "magic": magic, "comment": comment,
        "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
        "type_filling": getattr(mt5, "ORDER_FILLING_IOC", 1),
    }

    # order_check broker OBLIGATOIRE (rev.3, revue Codex) — fail-closed :
    # absent/lève/None → REFUS (on n'envoie jamais sans validation broker).
    checker = getattr(mt5, "order_check", None)
    if checker is None:
        return {"sent": False, "reason": "ORDER_CHECK_UNAVAILABLE"}
    try:
        chk = checker(req)
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": f"ORDER_CHECK_ERROR: {exc!r}"}
    if chk is None:
        return {"sent": False, "reason": "ORDER_CHECK_NONE"}
    chk_rc = getattr(chk, "retcode", None)
    if chk_rc not in (0, getattr(mt5, "TRADE_RETCODE_DONE", 10009)):
        return {"sent": False, "reason": f"ORDER_CHECK_REJECTED: retcode={chk_rc} "
                                         f"{getattr(chk, 'comment', '')}"}

    # P0-4 rev.3 : re-validation démo IMMÉDIATEMENT avant l'envoi, APRÈS order_check
    # — dernier appel MT5 avant order_send : ferme la fenêtre de bascule pendant
    # order_check. (Isolation d'un terminal démo dédié = durcissement suivant.)
    try:
        assert_demo_or_raise(mt5)
    except DemoExecutionRefused as exc:
        return {"sent": False, "reason": f"RACE_ACCOUNT_CHANGED: {exc}"}

    res = mt5.order_send(req)
    done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
    retcode = getattr(res, "retcode", None)
    ok = retcode == done
    # `order` = ticket de l'ordre (== position_id d'ouverture pour un ordre au marché) :
    # INDISPENSABLE pour relier plus tard la décision à son RÉSULTAT réel (SL/TP, P&L) via
    # positions_get / history_deals. `ticket` en est l'alias consommé par le journal.
    order = getattr(res, "order", None)
    return {"sent": ok, "retcode": retcode, "lot": lot, "price": price,
            "sl": sl, "tp": tp, "side": "long" if is_long else "short",
            "symbol": symbol, "risk_money": round(risk_money, 2),
            "comment": getattr(res, "comment", ""),
            "order": order, "deal": getattr(res, "deal", None), "ticket": order,
            "reason": None if ok else f"ORDER_REJECTED: retcode={retcode} "
                                      f"{getattr(res, 'comment', '')}"}
