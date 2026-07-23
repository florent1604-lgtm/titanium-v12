"""core/closed_bars.py — Contrat CLÔTURE : ne jamais décider sur une bougie en formation.

P0 red-team Codex (17/07/2026) : les détecteurs (bougies, SMC, VPOC, OTE, S/R)
sont causaux SEULEMENT si le df ne contient que des bougies CLÔTURÉES. Or le
pipeline live ne le garantit pas (Binance REST renvoie la kline en formation, le
resample WS garde le bucket courant). Sans garde, une décision peut « repeindre »
intrabar.

`closed_only(df, timeframe, now)` = filtre FAIL-CLOSED appliqué AVANT tout
détecteur : retire la dernière bougie tant que sa période n'est pas révolue.
Invariant testé : changer la bougie ouverte ne change JAMAIS la sortie.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# Durée d'une bougie par timeframe (minutes).
_TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
           "H1": 60, "H2": 120, "H4": 240, "D1": 1440,
           "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def bar_duration_minutes(timeframe: str) -> Optional[int]:
    return _TF_MIN.get(str(timeframe))


def is_last_closed(index: pd.DatetimeIndex, timeframe: str,
                   now: Optional[datetime] = None) -> bool:
    """La dernière bougie de l'index est-elle clôturée ? (index = heure d'OUVERTURE
    UTC de chaque bougie, convention MT5/Binance)."""
    dur = bar_duration_minutes(timeframe)
    if dur is None or len(index) == 0:
        return False
    now = (now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    last_open = pd.Timestamp(index[-1])
    if last_open.tzinfo is None:
        last_open = last_open.tz_localize("UTC")
    close_time = last_open + pd.Timedelta(minutes=dur)
    return now >= close_time.to_pydatetime()


def closed_only(df: Optional[pd.DataFrame], timeframe: str,
                now: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Retourne df tronqué aux bougies CLÔTURÉES. FAIL-CLOSED : timeframe inconnu
    ou index non temporel ⇒ None (aucun détecteur ne doit tourner sur du non garanti)."""
    if df is None or len(df) == 0:
        return df
    if bar_duration_minutes(timeframe) is None:
        return None                       # TF inconnu : on refuse plutôt que deviner
    if not isinstance(df.index, pd.DatetimeIndex):
        return None                       # pas d'horodatage fiable : refus
    if is_last_closed(df.index, timeframe, now):
        return df
    return df.iloc[:-1] if len(df) > 1 else df.iloc[:0]


def assert_closed(df: Optional[pd.DataFrame], timeframe: str,
                  now: Optional[datetime] = None) -> pd.DataFrame:
    """Comme closed_only mais lève si rien n'est exploitable (usage strict)."""
    out = closed_only(df, timeframe, now)
    if out is None or len(out) == 0:
        raise ValueError(f"CLOSED_BARS_UNAVAILABLE: {timeframe}")
    return out


def validate_frame(df: Optional[pd.DataFrame], timeframe: str, *,
                   now: Optional[datetime] = None, max_stale_bars: float = 3.0,
                   min_len: int = 1) -> Tuple[bool, str]:
    """Contrôle de SANITÉ d'un df de bougies clôturées (red-team Codex : `data_valid`
    était sur-vendu). Renvoie (ok, code) — code stable pour la trace/dashboard.
    Vérifie : longueur, index temporel monotone & unique, OHLC présentes/finies/cohérentes,
    et FRAÎCHEUR (la dernière bougie n'est pas trop ancienne = flux gelé)."""
    if df is None or len(df) == 0:
        return False, "EMPTY"
    if len(df) < max(1, int(min_len)):
        return False, "TOO_SHORT"
    if not isinstance(df.index, pd.DatetimeIndex):
        return False, "NON_TEMPORAL_INDEX"
    if not df.index.is_monotonic_increasing:
        return False, "INDEX_NOT_MONOTONIC"
    if df.index.has_duplicates:
        return False, "INDEX_DUPLICATES"
    cols = ("open", "high", "low", "close")
    if any(c not in df.columns for c in cols):
        return False, "MISSING_OHLC"
    # Tous les détecteurs ne se limitent pas aux 200 dernières lignes (S/R lit le
    # frame entier, VPOC jusqu'à 300). Valider seulement tail(200) survendrait G0.
    sub = df[list(cols)]
    arr = np.asarray(sub.to_numpy(dtype="float64"))
    if not np.isfinite(arr).all():
        return False, "NON_FINITE_OHLC"
    o, h, l, c = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    if not (np.all(h >= l) and np.all(h >= o) and np.all(h >= c)
            and np.all(l <= o) and np.all(l <= c)):
        return False, "INCOHERENT_OHLC"
    dur = bar_duration_minutes(timeframe)
    if dur and now is not None:
        last_open = pd.Timestamp(df.index[-1])
        if last_open.tzinfo is None:
            last_open = last_open.tz_localize("UTC")
        nowt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age_min = (pd.Timestamp(nowt) - last_open).total_seconds() / 60.0
        if age_min > dur * (max_stale_bars + 1.0):
            return False, "STALE"
    return True, "OK"
