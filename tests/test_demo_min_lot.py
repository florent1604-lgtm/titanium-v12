"""Tests de l'adaptation auto du budget de risque au LOT MINIMUM (phase de test démo).

Vérifie : le calcul du risque du lot min par actif, le refus historique quand le
budget ne couvre pas le lot min (comportement OFF inchangé), l'acceptation une
fois le budget adapté, le fail-safe, et la lecture des flags de config.
"""
from __future__ import annotations

import pytest

import execution.demo_mt5_executor as ex
from execution.demo_mt5_executor import (
    compute_lot, _min_lot_risk, DemoExecutionRefused, DemoGuards,
)


class _SI:
    # BTCUSD-like : tick 1$, 0.1 lot min, pas 0.01
    trade_tick_size = 1.0
    trade_tick_value = 1.0
    volume_min = 0.1
    volume_step = 0.01
    volume_max = 100.0
    point = 1.0
    digits = 2


class _MT5:
    def symbol_info(self, _s):
        return _SI()


class _MT5NoSym:
    def symbol_info(self, _s):
        return None


def test_min_lot_risk_par_actif():
    # dist = |64000 - 64087| = 87 ; money_per_lot = 87 ; min_lot_risk = 87 * 0.1 = 8.7
    r = _min_lot_risk(_MT5(), "BTCUSD", 64000.0, 64087.0)
    assert r is not None and abs(r - 8.7) < 1e-6


def test_compute_lot_refuse_sous_le_min_OFF():
    """Comportement historique : budget < risque du lot min → REFUS (inchangé quand OFF)."""
    with pytest.raises(DemoExecutionRefused):
        compute_lot(_MT5(), "BTCUSD", 64000.0, 64087.0, 3.15)


def test_compute_lot_accepte_budget_adapte():
    """Une fois le budget adapté au lot min (× tolérance), le lot min passe."""
    mlr = _min_lot_risk(_MT5(), "BTCUSD", 64000.0, 64087.0)  # 8.7
    lot = compute_lot(_MT5(), "BTCUSD", 64000.0, 64087.0, mlr * 1.15)
    assert lot >= 0.1


def test_min_lot_risk_failsafe_none():
    assert _min_lot_risk(_MT5NoSym(), "X", 1.0, 0.9) is None
    assert _min_lot_risk(_MT5(), "X", 1.0, 1.0) is None  # dist = 0


def test_flags_defaut_OFF(monkeypatch):
    # ⚠️ Ce test valide les DÉFAUTS DU CODE : il doit effacer AUSSI le plafond, sinon il
    # lit le `.env` de la machine (qui peut légitimement le régler, ex. 10.0 pour laisser
    # passer le lot min crypto) et échoue sans qu'aucun code n'ait bougé.
    monkeypatch.delenv("DEMO_MIN_LOT_TEST", raising=False)
    monkeypatch.delenv("DEMO_MIN_LOT_MAX_RISK_PCT", raising=False)
    g = DemoGuards.from_env()
    assert g.min_lot_test is False
    assert g.min_lot_max_risk_pct == 5.0


def test_flags_ON(monkeypatch):
    monkeypatch.setenv("DEMO_MIN_LOT_TEST", "1")
    monkeypatch.setenv("DEMO_MIN_LOT_MAX_RISK_PCT", "3.0")
    g = DemoGuards.from_env()
    assert g.min_lot_test is True and g.min_lot_max_risk_pct == 3.0


def test_plafond_borne_l_adaptation():
    """Le risque du lot min (8.7) doit rester sous le plafond pour être adapté."""
    equity = 3150.0
    mlr = _min_lot_risk(_MT5(), "BTCUSD", 64000.0, 64087.0)  # 8.7
    ceiling_5pct = equity * 5.0 / 100.0    # 157.5 → OK, adaptable
    ceiling_01pct = equity * 0.1 / 100.0   # 3.15 → trop bas, refus conservé
    assert mlr <= ceiling_5pct
    assert mlr > ceiling_01pct
