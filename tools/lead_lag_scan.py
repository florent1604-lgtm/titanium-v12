"""tools/lead_lag_scan.py — Scanner de CONCORDANCE / LEAD-LAG inter-actifs (EXPLORATOIRE).

Objectif (directive Florent) : identifier quel actif ANTICIPE le mouvement (ou le
changement de direction) d'un autre actif corrélé, pour une prise de position.

Méthode, par paire ORDONNÉE (leader L → follower F) :
  · rendements log alignés dans le temps (bougies clôturées, horloge UTC) ;
  · pour chaque décalage k>0 : corrélation de L[t] avec F[t+k] (L précède F de k barres) ;
  · hit-rate DIRECTIONNEL : P(signe(F[t+k]) == signe(L[t])) — prédit-il la direction ? ;
  · retournement : P(flip de signe de F en t+k | flip de signe de L en t) — prédit-il le
    CHANGEMENT de direction ? ;
  · meilleur k = argmax |corr|.

⚠️ EXPLORATOIRE — PRÉ-M2. Tester « toutes les combinaisons » crée un problème de
MULTIPLICITÉ (corrélations fallacieuses). Ces sorties sont des CANDIDATS, à valider par
le protocole M2 de Codex (collab/PLAN_CONFLUENCE_LEAD_LAG_M2.md : FDR/Holm, block
bootstrap, DSR/PBO, coûts) AVANT tout câblage décisionnel. Le garde pratique ici =
la PERSISTANCE à travers les fenêtres (un vrai lead/lag persiste ; le bruit non).
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

MIN_OBS = 60            # observations minimales pour une estimation (sinon ignoré)


def log_returns(close: pd.Series) -> pd.Series:
    """Rendements log d'une série de clôtures (index temporel conservé)."""
    c = pd.to_numeric(close, errors="coerce")
    r = np.log(c).diff()
    return r.replace([np.inf, -np.inf], np.nan).dropna()


def align_returns(series_by_symbol: Dict[str, pd.Series]) -> pd.DataFrame:
    """Aligne les rendements de plusieurs actifs sur l'index temporel COMMUN (inner join)."""
    valid = {s: r for s, r in series_by_symbol.items() if r is not None and len(r) > 0}
    if len(valid) < 2:
        return pd.DataFrame()
    return pd.concat(valid, axis=1).dropna()


def pair_lead_lag(rL: np.ndarray, rF: np.ndarray, max_lag: int,
                  min_obs: int = MIN_OBS) -> Optional[dict]:
    """Meilleur décalage k où L précède F. rL, rF déjà alignés (même horloge).
    Retourne {lag, corr, hit_rate, flip_rate, n} ou None si trop peu d'observations."""
    n0 = min(len(rL), len(rF))
    if n0 < min_obs + 1:
        return None
    rL = np.asarray(rL[:n0], float); rF = np.asarray(rF[:n0], float)
    best = None
    for k in range(1, max_lag + 1):
        a = rL[:-k]                      # L[t]
        b = rF[k:]                       # F[t+k]
        n = len(a)
        if n < min_obs or a.std() == 0 or b.std() == 0:
            continue
        corr = float(np.corrcoef(a, b)[0, 1])
        if not np.isfinite(corr):
            continue
        m = (a != 0) & (b != 0)
        hit = float(np.mean(np.sign(a[m]) == np.sign(b[m]))) if m.sum() >= min_obs else np.nan
        # retournement : changement de signe de L en t → changement de signe de F en t+k
        sL = np.sign(a); sF = np.sign(b)
        flipL = np.diff(sL) != 0
        flipF = np.diff(sF) != 0
        flip = float(np.mean(flipF[flipL])) if flipL.sum() >= min_obs // 2 else np.nan
        cand = {"lag": k, "corr": round(corr, 4),
                "hit_rate": round(hit, 4) if np.isfinite(hit) else None,
                "flip_rate": round(flip, 4) if np.isfinite(flip) else None, "n": int(n)}
        if best is None or abs(cand["corr"]) > abs(best["corr"]):
            best = cand
    return best


