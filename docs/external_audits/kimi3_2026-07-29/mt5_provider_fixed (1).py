"""data/mt5_provider.py — Connecteur MetaTrader5 (Axi) : données uniquement.

Fournit les barres H1 et les ticks des symboles forex/or au moteur forex.
AUCUN ordre n'est envoyé par ce module : le compte relié est un compte LIVE,
l'exécution réelle est volontairement absente (paper trading côté Titanium).

PATCH v12.1 :
- _selected protégé par RLock
- symbol_select vérifié avec retry
- Reconnexion MT5 avec backoff
- Timeout explicite sur les appels bloquants
- Exceptions explicites au lieu de None silencieux
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

# ── Verrou global ──────────────────────────────────────────────────────────────
mt5_lock = threading.RLock()

_initialized = False
_init_failures = 0
_init_last_try = 0.0

_account_snapshot_cache: Dict[str, Any] = {}
_account_snapshot_cache_at = 0.0
ACCOUNT_SNAPSHOT_CACHE_SECONDS = 15.0

_selected: set = set()
_selected_lock = threading.Lock()  # 🔒 Protection du set _selected


# ── Helpers ────────────────────────────────────────────────────────────────────

def _server_epoch_to_utc(values, *, server_timezone: Optional[str] = None) -> pd.DatetimeIndex:
    """Convertit les epochs encodant l'heure murale du serveur MT5 en vrais UTC."""
    tz_name = server_timezone or os.getenv("MT5_SERVER_TIMEZONE", "Europe/Helsinki")
    naive = pd.DatetimeIndex(pd.to_datetime(values, unit="s"))
    localized = naive.tz_localize(tz_name, ambiguous="infer", nonexistent="shift_forward")
    return localized.tz_convert("UTC")


class MT5DisconnectedError(Exception):
    """MT5 n'est pas initialisé ou le terminal est fermé."""
    pass


class MT5SymbolError(Exception):
    """Symbole introuvable ou non sélectionnable sur le broker."""
    pass


class MT5DataError(Exception):
    """MT5 connecté mais retourne des données vides (marché fermé, pas de ticks)."""
    pass


# ── Initialisation avec backoff ───────────────────────────────────────────────

def ensure_init(max_retries: int = 3, backoff: float = 1.0) -> bool:
    """Initialise la connexion au terminal MT5 avec retry exponentiel."""
    global _initialized, _init_failures, _init_last_try

    if not MT5_AVAILABLE:
        raise MT5DisconnectedError("MetaTrader5 non installé (ImportError)")

    if _initialized:
        # Vérification proactive : le terminal est-il toujours vivant ?
        try:
            if mt5.terminal_info() is None:
                _initialized = False
                logger.warning("[MT5] Terminal_info=None — connexion perdue, reconnexion...")
        except Exception:
            _initialized = False
            logger.warning("[MT5] Exception terminal_info — reconnexion...")

    if _initialized:
        return True

    # Backoff pour éviter le spam si MT5 est fermé
    now = time.monotonic()
    if now - _init_last_try < min(backoff * (2 ** _init_failures), 30.0):
        return False
    _init_last_try = now

    with mt5_lock:
        if _initialized:
            return True

        for attempt in range(1, max_retries + 1):
            try:
                if mt5.initialize():
                    _initialized = True
                    _init_failures = 0
                    acc = mt5.account_info()
                    logger.info("[MT5] Connecté — compte %s @ %s (tentative %d/%d)",
                                acc.login if acc else "?", acc.server if acc else "?",
                                attempt, max_retries)
                    return True
                else:
                    err = mt5.last_error()
                    logger.warning("[MT5] initialize() échoué (tentative %d/%d): %s",
                                   attempt, max_retries, err)
                    if attempt < max_retries:
                        time.sleep(backoff * (2 ** (attempt - 1)))
            except Exception as e:
                logger.warning("[MT5] Exception initialize() (tentative %d/%d): %s",
                               attempt, max_retries, e)
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** (attempt - 1)))

        _init_failures += 1
        logger.error("[MT5] Échec définitif après %d tentatives", max_retries)
        return False


def shutdown() -> None:
    global _initialized
    if MT5_AVAILABLE and _initialized:
        mt5.shutdown()
        _initialized = False
        logger.info("[MT5] Déconnecté proprement")


# ── Sélection symbole thread-safe ──────────────────────────────────────────────

