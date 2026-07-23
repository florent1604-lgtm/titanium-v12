"""core/geometric_plane.py — Plan géométrique transverse (OBSERVATEUR, lecture seule).

Quantifie la STRUCTURE / le RÉGIME du marché au même niveau d'abstraction que
l'émotion. Il n'entre PAS dans la décision à ce stade : il observe, il mesure, il
expose. Les décideurs (consensus, brain_gate, émotion, sizing) ne le consomment
PAS encore — ce câblage viendra APRÈS validation M2, un modulateur à la fois.

⚠️ HONNÊTETÉ DES NOMS (revue Claude 23/07/2026). Les libellés « Fisher-Rao »,
« topologie persistante », « Lyapunov » désignent ici des PROXYS heuristiques,
pas les objets mathématiques exacts :
  · `fisher_distance`  = distance euclidienne au régime historique le plus proche ;
  · `_topology_score`  = variance PCA × autocorrélation (proxy de circularité) ;
  · `_lyapunov_horizon`= divergence log moyenne (Wolf simplifié).
C'est un RÉGIME DÉTECTOR utile — mais on ne se ment pas sur ce qu'il calcule.

⚠️ EVENT PLANE DIFFÉRÉ (Étape 2). Le registre de faits est GELÉ / CLOSED_EXACT
(artefact de Codex). Publier un fact `GEOMETRIC_REGIME` exige que Codex étende le
registre. En attendant, le dernier régime par symbole est gardé en MÉMOIRE ici et
lu par `get_latest_regime()` — zéro écriture EventPlane, zéro effet de bord.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
from numpy.typing import NDArray

try:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
except ImportError:  # pragma: no cover
    PCA = None
    StandardScaler = None


# ── Cache mémoire du dernier régime (remplace l'EventPlane tant qu'il est gelé) ──
_LATEST: Dict[str, "GeometricRegime"] = {}


# ─────────────────────────────────────────────────────────────────────────────
# 1.  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class GeometricRegime:
    """Fait immuable — régime géométrique projeté pour un symbole."""
    symbol: str
    timestamp: float
    branch: Literal["CLIFFORD", "GRASSMANN", "CLASSIC"]
    curvature: float = 0.0
    fisher_distance: float = 0.0
    lyapunov_horizon: int = 30
    topology_alert: bool = False
    clifford_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    grassmann_rotation: float = 0.0
    spectral_cycle: int = 0
    poincare_radius: float = 0.0
    confidence: float = 0.0

    def to_fact_payload(self) -> Dict[str, Any]:
        """Sérialisation JSON-safe (pour la route API / le futur fact EventPlane)."""
        return asdict(self)


@dataclass
class RegimeLibraryEntry:
    """Entrée de la bibliothèque de régimes historiques (pour le proxy Fisher)."""
    mean: NDArray[np.float64]
    branch: str
    timestamp: float
    curvature: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2.  MOTEUR
# ─────────────────────────────────────────────────────────────────────────────

class GeometricPlane:
    """Moteur de régime géométrique. PUR : `analyze()` n'a d'autre effet que de
    mettre à jour le cache mémoire (`get_latest_regime`). Aucune décision, aucun
    ordre, aucune écriture EventPlane."""

    def __init__(
        self,
        window: int = 60,
        library_size: int = 50,
        fisher_threshold_warn: float = 5.0,
        fisher_threshold_block: float = 8.0,
        lyapunov_scalp_threshold: int = 3,
        lyapunov_swing_threshold: int = 5,
    ):
        self.window = window
        self.library_size = library_size
        self.fisher_warn = fisher_threshold_warn
        self.fisher_block = fisher_threshold_block
        self.lyap_scalp = lyapunov_scalp_threshold
        self.lyap_swing = lyapunov_swing_threshold

        self._pca = PCA(n_components=2) if PCA else None
        self._scaler = StandardScaler() if StandardScaler else None
        self._library: Dict[str, deque] = {}
        self._last_eigvecs: Dict[str, Optional[NDArray[np.float64]]] = {}

    # ── API publique ─────────────────────────────────────────────────────────

    def analyze(
        self,
        symbol: str,
        scores_16: NDArray[np.float64],
        returns: NDArray[np.float64],
        spectral_cycle: int = 0,
        spectral_override: Optional[Dict[str, Any]] = None,
        publish: bool = True,
    ) -> GeometricRegime:
        """Topologie → branche (tore/Grassmann/classique) → Fisher → Lyapunov → confiance.

        `spectral_override` (pont spectral, optionnel) : quand `use_spectral=True`, le tore
        prend directement les angles du cycle Ehlers au lieu de la PCA sur les scores.
        """
        now = time.time()
        scores_16 = np.asarray(scores_16, dtype=np.float64)
        returns = np.asarray(returns, dtype=np.float64)

        topo_score = self._topology_score(scores_16)
        confidence_boost = 0.0

        if spectral_override and spectral_override.get("use_spectral"):
            branch = "CLIFFORD"                       # le cycle spectral fournit le tore
            clifford_xyz = spectral_override["clifford_xyz"]
            curvature = float(spectral_override["curvature"])
            grassmann_rot = 0.0
            confidence_boost = float(spectral_override.get("confidence", 0.5))
        elif topo_score > 0.60 and spectral_cycle > 5:
            branch = "CLIFFORD"
            clifford_xyz, curvature = self._compute_clifford(scores_16)
            grassmann_rot = 0.0
        elif topo_score > 0.25:
            branch = "GRASSMANN"
            clifford_xyz = (0.0, 0.0, 0.0)
            grassmann_rot = self._compute_grassmann(symbol, scores_16)
            curvature = 0.5
        else:
            branch = "CLASSIC"
            clifford_xyz = (0.0, 0.0, 0.0)
            grassmann_rot = 0.0
            curvature = 0.0

        fisher = self._fisher_distance(symbol, scores_16)
        horizon = self._lyapunov_horizon(returns)
        poincare_r = self._poincare_radius(scores_16)
        confidence = self._compute_confidence(topo_score, fisher, horizon, spectral_cycle)
        if confidence_boost:
            confidence = min(1.0, confidence + confidence_boost * 0.3)
        topology_alert = topo_score < 0.15

        regime = GeometricRegime(
            symbol=symbol,
            timestamp=now,
            branch=branch,
            curvature=round(float(curvature), 4),
            fisher_distance=round(float(fisher), 4),
            lyapunov_horizon=int(horizon),
            topology_alert=bool(topology_alert),
            clifford_xyz=tuple(round(float(v), 6) for v in clifford_xyz),
            grassmann_rotation=round(float(grassmann_rot), 2),
            spectral_cycle=int(spectral_cycle),
            poincare_radius=round(float(poincare_r), 4),
            confidence=round(float(confidence), 4),
        )

        self._store_regime(symbol, regime, scores_16)
        if publish:
            _LATEST[symbol] = regime          # cache mémoire (pas d'EventPlane à ce stade)
        return regime

    def analyze_with_spectral(
        self,
        symbol: str,
        scores_16: NDArray[np.float64],
        returns: NDArray[np.float64],
        spectral_state: Dict[str, Any],
        publish: bool = True,
    ) -> GeometricRegime:
        """Comme `analyze()`, mais auto-détecte le pont spectral depuis `spectral_state`.

        Si le pont est indisponible ou le cycle invalide, retombe proprement sur la PCA.
        """
        spectral_override = None
        try:
            from core.spectral_bridge import integrate_with_geometric_plane
            spectral_override = integrate_with_geometric_plane(self, spectral_state, symbol)
        except Exception:
            spectral_override = None
        spectral_cycle = int((spectral_state.get(symbol, {}) or {}).get("dominant_cycle", 0) or 0)
        return self.analyze(symbol=symbol, scores_16=scores_16, returns=returns,
                            spectral_cycle=spectral_cycle, spectral_override=spectral_override,
                            publish=publish)

    # ── Modulateurs statiques (NON câblés — prêts pour l'étape 3, post-M2) ────

    @staticmethod
    def sizing_factor(regime: GeometricRegime) -> float:
        """Facteur de sizing ∈ [0.30, 1.20] dérivé du régime. (Non câblé.)"""
        factor = 1.0
        if regime.branch == "CLIFFORD":
            factor *= (1.0 - 0.15 * regime.curvature)
        elif regime.branch == "GRASSMANN":
            factor *= (1.0 - 0.25 * min(regime.grassmann_rotation / 45.0, 1.0))
        if regime.fisher_distance > 8.0:
            factor *= 0.25
        elif regime.fisher_distance > 5.0:
            factor *= 0.50
        if regime.lyapunov_horizon < 3:
            factor *= 0.50
        elif regime.lyapunov_horizon < 5:
            factor *= 0.75
        if regime.topology_alert:
            factor *= 0.30
        return float(np.clip(factor, 0.30, 1.20))

    @staticmethod
    def emotion_arousal_modifier(regime: GeometricRegime, base_arousal: float) -> float:
        """Module l'arousal du circumplex par la courbure / l'incertitude. (Non câblé.)"""
        arousal = base_arousal
        if regime.branch == "CLIFFORD":
            arousal *= (1.0 + 0.50 * regime.curvature)
        if regime.lyapunov_horizon < 5:
            arousal *= 1.30
        if regime.fisher_distance > 5.0:
            arousal *= 0.40
        return float(np.clip(arousal, 0.0, 1.0))

    @staticmethod
    def consensus_modulator(regime: GeometricRegime, base_score: float) -> float:
        """Module le consensus_score ∈ [-100,100]. (Non câblé.)"""
        factor = 1.0
        if regime.branch == "CLIFFORD":
            factor *= (1.0 - 0.30 * regime.curvature)
        elif regime.branch == "GRASSMANN":
            factor *= (1.0 - 0.40 * min(regime.grassmann_rotation / 45.0, 1.0))
        if regime.fisher_distance > 5.0:
            factor *= 0.30
        if regime.topology_alert:
            factor = 0.0
        return base_score * factor

    @staticmethod
    def gate_permitted(regime: GeometricRegime, trade_horizon: str) -> Tuple[bool, str]:
        """Filtre proposé pour brain_gate (retourne (permitted, reason)). (Non câblé.)"""
        if regime.topology_alert:
            return False, "GEOM_TOPOLOGY_ALERT"
        if regime.branch == "GRASSMANN" and regime.grassmann_rotation > 30.0:
            return False, "GEOM_GRASSMANN_ROTATION_TOO_FAST"
        if trade_horizon != "scalp" and regime.lyapunov_horizon < 2:
            return False, "GEOM_LYAPUNOV_TOO_SHORT_FOR_SWING"
        if regime.fisher_distance > 8.0 and trade_horizon != "scalp":
            return False, "GEOM_FISHER_UNKNOWN_REGIME"
        return True, "GEOM_OK"

    # ── Implémentation interne ────────────────────────────────────────────────

    def _topology_score(self, data: NDArray[np.float64]) -> float:
        """Proxy de circularité : variance PCA expliquée × autocorrélation lag-1."""
        if data.shape[0] < 20 or self._pca is None:
            return 0.5
        if float(np.var(data)) < 1e-12:          # entrée plate → AUCUNE structure → CLASSIC
            return 0.0
        scaled = self._scaler.fit_transform(data)
        proj = self._pca.fit_transform(scaled)
        if proj.shape[0] < 2:
            return 0.5
        var_ratio = float(self._pca.explained_variance_ratio_.sum())
        col = proj[:, 0]
        if np.std(col[:-1]) < 1e-12 or np.std(col[1:]) < 1e-12:
            circularity = 0.0
        else:
            circularity = abs(float(np.corrcoef(col[:-1], col[1:])[0, 1]))
        score = var_ratio * circularity
        return float(np.clip(score * 2.5, 0.0, 1.0))

    def _compute_clifford(
        self, data: NDArray[np.float64]
    ) -> Tuple[Tuple[float, float, float], float]:
        """Projection stéréographique d'un tore de Clifford → ((x,y,z), courbure)."""
        scaled = self._scaler.fit_transform(data)
        proj = self._pca.fit_transform(scaled)
        u = math.atan2(float(proj[-1, 1]), float(proj[-1, 0]))
        v = u + math.pi / 4.0
        t = 1.0
        W = 2.0 - (math.sin(u) * math.sin(t) + math.sin(v) * math.cos(t))
        W = max(W, 0.15)
        x = math.cos(u) / W
        y = (math.sin(u) * math.cos(t) - math.sin(v) * math.sin(t)) / W
        z = math.cos(v) / W
        curvature = min(1.0, abs(1.0 / W))
        return (x, y, z), curvature

    def _compute_grassmann(self, symbol: str, data: NDArray[np.float64]) -> float:
        """Vitesse de rotation (deg) du sous-espace dominant de rang 2."""
        cov = np.cov(data.T)
        _, eigvecs = np.linalg.eigh(cov)
        subspace = eigvecs[:, -2:]
        last = self._last_eigvecs.get(symbol)
        if last is not None and last.shape == subspace.shape:
            rot = float(np.linalg.norm(subspace - last, ord="fro"))
            deg = min(180.0, rot * 180.0 / math.pi)
        else:
            deg = 0.0
        self._last_eigvecs[symbol] = subspace.copy()
        return float(deg)

    def _fisher_distance(self, symbol: str, current: NDArray[np.float64]) -> float:
        """PROXY : distance euclidienne au régime historique le plus proche."""
        lib = self._library.get(symbol)
        if not lib:
            return 0.0
        current_mean = current.mean(axis=0)
        distances = [float(np.linalg.norm(current_mean - e.mean)) for e in lib]
        return float(min(distances)) if distances else 0.0

    def _lyapunov_horizon(self, returns: NDArray[np.float64]) -> int:
        """PROXY (Wolf simplifié) : horizon de prédictibilité en « jours » ∈ [1,60]."""
        if returns.shape[0] < 30:
            return 30
        series = returns[:, 0] if returns.ndim > 1 else returns
        series = np.asarray(series, dtype=np.float64).flatten()
        divergences: List[float] = []
        n = len(series)
        for i in range(10, n - 10):
            for j in range(i + 5, min(i + 15, n - 5)):
                d0 = abs(float(series[i]) - float(series[j]))
                if d0 > 1e-12:
                    d1 = abs(float(series[i + 5]) - float(series[j + 5]))
                    if d1 > 0:
                        divergences.append(math.log(d1 / d0))
        if not divergences:
            return 30
        lyap = float(np.mean(divergences))
        if lyap <= 0:
            return 60
        horizon = int(math.log(2.0) / lyap)
        return max(1, min(horizon, 60))

    def _poincare_radius(self, data: NDArray[np.float64]) -> float:
        """Proxy : variance moyenne normalisée (0 = central/stable, 1 = exotique)."""
        variances = np.var(data, axis=0)
        mean_var = float(np.mean(variances))
        return float(np.clip(mean_var / 0.10, 0.0, 0.99))

    def _compute_confidence(
        self, topo_score: float, fisher: float, horizon: int, spectral_cycle: int
    ) -> float:
        c = 0.5
        c += 0.2 * topo_score
        c -= 0.1 * min(fisher / 10.0, 1.0)
        c += 0.1 * min(horizon / 30.0, 1.0)
        c += 0.1 * (1.0 if spectral_cycle > 0 else 0.0)
        return float(np.clip(c, 0.0, 1.0))

    def _store_regime(
        self, symbol: str, regime: GeometricRegime, scores: NDArray[np.float64]
    ) -> None:
        if symbol not in self._library:
            self._library[symbol] = deque(maxlen=self.library_size)
        self._library[symbol].append(
            RegimeLibraryEntry(
                mean=scores.mean(axis=0).copy(),
                branch=regime.branch,
                timestamp=regime.timestamp,
                curvature=regime.curvature,
            )
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3.  SINGLETON + ACCÈS LECTURE SEULE
# ─────────────────────────────────────────────────────────────────────────────

geometric_plane = GeometricPlane()


def get_latest_regime(symbol: str) -> Optional[GeometricRegime]:
    """Dernier régime calculé pour un symbole (cache mémoire, lecture seule)."""
    return _LATEST.get(symbol)


def all_latest_regimes() -> Dict[str, GeometricRegime]:
    """Copie du cache complet (pour la route /geometry/all)."""
    return dict(_LATEST)


def price_features(o, h, l, c, window: int = 60):
    """(open,high,low,close) → (features (W,8), returns (W,1)), sans look-ahead.

    8 descripteurs de STRUCTURE PRIX par barre — partagés par la route observateur
    et le chemin de décision pour que le régime câblé soit calculé de façon IDENTIQUE :
      0 log-return   1 amplitude (H-L)/C   2 corps (C-O)/ampl.   3 mèche haute
      4 mèche basse  5 vol. glissante 5    6 momentum 5          7 vol. glissante 20
    """
    o = np.asarray(o, dtype=float); h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float); c = np.asarray(c, dtype=float)
    n = len(c); eps = 1e-12
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

    vol5 = _roll_std(logret, 5); vol20 = _roll_std(logret, 20)
    mom5 = np.zeros(n)
    mom5[5:] = np.log(np.clip(c[5:], eps, None) / np.clip(c[:-5], eps, None))
    feats = np.column_stack([logret, ampl, body, up_wick, lo_wick, vol5, mom5, vol20])
    return feats[-window:], logret[-window:].reshape(-1, 1)
