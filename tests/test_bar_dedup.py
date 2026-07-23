"""R1 — anti ré-entrée sur la même barre clôturée (swing/forex).

Prouve qu'après une fermeture, un signal encore présent sur la MÊME barre
clôturée ne rouvre PAS la position au scan suivant.
"""
import asyncio

import pandas as pd

import core.swing_engine as se


def _df():
    idx = pd.date_range("2026-07-01", periods=3, freq="4h", tz="UTC")
    return pd.DataFrame({"open": [1.0, 1.0, 1.0], "high": [1.0, 1.0, 1.0],
                         "low": [1.0, 1.0, 1.0], "close": [1.0, 1.0, 1.0]}, index=idx)


def _neutralize_risk(monkeypatch):
    """Isole le garde R3 : plafonds neutralisés, états forex/crypto contrôlés
    (le test ne vise que la logique R1 de dédoublonnage par barre)."""
    import core.portfolio_risk as pr
    from core.forex_engine import forex_state
    monkeypatch.setattr(pr, "RISK_MAX_STRATEGY_PCT", 5000.0)
    monkeypatch.setattr(pr, "RISK_MAX_CLUSTER_PCT", 5000.0)
    monkeypatch.setattr(pr, "RISK_MAX_GROSS_PCT", 5000.0)
    monkeypatch.setattr(pr, "RISK_MAX_NET_PCT", 5000.0)
    monkeypatch.setattr(pr, "_crypto_engine", lambda: None)
    monkeypatch.setitem(forex_state, "positions", {})
    monkeypatch.setitem(forex_state, "equity", 10000.0)


def test_swing_no_reentry_same_bar(monkeypatch):
    _neutralize_risk(monkeypatch)
    df = _df()
    se._configs.clear()
    se._configs["TEST"] = {"tf": "H4", "sl_atr": 2.0, "tp_ladder": [1, 2, 3],
                           "align_ema50": False, "rsi_gate": False,
                           "time_stop_bars": 60, "style": "swing"}
    se.swing_state.update(equity=10000.0, positions={}, trades=[], last_signal={},
                          errors=[], scan_count=0, last_bar={})

    import data.mt5_provider as mp
    monkeypatch.setattr(mp, "get_tick", lambda s: {"bid": 100.0, "ask": 100.1,
                                                   "mid": 100.05, "ts": "x", "stale": False})
    monkeypatch.setattr(mp, "get_rates", lambda s, tf, n: df)
    monkeypatch.setattr(se, "_signal", lambda d, c: "long")
    monkeypatch.setattr(se, "_atr", lambda d: 1.0)
    monkeypatch.setattr(se, "_save", lambda: None)

    # 1er scan : ouvre la position et mémorise la barre
    asyncio.run(se.scan_once())
    assert "TEST" in se.swing_state["positions"], "position ouverte au 1er scan"
    assert se.swing_state["last_bar"]["TEST"] == df.index[-2].isoformat()

    # La position se ferme (SL/TP/timestop) — mais on est TOUJOURS sur la même barre
    se.swing_state["positions"].clear()

    # 2e scan : le signal est encore là, mais R1 doit REFUSER la ré-entrée
    r2 = asyncio.run(se.scan_once())
    assert "TEST" not in se.swing_state["positions"], "R1: pas de ré-entrée sur la même barre"
    assert any("anti ré-entrée" in s for s in r2["skipped"])

    # Nouvelle barre clôturée → ré-entrée autorisée
    df2 = _df()
    df2.index = pd.date_range("2026-07-02", periods=3, freq="4h", tz="UTC")
    monkeypatch.setattr(mp, "get_rates", lambda s, tf, n: df2)
    asyncio.run(se.scan_once())
    assert "TEST" in se.swing_state["positions"], "nouvelle barre → ré-entrée autorisée"


def test_concurrent_scans_single_entry(monkeypatch):
    """R1 race (revue Codex) : deux scans concurrents (boucle + POST /scan) ne
    doivent produire qu'UNE seule entrée sur la même barre."""
    _neutralize_risk(monkeypatch)
    df = _df()
    se._configs.clear()
    se._configs["TEST"] = {"tf": "H4", "sl_atr": 2.0, "tp_ladder": [1, 2, 3],
                           "align_ema50": False, "rsi_gate": False,
                           "time_stop_bars": 60, "style": "swing"}
    se.swing_state.update(equity=10000.0, positions={}, trades=[], last_signal={},
                          errors=[], scan_count=0, last_bar={})
    import data.mt5_provider as mp
    monkeypatch.setattr(mp, "get_tick", lambda s: {"bid": 100.0, "ask": 100.1,
                                                   "mid": 100.05, "ts": "x", "stale": False})
    monkeypatch.setattr(mp, "get_rates", lambda s, tf, n: df)
    monkeypatch.setattr(se, "_signal", lambda d, c: "long")
    monkeypatch.setattr(se, "_atr", lambda d: 1.0)
    monkeypatch.setattr(se, "_save", lambda: None)

    async def two_concurrent():
        return await asyncio.gather(se.scan_once(), se.scan_once())

    r1, r2 = asyncio.run(two_concurrent())
    # exactement UN des deux scans a réellement ouvert
    opened = ("TEST" in r1["signals"]) + ("TEST" in r2["signals"])
    assert opened == 1, f"double entrée concurrente: {opened} ouvertures"
    assert "TEST" in se.swing_state["positions"]
