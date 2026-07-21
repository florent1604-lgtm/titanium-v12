"""core/instruments.py — Référentiel d'instruments UNIFIÉ (axe G de l'audit archi).

Source de vérité unique pour : le ticker d'exécution (MT5/Axi), la venue (crypto/cfd),
la paire Binance de RÉFÉRENCE (crypto), et la classe d'actif. Remplace les mappings
ad hoc éparpillés (binance_ohlcv, consensus_engine…) qui causaient des incohérences
inter-moteurs (BTCUSD ↔ BTC/USDT). PUR, sans réseau, fail-safe.

⚠️ PRÉ-M2 / structurel : ce module ne décide RIEN. Il normalise les identifiants pour que
les moteurs (confluence, scoring, consensus, lead/lag) parlent le même langage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Instrument:
    symbol: str                 # ticker canonique d'EXÉCUTION (MT5/Axi) — ex "BTCUSD", "EURUSD"
    venue: str                  # "crypto" | "cfd"
    kind: str                   # "crypto" | "forex" | "index" | "metal"
    binance: Optional[str] = None   # paire Binance de référence (crypto) — ex "BTC/USDT"


def _mk(symbol, venue, kind, binance=None) -> Instrument:
    return Instrument(symbol=symbol, venue=venue, kind=kind, binance=binance)


# Univers connu (crypto Axi + CFD Axi validés). Étendre ICI, pas ailleurs.
_ALL: List[Instrument] = [
    # ── Crypto (Axi MT5, LIVE 24/7) → référence Binance ──
    _mk("BTCUSD", "crypto", "crypto", "BTC/USDT"),
    _mk("ETHUSD", "crypto", "crypto", "ETH/USDT"),
    _mk("XRPUSD", "crypto", "crypto", "XRP/USDT"),
    _mk("LTCUSD", "crypto", "crypto", "LTC/USDT"),
    _mk("BCHUSD", "crypto", "crypto", "BCH/USDT"),
    _mk("ADAUSD", "crypto", "crypto", "ADA/USDT"),
    _mk("SOLUSD", "crypto", "crypto", "SOL/USDT"),
    _mk("DOGEUSD", "crypto", "crypto", "DOGE/USDT"),
    _mk("BNBUSD", "crypto", "crypto", "BNB/USDT"),
    # ── Métaux ──
    _mk("XAUUSD", "cfd", "metal"),
    _mk("XAGUSD", "cfd", "metal"),
    # ── Forex ──
    _mk("EURUSD", "cfd", "forex"), _mk("GBPUSD", "cfd", "forex"),
    _mk("USDJPY", "cfd", "forex"), _mk("AUDUSD", "cfd", "forex"),
    _mk("USDCAD", "cfd", "forex"), _mk("NZDUSD", "cfd", "forex"),
    _mk("EURJPY", "cfd", "forex"), _mk("GBPJPY", "cfd", "forex"),
    _mk("EURGBP", "cfd", "forex"),
    # ── Indices ──
    _mk("US500", "cfd", "index"), _mk("US30", "cfd", "index"),
    _mk("US2000", "cfd", "index"), _mk("NAS100.fs", "cfd", "index"),
    _mk("USTECH", "cfd", "index"), _mk("HSI.fs", "cfd", "index"),
    _mk("GER40", "cfd", "index"), _mk("UK100", "cfd", "index"),
    _mk("FRA40", "cfd", "index"), _mk("AUS200", "cfd", "index"),
]

_BY_SYMBOL: Dict[str, Instrument] = {i.symbol.upper(): i for i in _ALL}
_BY_BINANCE: Dict[str, Instrument] = {i.binance.upper(): i for i in _ALL if i.binance}


def get(symbol: str) -> Optional[Instrument]:
    """Instrument par ticker d'exécution (insensible à la casse). None si inconnu."""
    return _BY_SYMBOL.get(str(symbol).upper())


def from_binance(pair: str) -> Optional[Instrument]:
    """Instrument depuis une paire Binance (ex 'BTC/USDT' → BTCUSD)."""
    return _BY_BINANCE.get(str(pair).upper())


def binance_ref(symbol: str) -> Optional[str]:
    """Paire Binance de référence pour un ticker d'exécution (crypto). None sinon."""
    inst = get(symbol)
    return inst.binance if inst else None


def venue_of(symbol: str, default: str = "cfd") -> str:
    """Venue ('crypto'|'cfd') d'un ticker. `default` si inconnu (fail-safe)."""
    inst = get(symbol)
    return inst.venue if inst else default


def symbols(venue: Optional[str] = None, kind: Optional[str] = None) -> List[str]:
    """Liste des tickers, filtrable par venue et/ou classe d'actif."""
    return [i.symbol for i in _ALL
            if (venue is None or i.venue == venue) and (kind is None or i.kind == kind)]


def is_known(symbol: str) -> bool:
    return str(symbol).upper() in _BY_SYMBOL
