"""api/geometry_routes.py — Plan géométrique, LECTURE SEULE (étape 1b).

Expose le régime géométrique calculé À LA DEMANDE depuis les vraies bougies MT5.
Aucun effet de bord trading : on lit des prix, on calcule un régime, on le rend.
Le câblage décisionnel (consensus/gate/émotion/sizing) n'est PAS ici — il viendra
après validation M2.

⚠️ Le vecteur de features N'est PAS les 16 critères SMC (non historisés à ce jour) :
c'est un jeu de 8 descripteurs de structure de prix, documentés ci-dessous. Le
régime géométrique porte donc sur la STRUCTURE PRIX, pas encore sur le scoring SMC.
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException

from core.geometric_plane import GeometricPlane, geometric_plane, get_latest_regime

router = APIRouter(prefix="/geometry", tags=["geometry"])

_WINDOW = 60
_TF = "M15"


def _feature_matrix(df) -> tuple:
    """Construit (features (W,8), returns (W,1)) à partir des bougies.

    8 descripteurs par barre, tous sans look-ahead (bougies clôturées) :
      0 log-return          1 amplitude (H-L)/C      2 corps (C-O)/amplitude
      3 mèche haute /ampl.   4 mèche basse /ampl.     5 vol glissante 5 barres
      6 momentum 5 barres    7 vol glissante 20 barres
    """
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    n = len(c)
    eps = 1e-12

    logret = np.zeros(n)
    logret[1:] = np.log(np.clip(c[1:], eps, None) / np.clip(c[:-1], eps, None))
    ampl = (h - l) / np.clip(c, eps, None)
    span = np.clip(h - l, eps, None)
    body = (c - o) / span
    up_wick = (h - np.maximum(o, c)) / span
    lo_wick = (np.minimum(o, c) - l) / span

    def _roll_std(x, w):
        out = np.zeros(n)
        for i in range(n):
            j = max(0, i - w + 1)
            out[i] = float(np.std(x[j:i + 1])) if i > j else 0.0
        return out

    vol5 = _roll_std(logret, 5)
    vol20 = _roll_std(logret, 20)
    mom5 = np.zeros(n)
    mom5[5:] = np.log(np.clip(c[5:], eps, None) / np.clip(c[:-5], eps, None))

    feats = np.column_stack([logret, ampl, body, up_wick, lo_wick, vol5, mom5, vol20])
    feats = feats[-_WINDOW:]
    returns = logret[-_WINDOW:].reshape(-1, 1)
    return feats, returns


def _compute_regime(symbol: str):
    """Calcule (et met en cache) le régime d'un symbole depuis MT5. None si indispo."""
    from data.mt5_provider import get_ohlcv
    df = get_ohlcv(symbol, _TF, _WINDOW + 30)
    if df is None or len(df) < 40:
        return None
    feats, returns = _feature_matrix(df)
    try:
        from core.signal_engine import get_spectral_state
        spec = (get_spectral_state() or {}).get(symbol, {})
        spectral_cycle = int(spec.get("dominant_cycle", 0) or 0)
    except Exception:
        spectral_cycle = 0
    return geometric_plane.analyze(
        symbol=symbol, scores_16=feats, returns=returns,
        spectral_cycle=spectral_cycle, publish=True,
    )


def _serialize(regime) -> dict:
    return {
        "symbol": regime.symbol,
        "branch": regime.branch,
        "timestamp": regime.timestamp,
        "clifford": {
            "x": regime.clifford_xyz[0], "y": regime.clifford_xyz[1],
            "z": regime.clifford_xyz[2], "curvature": regime.curvature,
        },
        "indicators": {
            "fisher_distance": regime.fisher_distance,
            "lyapunov_horizon": regime.lyapunov_horizon,
            "topology_alert": regime.topology_alert,
            "grassmann_rotation": regime.grassmann_rotation,
            "spectral_cycle": regime.spectral_cycle,
            "poincare_radius": regime.poincare_radius,
            "confidence": regime.confidence,
        },
        "sizing_factor_propose": GeometricPlane.sizing_factor(regime),  # PROPOSÉ, non appliqué
        "note": "observateur — proxys heuristiques, aucun effet sur la décision",
    }


@router.get("/state/{symbol:path}")
async def geometry_state(symbol: str):
    """Régime géométrique d'un symbole, calculé à la demande depuis MT5 (lecture seule)."""
    import asyncio
    regime = await asyncio.to_thread(_compute_regime, symbol)
    if regime is None:
        raise HTTPException(status_code=404, detail=f"Pas de données MT5 pour {symbol}")
    return _serialize(regime)


@router.get("/all")
async def geometry_all():
    """Dernier régime connu pour tous les symboles du panier confluence (cache lecture seule)."""
    import asyncio
    from utils.config import CONFLUENCE_DEMO_SYMBOLS, CONFLUENCE_CRYPTO_SYMBOLS
    syms = list(CONFLUENCE_DEMO_SYMBOLS) + list(CONFLUENCE_CRYPTO_SYMBOLS)

    async def _one(s):
        try:
            r = await asyncio.to_thread(_compute_regime, s)
            return s, (_serialize(r) if r else None)
        except Exception:
            return s, None

    results = await asyncio.gather(*(_one(s) for s in syms))
    return {s: r for s, r in results if r is not None}
