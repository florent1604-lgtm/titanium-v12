"""emotion/market_context.py — Adaptateur DONNÉES RÉELLES → contexte émotion (v12, 14/07/2026).

Branche le segment ÉMOTION (`emotion_engine`) sur les vrais stores de marché de
Titanium SANS le coupler : `emotion_engine` reste pur/testable ; ici on lit les
sources vivantes (Binance WS delta-volume, Futures funding/long-short,
fondamentaux macro, bougies 30 s) et on assemble le dict `context`.

FIDÉLITÉ (règle Florent — latences broker/Binance non contrôlées) : la source la
plus rapide (delta-volume) porte son timestamp ; `source_age_s` = l'âge de la
donnée la plus vieille réellement utilisée → le moteur marque STALE et baisse la
confiance. Une donnée absente est OMISE (fail-safe), jamais inventée.

Séparation des responsabilités :
  · `live_raw(symbol)`      lit les stores vivants (couplage Titanium, isolé ici) ;
  · `assemble_context(raw)` pur → dict `context` (testable sans le bot) ;
  · `build_context` / `emotion_for` : la chaîne complète.

⚠️ Read-only. Aucun branchement dans une décision de trading sans protocole M2.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

_log = logging.getLogger(__name__)


def _clamp(x: float, lo: float, hi: float) -> float:
    if x != x:          # NaN propagé (jamais borné silencieusement à hi)
        return x
    return max(lo, min(hi, x))


def _finite(x: Any) -> Optional[float]:
    """float(x) si fini, sinon None (red-team Codex : un NaN/inf ou un non-numérique
    est une donnée ABSENTE, jamais une valeur extrême)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


@dataclass
class RawInputs:
    """Entrées brutes d'un actif, avant normalisation. Tout est Optional : une
    source absente reste None et sera simplement omise du contexte."""
    delta_pct: Optional[float] = None          # (buy-sell)/total ∈ [-1,1]
    delta_ts: Optional[float] = None           # epoch UTC de la mesure delta
    funding: Optional[float] = None            # taux de funding (crypto)
    long_short_ratio: Optional[float] = None   # positionnement foule (>0)
    macro_risk: Optional[float] = None         # score de risque macro 0..100
    candles: Any = None                        # pd.DataFrame OHLCV 30s (high/low/close/v)
    now: Optional[float] = None                # epoch de référence (injectable pour tests)


def _candle_features(df):
    """Bougies OHLCV → (atr_zscore, volume_surge, valence_momentum). Chacun None
    si pas assez d'historique (fail-safe). Aucune dépendance dure à pandas."""
    if df is None:
        return None, None, None
    try:
        n = len(df)
    except Exception:
        return None, None, None
    if n < 8:
        return None, None, None

    try:
        highs = [float(x) for x in df["high"].tolist()]
        lows = [float(x) for x in df["low"].tolist()]
        closes = [float(x) for x in df["close"].tolist()]
        vols = [float(x) for x in df["v"].tolist()]
    except Exception:
        return None, None, None

    win = min(50, n)
    rng = [h - l for h, l in zip(highs[-win:], lows[-win:])]

    # atr_zscore : la barre courante est-elle anormalement volatile vs son histoire ?
    atr_z = None
    if len(rng) >= 8:
        mean_r = sum(rng) / len(rng)
        var = sum((r - mean_r) ** 2 for r in rng) / len(rng)
        std = var ** 0.5
        if std > 1e-12:
            atr_z = (rng[-1] - mean_r) / std

    # volume_surge 0..1 : volume de la dernière barre vs sa moyenne récente.
    vol_s = None
    recent = vols[-win:]
    mean_v = sum(recent) / len(recent) if recent else 0.0
    if mean_v > 1e-12:
        ratio = vols[-1] / mean_v
        vol_s = _clamp((ratio - 1.0) / 2.0, 0.0, 1.0)   # ×1 →0, ×3 →1

    # valence_momentum : l'émotion monte/retombe ? proxy = rendement court terme.
    mom = None
    if n >= 7 and closes[-7] > 1e-12:
        ret = closes[-1] / closes[-7] - 1.0
        mom = _clamp(ret * 20.0, -1.0, 1.0)             # ±5% ⇒ ±1

    return atr_z, vol_s, mom


def assemble_context(raw: RawInputs, *, max_age_s: float = 30.0) -> dict:
    """RawInputs → dict `context` pour `compute_emotion`. PUR (aucun accès store).
    N'ajoute que les clés dont la donnée est présente ; calcule `source_age_s`
    depuis la source la plus rapide (delta-volume)."""
    ctx: dict = {}
    now = raw.now if raw.now is not None else time.time()
    ages = []

    # Toute valeur non finie (NaN/inf) ou non numérique est OMISE (source absente).
    dts = _finite(raw.delta_ts)
    if dts is not None:
        ages.append(max(0.0, now - dts))
    dv = _finite(raw.delta_pct)
    if dv is not None:
        ctx["delta_volume"] = _clamp(dv, -1.0, 1.0)
    fr = _finite(raw.funding)
    if fr is not None:
        ctx["funding_rate"] = fr
    ls = _finite(raw.long_short_ratio)
    if ls is not None and ls > 0:
        ctx["long_short_ratio"] = ls
    mr = _finite(raw.macro_risk)
    if mr is not None:
        ctx["macro_risk"] = mr

    atr_z, vol_s, mom = _candle_features(raw.candles)
    atr_z, vol_s, mom = _finite(atr_z), _finite(vol_s), _finite(mom)
    if atr_z is not None:
        ctx["atr_zscore"] = round(atr_z, 3)
    if vol_s is not None:
        ctx["volume_surge"] = round(vol_s, 3)
    if mom is not None:
        ctx["valence_momentum"] = round(mom, 3)

    if ages:
        ctx["source_age_s"] = round(max(ages), 1)
    ctx["max_age_s"] = max_age_s
    return ctx