def _ensure_symbol(symbol: str) -> None:
    """Sélectionne le symbole sur MT5 de manière thread-safe.
    Lève MT5SymbolError si le symbole est introuvable."""
    with _selected_lock:
        if symbol in _selected:
            return

        with mt5_lock:
            ok = mt5.symbol_select(symbol, True)
            if not ok:
                err = mt5.last_error()
                raise MT5SymbolError(
                    f"symbol_select({symbol}) échoué: {err} — "
                    f"symbole inexistant ou marché fermé"
                )
            _selected.add(symbol)
            logger.debug("[MT5] Symbole sélectionné: %s", symbol)


# ── Récupération des données ───────────────────────────────────────────────────

def get_rates_h1(symbol: str, n: int = 300) -> pd.DataFrame:
    """n dernières barres H1. Lève une exception explicite si données indisponibles."""
    if not ensure_init():
        raise MT5DisconnectedError("MT5 non initialisé — terminal fermé ou non répondant")

    _ensure_symbol(symbol)

    with mt5_lock:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, n)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        raise MT5DataError(
            f"copy_rates_from_pos({symbol}, H1) retourne vide — "
            f"marché fermé, pas d'historique, ou erreur MT5: {err}"
        )

    df = pd.DataFrame(rates)
    df.index = _server_epoch_to_utc(df["time"])
    return df[["open", "high", "low", "close"]].astype(float)


_TF = {}

def get_rates(symbol: str, tf: str = "H1", n: int = 300) -> pd.DataFrame:
    """n dernières barres d'un timeframe arbitraire."""
    if not ensure_init():
        raise MT5DisconnectedError("MT5 non initialisé")

    if not _TF:
        _TF.update({
            "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        })

    _ensure_symbol(symbol)

    with mt5_lock:
        rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_H1), 0, n)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        raise MT5DataError(f"copy_rates({symbol}, {tf}) vide: {err}")

    df = pd.DataFrame(rates)
    df.index = _server_epoch_to_utc(df["time"])
    return df[["open", "high", "low", "close"]].astype(float)


def get_ohlcv(symbol: str, tf: str = "M15", n: int = 120) -> pd.DataFrame:
    """OHLCV avec volume."""
    if not ensure_init():
        raise MT5DisconnectedError("MT5 non initialisé")

    if not _TF:
        _TF.update({
            "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        })

    _ensure_symbol(symbol)

    with mt5_lock:
        rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M15), 0, n)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        raise MT5DataError(f"copy_rates({symbol}, {tf}) vide: {err}")

    df = pd.DataFrame(rates)
    df.index = _server_epoch_to_utc(df["time"])
    df = df.rename(columns={"tick_volume": "v"})
    cols = ["open", "high", "low", "close"]
    if "v" in df.columns:
        cols.append("v")
    return df[cols].astype(float)


def get_tick(symbol: str) -> Dict[str, Any]:
    """Dernier tick. Lève MT5DataError si pas de tick valide."""
    if not ensure_init():
        raise MT5DisconnectedError("MT5 non initialisé")

    _ensure_symbol(symbol)

    with mt5_lock:
        t = mt5.symbol_info_tick(symbol)

    if t is None:
        err = mt5.last_error()
        raise MT5DataError(f"symbol_info_tick({symbol}) retourne None: {err}")

    if t.bid <= 0 or t.ask <= 0:
        raise MT5DataError(
            f"Tick {symbol} invalide: bid={t.bid}, ask={t.ask} — "
            f"marché probablement fermé"
        )

    age = time.time() - t.time
    return {
        "bid": t.bid,
        "ask": t.ask,
        "mid": (t.bid + t.ask) / 2,
        "ts": datetime.fromtimestamp(t.time, tz=timezone.utc).isoformat(),
        "stale": age > 600,
        "age_seconds": round(age, 2),
    }


def get_ticks_fast(symbols) -> Dict[str, Dict[str, Any]]:
    """Ticks multi-symboles. Retourne uniquement les symboles valides,
    loggue les échecs sans planter."""
    if not ensure_init():
        raise MT5DisconnectedError("MT5 non initialisé")

    out: Dict[str, Dict[str, Any]] = {}
    errors: list[str] = []

    with mt5_lock:
        for s in symbols:
            try:
                _ensure_symbol(s)
                t = mt5.symbol_info_tick(s)
                if not t or t.bid <= 0 or t.ask <= 0:
                    errors.append(f"{s}: tick invalide")
                    continue
                mid = (t.bid + t.ask) / 2
                out[s] = {
                    "bid": t.bid,
                    "ask": t.ask,
                    "mid": mid,
                    "ts_msc": int(t.time_msc),
                    "spread_bps": round((t.ask - t.bid) / mid * 10000, 2) if mid else 0.0,
                }
            except MT5SymbolError as e:
                errors.append(str(e))
            except Exception as e:
                errors.append(f"{s}: {e}")

    if errors:
        logger.warning("[MT5] get_ticks_fast échecs partiels (%d/%d): %s",
                       len(errors), len(symbols), "; ".join(errors[:3]))

    return out


