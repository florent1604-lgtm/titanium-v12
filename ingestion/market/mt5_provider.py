"""data/mt5_provider.py — Connecteur MetaTrader5 (Axi) : données uniquement.

Fournit les barres H1 et les ticks des symboles forex/or au moteur forex.
AUCUN ordre n'est envoyé par ce module : le compte relié est un compte LIVE,
l'exécution réelle est volontairement absente (paper trading côté Titanium).

Les appels MetaTrader5 sont bloquants → toujours passer par asyncio.to_thread
depuis les boucles asyncio (voir core/forex_engine.py).
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

# MetaTrader5 n'est PAS thread-safe : toutes les lectures (ticks, barres,
# univers, scan d'opportunités) passent par ce verrou pour sérialiser les
# appels mt5.* entre les boucles asyncio concurrentes (forex/swing/temps réel/
# scan). RLock car ensure_init() peut être appelé depuis une section déjà tenue.
mt5_lock = threading.RLock()

_initialized = False
_init_failures = 0
_init_next_retry_at = 0.0
_INIT_BACKOFF_BASE_SECONDS = 1.0
_INIT_BACKOFF_MAX_SECONDS = 30.0
_account_snapshot_cache: Dict[str, Any] = {}
_account_snapshot_cache_at = 0.0
ACCOUNT_SNAPSHOT_CACHE_SECONDS = 15.0


def _server_epoch_to_utc(values, *, server_timezone: Optional[str] = None) -> pd.DatetimeIndex:
    """Convertit les epochs encodant l'heure murale du serveur MT5 en vrais UTC.

    Axi expose des barres calées sur son heure serveur EET/EEST (UTC+2 l'hiver,
    UTC+3 l'été). Les interpréter directement avec ``utc=True`` avançait donc
    artificiellement leur index. Le fuseau IANA conserve les transitions DST ;
    il reste surchargeable pour un autre broker via ``MT5_SERVER_TIMEZONE``.
    """
    tz_name = server_timezone or os.getenv("MT5_SERVER_TIMEZONE", "Europe/Helsinki")
    naive = pd.DatetimeIndex(pd.to_datetime(values, unit="s"))
    localized = naive.tz_localize(tz_name, ambiguous="infer", nonexistent="shift_forward")
    return localized.tz_convert("UTC")


class MT5SymbolError(RuntimeError):
    """Le broker a refusé la sélection d'un symbole."""


def ensure_init() -> bool:
    """Initialise MT5 et retente avec backoff si le terminal est indisponible."""
    global _initialized, _init_failures, _init_next_retry_at
    if not MT5_AVAILABLE:
        return False
    with mt5_lock:
        if _initialized:
            terminal_probe = getattr(mt5, "terminal_info", None)
            if not callable(terminal_probe):
                return True
            try:
                if terminal_probe() is not None:
                    return True
            except Exception as exc:
                logger.warning("[MT5] Vérification terminal échouée: %s", exc)
            _initialized = False
            _selected.clear()
            logger.warning("[MT5] Connexion perdue — reconnexion différée")

        now = time.monotonic()
        if now < _init_next_retry_at:
            return False

        if mt5.initialize():
            _initialized = True
            _init_failures = 0
            _init_next_retry_at = 0.0
            _selected.clear()
            acc = mt5.account_info()
            logger.info("[MT5] Connecté — compte %s @ %s",
                        acc.login if acc else "?", acc.server if acc else "?")
            return True

        _init_failures += 1
        delay = min(
            _INIT_BACKOFF_BASE_SECONDS * (2 ** (_init_failures - 1)),
            _INIT_BACKOFF_MAX_SECONDS,
        )
        _init_next_retry_at = now + delay
        logger.warning(
            "[MT5] initialize() échoué: %s — nouvelle tentative dans %.1fs",
            mt5.last_error(),
            delay,
        )
        return False


def shutdown() -> None:
    global _initialized
    if MT5_AVAILABLE and _initialized:
        mt5.shutdown()
        _initialized = False


def get_rates_h1(symbol: str, n: int = 300) -> Optional[pd.DataFrame]:
    """n dernières barres H1 (index UTC, colonnes open/high/low/close)."""
    if not ensure_init():
        return None
    try:
        _ensure_symbol(symbol)
    except MT5SymbolError as exc:
        logger.warning("[MT5] %s", exc)
        return None
    with mt5_lock:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, n)
    if rates is None or len(rates) == 0:
        logger.warning("[MT5] copy_rates %s: %s", symbol, mt5.last_error())
        return None
    df = pd.DataFrame(rates)
    df.index = _server_epoch_to_utc(df["time"])
    return df[["open", "high", "low", "close"]].astype(float)