def scan_pairs(series_by_symbol: Dict[str, pd.Series], *, max_lag: int = 12,
               min_obs: int = MIN_OBS) -> List[dict]:
    """Toutes les paires ORDONNÉES (L≠F). Retourne les relations lead/lag, triées par
    |corrélation| décroissante. Chaque item : leader, follower, lag, corr, hit_rate, flip_rate, n."""
    aligned = align_returns(series_by_symbol)
    if aligned.empty or len(aligned) < min_obs + 1:
        return []
    cols = list(aligned.columns)
    out: List[dict] = []
    for L in cols:
        for F in cols:
            if L == F:
                continue
            res = pair_lead_lag(aligned[L].to_numpy(), aligned[F].to_numpy(),
                                max_lag, min_obs)
            if res is None:
                continue
            out.append({"leader": L, "follower": F, **res})
    out.sort(key=lambda d: -abs(d["corr"]))
    return out


class PersistenceTracker:
    """Persistance d'une relation lead/lag à travers les scans successifs (fenêtre glissante).
    Un vrai « stigmate de marché » PERSISTE ; une corrélation fallacieuse non."""

    def __init__(self, window: int = 20):
        self.window = window
        self._hist: Dict[tuple, "deque"] = defaultdict(lambda: deque(maxlen=window))

    def update(self, ranked: List[dict], *, top: int = 30) -> None:
        seen = set()
        for d in ranked[:top]:
            key = (d["leader"], d["follower"])
            seen.add(key)
            self._hist[key].append((d["lag"], d["corr"]))
        for key, dq in self._hist.items():        # absence = 0 ce tour
            if key not in seen:
                dq.append(None)

    def score(self, leader: str, follower: str) -> dict:
        dq = self._hist.get((leader, follower))
        if not dq:
            return {"seen": 0, "rate": 0.0, "lag_stable": None, "mean_corr": None}
        hits = [x for x in dq if x is not None]
        rate = len(hits) / len(dq)
        lags = [h[0] for h in hits]
        corrs = [h[1] for h in hits]
        lag_stable = (max(lags) - min(lags) <= 1) if lags else None   # lag ~constant = fiable
        return {"seen": len(hits), "rate": round(rate, 3),
                "lag_stable": lag_stable,
                "mean_corr": round(float(np.mean(corrs)), 4) if corrs else None}


def run_scan(symbols: List[str], fetch_fn: Callable[[str], Optional[pd.Series]], *,
             max_lag: int = 12, min_obs: int = MIN_OBS,
             tracker: Optional[PersistenceTracker] = None) -> dict:
    """Un passage complet : récupère les clôtures via fetch_fn(symbol) → rendements →
    scan de toutes les paires → (option) persistance. fetch_fn renvoie une Série de
    clôtures indexée temps (ou None). Retourne un rapport sérialisable."""
    series = {}
    for s in symbols:
        try:
            close = fetch_fn(s)
            r = log_returns(close) if close is not None else None
            if r is not None and len(r) > min_obs:
                series[s] = r
        except Exception:
            continue
    ranked = scan_pairs(series, max_lag=max_lag, min_obs=min_obs)
    if tracker is not None:
        tracker.update(ranked)
        for d in ranked:
            d["persistence"] = tracker.score(d["leader"], d["follower"])
    return {"n_assets": len(series), "assets": list(series.keys()),
            "n_pairs": len(ranked), "pairs": ranked}


def strong_candidates(report: dict, *, min_abs_corr: float = 0.25, min_hit: float = 0.55,
                      min_persist_rate: float = 0.6, min_seen: int = 5) -> List[dict]:
    """Candidats notables : corrélation + directionnel + PERSISTANCE. (Pré-M2 : ce sont
    des pistes à valider statistiquement par Codex, pas des signaux de trading.)"""
    out = []
    for d in report.get("pairs", []):
        p = d.get("persistence") or {}
        if (abs(d["corr"]) >= min_abs_corr
                and (d.get("hit_rate") or 0) >= min_hit
                and p.get("rate", 0) >= min_persist_rate
                and p.get("seen", 0) >= min_seen):
            out.append(d)
    return out