# ── Account snapshot ───────────────────────────────────────────────────────────

def account_snapshot() -> Dict[str, Any]:
    global _account_snapshot_cache, _account_snapshot_cache_at

    if not ensure_init():
        return {"connected": False, "available": MT5_AVAILABLE, "reason": "MT5_NOT_INITIALIZED"}

    now = time.monotonic()
    if (_account_snapshot_cache
            and now - _account_snapshot_cache_at < ACCOUNT_SNAPSHOT_CACHE_SECONDS):
        return dict(_account_snapshot_cache)

    if not mt5_lock.acquire(timeout=1.0):
        if _account_snapshot_cache:
            cached = dict(_account_snapshot_cache)
            cached["telemetry_stale"] = True
            cached["reason"] = "MT5_BUSY_LOCK_TIMEOUT"
            cached["cache_age_sec"] = round(now - _account_snapshot_cache_at, 1)
            return cached
        return {"connected": False, "available": MT5_AVAILABLE, "reason": "MT5_BUSY_LOCK_TIMEOUT"}

    try:
        now = time.monotonic()
        if (_account_snapshot_cache
                and now - _account_snapshot_cache_at < ACCOUNT_SNAPSHOT_CACHE_SECONDS):
            return dict(_account_snapshot_cache)

        acc = mt5.account_info()
        positions = mt5.positions_get() if acc is not None else None
    finally:
        mt5_lock.release()

    if acc is None:
        return {"connected": False, "available": MT5_AVAILABLE,
                "reason": "MT5_ACCOUNT_UNAVAILABLE", "last_error": mt5.last_error()}

    mode_by_value = {
        getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", object()): "demo",
        getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", object()): "contest",
        getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", object()): "real",
    }
    mode = mode_by_value.get(getattr(acc, "trade_mode", None), "unknown")
    demo_enabled = os.getenv("DEMO_EXEC_ENABLED", "0") == "1"

    safe_positions = []
    for position in positions or ():
        safe_positions.append({
            "ticket": getattr(position, "ticket", None),
            "symbol": getattr(position, "symbol", None),
            "side": (
                "long" if getattr(position, "type", None)
                == getattr(mt5, "POSITION_TYPE_BUY", 0) else "short"
            ),
            "volume": getattr(position, "volume", None),
            "price_open": getattr(position, "price_open", None),
            "price_current": getattr(position, "price_current", None),
            "sl": getattr(position, "sl", None),
            "tp": getattr(position, "tp", None),
            "profit": getattr(position, "profit", None),
            "magic": getattr(position, "magic", None),
            "comment": getattr(position, "comment", None),
        })

    floating_pnl = round(sum(float(item["profit"] or 0) for item in safe_positions), 2)

    if mode == "demo" and demo_enabled:
        note = "Exécution MT5 DÉMO armée — compte réel interdit par garde fail-closed"
    elif mode == "demo":
        note = "Compte MT5 DÉMO connecté — exécution Titanium désarmée"
    else:
        note = "MT5 en lecture seule — aucune exécution réelle autorisée"

    payload = {
        "connected": True,
        "login": acc.login,
        "server": acc.server,
        "currency": acc.currency,
        "mode": mode,
        "demo_execution_enabled": mode == "demo" and demo_enabled,
        "balance": getattr(acc, "balance", None),
        "equity": getattr(acc, "equity", None),
        "margin": getattr(acc, "margin", None),
        "margin_free": getattr(acc, "margin_free", None),
        "margin_level": getattr(acc, "margin_level", None),
        "positions_available": positions is not None,
        "position_count": len(safe_positions),
        "floating_pnl": floating_pnl,
        "positions": safe_positions,
        "note": note,
    }
    _account_snapshot_cache = payload
    _account_snapshot_cache_at = time.monotonic()
    return dict(payload)