def _candle_body_pressure(df, k: int = 5) -> Optional[float]:
    """Proxy de pression acheteur/vendeur pour MT5 (Axi ne diffuse pas le carnet
    L2, donc pas de vrai order-flow). Moyenne, sur les k dernières bougies, de
    (close-open)/(high-low) ∈ [-1,1] : clôtures près du haut = achat, du bas = vente."""
    try:
        opens = [float(x) for x in df["open"].tolist()]
        highs = [float(x) for x in df["high"].tolist()]
        lows = [float(x) for x in df["low"].tolist()]
        closes = [float(x) for x in df["close"].tolist()]
    except Exception:
        return None
    kk = min(k, len(closes))
    vals = []
    for i in range(-kk, 0):
        rng = highs[i] - lows[i]
        if rng > 1e-12:
            vals.append((closes[i] - opens[i]) / rng)
    if not vals:
        return None
    return _clamp(sum(vals) / len(vals), -1.0, 1.0)


def _is_crypto(symbol: str) -> bool:
    return "/" in symbol   # "BTC/USDT" (Binance) vs "US50"/"XAUUSD"/"EURUSD" (MT5)


def live_raw(symbol: str) -> RawInputs:
    """Stores VIVANTS crypto (Binance WS + Futures + macro). Fail-safe.
    À appeler DANS le process du bot (les stores sont en mémoire du process)."""
    raw = RawInputs(now=time.time())
    try:
        from data.binance_ws import delta_vol, candle_store
        d = delta_vol.get(symbol)
        if d:
            raw.delta_pct = d.get("delta_pct")
            raw.delta_ts = d.get("ts") or None
        raw.candles = candle_store.get(symbol)
    except Exception as exc:
        _log.warning("[EMOTION] delta/bougies Binance %s : %s", symbol, exc)
    try:
        from data.futures_data import futures_store
        f = futures_store.get(symbol)
        if f and f.get("ok"):
            raw.funding = f.get("funding")
            raw.long_short_ratio = f.get("long_short_ratio")
    except Exception as exc:
        _log.warning("[EMOTION] futures %s : %s", symbol, exc)
    try:
        from fundamentals.risk_scorer import get_current_score
        raw.macro_risk = get_current_score()
    except Exception as exc:
        _log.warning("[EMOTION] macro %s : %s", symbol, exc)
    return raw


def live_raw_mt5(symbol: str, *, tf: str = "M15", n: int = 120) -> RawInputs:
    """Stores VIVANTS MT5/Axi (là où passent les VRAIS trades démo/réel : indices,
    forex, métaux). Signaux plus grossiers que le crypto (pas de funding/long-short,
    pas d'order-flow L2) — la confiance du moteur baisse d'elle-même (fail-safe).
    Fraîcheur ancrée sur le dernier TICK (marché fermé → stale automatique)."""
    raw = RawInputs(now=time.time())
    try:
        from data.mt5_provider import get_ohlcv
        df = get_ohlcv(symbol, tf=tf, n=n)
        raw.candles = df
        if df is not None and len(df) >= 2:
            raw.delta_pct = _candle_body_pressure(df)
    except Exception as exc:
        _log.warning("[EMOTION] bougies MT5 %s : %s", symbol, exc)
    # Fraîcheur : get_tick renvoie `ts` en ISO-8601 (PAS un epoch) → parser, sinon
    # delta_ts resterait None et STALE ne se déclencherait JAMAIS sur MT5.
    try:
        from data.mt5_provider import get_tick
        tk = get_tick(symbol)
        if tk and tk.get("ts"):
            raw.delta_ts = datetime.fromisoformat(str(tk["ts"])).timestamp()
    except Exception as exc:
        _log.warning("[EMOTION] tick MT5 %s : %s", symbol, exc)
    try:
        from fundamentals.risk_scorer import get_current_score
        raw.macro_risk = get_current_score()
    except Exception as exc:
        _log.warning("[EMOTION] macro %s : %s", symbol, exc)
    return raw


def build_context(symbol: str, *, max_age_s: Optional[float] = None,
                  raw: Optional[RawInputs] = None) -> dict:
    """Contexte émotion d'un actif depuis les vraies données (ou `raw` injecté).
    Route automatiquement crypto Binance ('BTC/USDT') vs MT5 ('US50', 'XAUUSD')."""
    if raw is not None:
        return assemble_context(raw, max_age_s=max_age_s if max_age_s is not None else 30.0)
    if _is_crypto(symbol):
        return assemble_context(live_raw(symbol),
                                max_age_s=max_age_s if max_age_s is not None else 30.0)
    return assemble_context(live_raw_mt5(symbol),
                            max_age_s=max_age_s if max_age_s is not None else 60.0)


def emotion_for(symbol: str, *, max_age_s: Optional[float] = None,
                raw: Optional[RawInputs] = None):
    """Émotion de marché LIVE d'un actif (crypto OU MT5), read-only → EmotionState."""
    from emotion.emotion_engine import compute_emotion
    return compute_emotion(build_context(symbol, max_age_s=max_age_s, raw=raw))
