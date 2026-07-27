"""data/binance_ohlcv.py — OHLCV Binance SYNCHRONE (léger) pour le moteur de confluence.

Le crypto est le seul marché ouvert le week-end : la confluence doit y tourner 24/7.
Le moteur (`confluence_demo_engine.run_once`) appelle `rates_fn(symbol, tf, n)` dans un
thread → il lui faut une fonction SYNCHRONE. `fetch_klines` (data/binance_rest) est async ;
ici on fait un fetch REST direct (stdlib urllib, aucune dépendance), qui renvoie un df
index UTC (heure d'OUVERTURE) + open/high/low/close/v — exactement ce qu'attend
`closed_bars` (la dernière ligne = bougie en formation, retirée en amont).
"""
from __future__ import annotations

import json
import math
import urllib.request
from typing import Optional

import pandas as pd

# TF Titanium → intervalle Binance
_INTERVALS = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
              "H1": "1h", "H2": "2h", "H4": "4h", "D1": "1d",
              "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
              "1h": "1h", "4h": "4h", "1d": "1d"}

_BASES = ("https://api.binance.com", "https://data-api.binance.vision")

def mt5_to_binance(mt5_symbol: str) -> Optional[str]:
    """Ticker crypto MT5 (Axi) → paire Binance de référence. Délègue au référentiel
    d'instruments unifié (axe G : source de vérité unique)."""
    from core.instruments import binance_ref
    return binance_ref(mt5_symbol)


def reference_close(mt5_symbol: str) -> Optional[float]:
    """Dernier prix Binance de référence pour un ticker crypto MT5. None si non mappé
    ou réseau indisponible. Fail-safe (l'ajustement est un bonus, jamais bloquant)."""
    bnc = mt5_to_binance(mt5_symbol)
    if not bnc:
        return None
    df = get_ohlcv(bnc, "M1", 2, min_bars=1)
    if df is None or df.empty:
        return None
    try:
        price = float(df["close"].iloc[-1])
        return price if math.isfinite(price) and price > 0 else None
    except (TypeError, ValueError, IndexError):
        return None


def parse_klines(raw: list) -> Optional[pd.DataFrame]:
    """Transforme la réponse REST /klines en df OHLCV (PUR, testable sans réseau).
    Format Binance : [openTime, o, h, l, c, v, closeTime, ...]."""
    if not isinstance(raw, list) or not raw:
        return None
    try:
        idx = pd.to_datetime([int(k[0]) for k in raw], unit="ms", utc=True)
        df = pd.DataFrame({
            "open": [float(k[1]) for k in raw], "high": [float(k[2]) for k in raw],
            "low": [float(k[3]) for k in raw], "close": [float(k[4]) for k in raw],
            "v": [float(k[5]) for k in raw],
        }, index=idx)
    except (TypeError, ValueError, IndexError):
        return None
    return df


def get_ohlcv(symbol: str, tf: str = "M15", n: int = 300,
              min_bars: int = 20) -> Optional[pd.DataFrame]:
    """n dernières bougies Binance pour `symbol` (ex 'BTC/USDT'). SYNCHRONE, fail-safe :
    renvoie None si indisponible ou moins de `min_bars` bougies. Pour la confluence,
    min_bars=20 ; pour un simple prix de référence, min_bars=1."""
    interval = _INTERVALS.get(tf, tf)
    sym = symbol.replace("/", "").upper()
    q = f"?symbol={sym}&interval={interval}&limit={int(n)}"
    for base in _BASES:
        try:
            req = urllib.request.Request(f"{base}/api/v3/klines{q}",
                                         headers={"User-Agent": "titanium-confluence"})
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = json.loads(r.read().decode("utf-8"))
            df = parse_klines(raw)
            if df is not None and len(df) >= max(1, min_bars):
                return df
        except Exception:
            continue
    return None
