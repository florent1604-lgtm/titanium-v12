"""Scanner lead/lag : détecte un leader connu, classe correctement, mesure la persistance.
Données synthétiques → aucune dépendance réseau/MT5."""
import numpy as np
import pandas as pd

from tools import lead_lag_scan as ll


def _idx(n, start="2026-07-01"):
    return pd.date_range(start, periods=n, freq="15min", tz="UTC")


def test_pair_detecte_le_lead_connu():
    rng = np.random.default_rng(0)
    n, k = 500, 3
    a = rng.normal(0, 1, n)
    b = np.zeros(n)
    b[k:] = a[:-k] + rng.normal(0, 0.1, n - k)      # B reproduit A avec k barres de retard
    res = ll.pair_lead_lag(a, b, max_lag=8)
    assert res["lag"] == k and res["corr"] > 0.8 and res["hit_rate"] > 0.8


def test_scan_pairs_identifie_le_leader():
    rng = np.random.default_rng(1)
    n, k = 600, 2
    idx = _idx(n)
    a = rng.normal(0, 1, n)
    b = np.concatenate([np.zeros(k), a[:-k]]) + rng.normal(0, 0.05, n)
    series = {"A": pd.Series(a, index=idx), "B": pd.Series(b, index=idx)}
    ranked = ll.scan_pairs(series, max_lag=6)
    top = ranked[0]
    assert top["leader"] == "A" and top["follower"] == "B" and top["lag"] == k


def test_run_scan_via_fetch_closes():
    rng = np.random.default_rng(2)
    n, k = 700, 2
    idx = _idx(n)
    ra = rng.normal(0, 0.01, n)
    rb = np.concatenate([np.zeros(k), ra[:-k]]) + rng.normal(0, 0.001, n)
    closes = {"A": pd.Series(100 * np.exp(np.cumsum(ra)), index=idx),
              "B": pd.Series(50 * np.exp(np.cumsum(rb)), index=idx)}
    rep = ll.run_scan(["A", "B"], lambda s: closes.get(s), max_lag=6)
    assert rep["n_assets"] == 2 and rep["pairs"]
    assert rep["pairs"][0]["leader"] == "A" and rep["pairs"][0]["follower"] == "B"


def test_persistance_monte_avec_les_apparitions():
    tr = ll.PersistenceTracker(window=10)
    strong = [{"leader": "A", "follower": "B", "lag": 2, "corr": 0.9}]
    for _ in range(6):
        tr.update(strong)
    sc = tr.score("A", "B")
    assert sc["seen"] == 6 and sc["rate"] >= 0.59 and sc["lag_stable"] is True
    # une paire jamais vue → score nul
    assert tr.score("X", "Y")["seen"] == 0


def test_donnees_insuffisantes_renvoie_vide():
    idx = _idx(20)
    series = {"A": pd.Series(np.arange(20.0), index=idx),
              "B": pd.Series(np.arange(20.0), index=idx)}
    assert ll.scan_pairs(series, max_lag=4, min_obs=60) == []
    assert ll.pair_lead_lag(np.arange(10.0), np.arange(10.0), max_lag=3) is None


def test_strong_candidates_exige_persistance():
    rep = {"pairs": [
        {"leader": "A", "follower": "B", "lag": 2, "corr": 0.4, "hit_rate": 0.6,
         "persistence": {"rate": 0.8, "seen": 8}},                     # retenu
        {"leader": "C", "follower": "D", "lag": 1, "corr": 0.4, "hit_rate": 0.6,
         "persistence": {"rate": 0.2, "seen": 2}},                     # rejeté (pas persistant)
    ]}
    strong = ll.strong_candidates(rep)
    assert len(strong) == 1 and strong[0]["leader"] == "A"
