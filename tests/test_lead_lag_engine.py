"""Boucle de concordance multi-timeframe : scan par TF + persistance, aucun réseau."""
import asyncio

import numpy as np
import pandas as pd

import core.lead_lag_engine as le


def _closes(sym, tf, n=400):
    rng = np.random.default_rng(abs(hash((sym, tf))) % 2**32)
    idx = pd.date_range("2026-07-01", periods=n, freq="15min", tz="UTC")
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, n))), index=idx)


def test_run_cycle_multi_tf_remplit_chaque_tf():
    le.LAST.clear(); le.LAST.update({"ts": None, "by_tf": {}})
    le.TRACKERS.clear()
    rep = asyncio.run(le.run_cycle(
        ["A", "B", "C"], tfs=("M15", "H1"),
        fetch_fn=lambda s, tf: _closes(s, tf), max_lag=6, notify=False))
    assert set(rep["by_tf"].keys()) == {"M15", "H1"}
    snap = le.status_snapshot()
    assert set(snap["timeframes"]) == {"M15", "H1"}
    assert snap["by_tf"]["M15"]["n_pairs"] > 0


def test_run_cycle_fail_safe_sur_tf():
    le.LAST.clear(); le.LAST.update({"ts": None, "by_tf": {}})
    le.TRACKERS.clear()

    def fetch(s, tf):
        if tf == "H4":
            raise RuntimeError("indispo")
        return _closes(s, tf)

    rep = asyncio.run(le.run_cycle(["A", "B"], tfs=("M15", "H4"),
                                   fetch_fn=fetch, max_lag=4, notify=False))
    # H4 échoue par symbole → rapport vide (0 paire) mais n'empêche PAS M15
    assert rep["by_tf"]["M15"]["n_pairs"] > 0
    assert rep["by_tf"].get("H4", {}).get("n_pairs", 0) == 0
