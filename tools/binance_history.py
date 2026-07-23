"""tools/binance_history.py — Historique de prix Binance SPOT (klines) pour la
calibration crypto sur le VRAI terrain (décision Florent 16/07/2026).

Pourquoi : le run crypto précédent tournait sur les CFD crypto d'Axi via MT5
(spreads LARGES, pas de carnet L2). La thèse « scalp = gagner peu et souvent »
mérite d'être testée sur Binance, où le spread est ~0 mais où le vrai coût est le
FRAIS (0,10 % taker / 0,075 % maker par côté). C'est ce coût qui décide.

Ce module ne fait QUE la donnée (rôle Claude). Il renvoie un DataFrame au MÊME
format que `data.mt5_provider.get_ohlcv` (index UTC, colonnes open/high/low/close/v)
pour que le pipeline de calibration de Codex le consomme comme source alternative,
sans réécrire la génération de signal ni les stats M2.

Gratuit, public, sans clé. Klines plafonnés à 1000/appel → on chunk en remontant.
Aucun ordre, lecture seule.
"""
from __future__ import annotations

import time
import urllib.request
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

BASE = "https://api.binance.com/api/v3/klines"
_TF_MS = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}   # minutes
_TF_BINANCE = {"M5": "5m", "M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d"}

# Frais Binance SPOT réels (barème de base ; le coût qui décide du scalp).
FEE_TAKER_BPS = 10.0    # 0,10 % par côté
FEE_MAKER_BPS = 7.5     # 0,075 % par côté (0 à négatif selon paliers/BNB)


def _fetch_chunk(symbol: str, interval: str, end_ms: int, limit: int = 1000) -> list:
    url = f"{BASE}?symbol={symbol}&interval={interval}&limit={limit}&endTime={end_ms}"
    for attempt in range(5):                       # robuste aux hoquets réseau/limites
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    return []


def get_klines(symbol: str, tf: str = "M15", years: float = 4.0,
               *, max_bars: int = 200_000) -> Optional[pd.DataFrame]:
    """N années de bougies Binance spot. Chunk en remontant, dédup sur le temps,
    tri croissant. Colonnes open/high/low/close/v (volume base), index UTC."""
    interval = _TF_BINANCE.get(tf)
    if interval is None:
        raise ValueError(f"timeframe non supporté: {tf}")
    horizon = datetime.now(timezone.utc) - timedelta(days=int(years * 365.25) + 5)
    horizon_ms = int(horizon.timestamp() * 1000)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows: list = []
    seen_first = None
    while len(rows) < max_bars:
        chunk = _fetch_chunk(symbol, interval, end_ms)
        if not chunk:
            break
        rows = chunk + rows                        # on préfixe (on remonte)
        first_open = chunk[0][0]
        if seen_first == first_open:               # plus rien de plus ancien
            break
        seen_first = first_open
        if first_open <= horizon_ms:
            break
        end_ms = first_open - 1                     # fenêtre suivante, juste avant

    if not rows:
        return None
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "v",
        "close_time", "qav", "trades", "tb_base", "tb_quote", "ignore"])
    df = df[["open_time", "open", "high", "low", "close", "v"]].copy()
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="first")].astype(float)
    return df.tail(max_bars)


def binance_cost_model(mode: str = "taker") -> dict:
    """Coûts Binance spot pour le CostModel du simulateur. Le spread réel ≈ 0-1 bps
    sur les majors ; le frais est le vrai coût. Round-trip = 2× le frais par côté."""
    fee = FEE_TAKER_BPS if mode == "taker" else FEE_MAKER_BPS
    return {"spread_bps": 1.0, "slippage_bps": 1.0, "commission_bps": fee,
            "note": f"binance spot {mode} - frais {fee} bps/cote, RT ~ {2*fee:.1f} bps"}


if __name__ == "__main__":     # smoke : profondeur réelle par symbole
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        df = get_klines(sym, "M15", years=4)
        if df is None:
            print(f"{sym}: aucune donnée")
            continue
        print(f"{sym} M15 : {len(df)} barres | {df.index[0].date()} -> {df.index[-1].date()} "
              f"| {(df.index[-1]-df.index[0]).days/365.25:.2f} ans")
    print("coûts:", binance_cost_model("taker"), "|", binance_cost_model("maker"))