_TF = {}
def get_rates(symbol: str, tf: str = "H1", n: int = 300) -> Optional[pd.DataFrame]:
    """n dernières barres d'un timeframe arbitraire (H1/H4/M15/D1…).
    Index UTC, colonnes open/high/low/close. Sélectionne le symbole au besoin."""
    if not ensure_init():
        return None
    if not _TF:
        _TF.update({"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
                    "D1": mt5.TIMEFRAME_D1})
    try:
        _ensure_symbol(symbol)
    except MT5SymbolError as exc:
        logger.warning("[MT5] %s", exc)
        return None
    with mt5_lock:
        rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_H1), 0, n)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df.index = _server_epoch_to_utc(df["time"])
    return df[["open", "high", "low", "close"]].astype(float)


def get_ohlcv(symbol: str, tf: str = "M15", n: int = 120) -> Optional[pd.DataFrame]:
    """Comme get_rates mais CONSERVE le volume (colonne `v` = tick_volume).
    Utilisé par le segment émotion (volatilité + afflux de volume). Index UTC,
    colonnes open/high/low/close/v. Read-only, aucun ordre."""
    if not ensure_init():
        return None
    if not _TF:
        _TF.update({"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
                    "D1": mt5.TIMEFRAME_D1})
    try:
        _ensure_symbol(symbol)
    except MT5SymbolError as exc:
        logger.warning("[MT5] %s", exc)
        return None
    with mt5_lock:
        rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M15), 0, n)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df.index = _server_epoch_to_utc(df["time"])
    df = df.rename(columns={"tick_volume": "v"})
    cols = ["open", "high", "low", "close"] + (["v"] if "v" in df.columns else [])
    return df[cols].astype(float)


def get_tick(symbol: str) -> Optional[Dict[str, Any]]:
    """Dernier tick {bid, ask, mid, ts, stale}. stale=True si > 10 min (marché fermé)."""
    if not ensure_init():
        return None
    try:
        _ensure_symbol(symbol)
    except MT5SymbolError as exc:
        logger.warning("[MT5] %s", exc)
        return None
    with mt5_lock:
        t = mt5.symbol_info_tick(symbol)
    if t is None or t.bid <= 0:
        return None
    age = time.time() - t.time
    return {
        "bid": t.bid, "ask": t.ask, "mid": (t.bid + t.ask) / 2,
        "ts": datetime.fromtimestamp(t.time, tz=timezone.utc).isoformat(),
        "stale": age > 600,
    }


_selected: set = set()


def _ensure_symbol(symbol: str) -> None:
    """Sélectionne un symbole une seule fois sous le verrou MT5 partagé."""
    with mt5_lock:
        if symbol in _selected:
            return
        if not mt5.symbol_select(symbol, True):
            raise MT5SymbolError(
                f"symbol_select({symbol}) échoué: {mt5.last_error()}"
            )
        _selected.add(symbol)


def get_ticks_fast(symbols) -> Dict[str, Dict[str, Any]]:
    """Ticks temps réel multi-symboles pour le streaming dashboard.
    Retourne {sym: {bid, ask, mid, ts_msc, spread_bps}} avec le timestamp
    à la milliseconde (time_msc). Sélectionne les symboles à la volée."""
    if not ensure_init():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    with mt5_lock:
        ticks = {}
        for s in symbols:
            try:
                _ensure_symbol(s)
            except MT5SymbolError as exc:
                logger.warning("[MT5] %s", exc)
                continue
            ticks[s] = mt5.symbol_info_tick(s)
    for s, t in ticks.items():
        if not t or t.bid <= 0:
            continue
        mid = (t.bid + t.ask) / 2
        out[s] = {
            "bid": t.bid, "ask": t.ask, "mid": mid,
            "ts_msc": int(t.time_msc),
            "spread_bps": round((t.ask - t.bid) / mid * 10000, 2) if mid else 0.0,
        }
    return out


def account_snapshot() -> Dict[str, Any]:
    global _account_snapshot_cache, _account_snapshot_cache_at
    if not ensure_init():
        return {"connected": False, "available": MT5_AVAILABLE}
    now = time.monotonic()
    if (_account_snapshot_cache
            and now - _account_snapshot_cache_at < ACCOUNT_SNAPSHOT_CACHE_SECONDS):
        return dict(_account_snapshot_cache)
    if not mt5_lock.acquire(timeout=0.75):
        if _account_snapshot_cache:
            cached = dict(_account_snapshot_cache)
            cached["telemetry_stale"] = True
            cached["reason"] = "MT5_BUSY"
            return cached
        return {"connected": False, "available": MT5_AVAILABLE,
                "reason": "MT5_BUSY"}
    try:
        # Une seconde requête swing/forex peut avoir attendu la première.
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
                "reason": "MT5_ACCOUNT_UNAVAILABLE"}

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
