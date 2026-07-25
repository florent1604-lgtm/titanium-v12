"""Tests du relax de fraîcheur M15 auto-scopé au week-end (phase de test démo).

Consigne Florent : assouplir la fraîcheur M15 CE week-end, restaurer le seuil
normal AUTOMATIQUEMENT à l'ouverture lundi. Vérifie que le relax ne s'applique
QUE le week-end ET flag ON ; sinon seuil normal (3.0).
"""
from __future__ import annotations

import datetime as dt

import core.confluence_adapter as ca

SAT = dt.datetime(2026, 7, 25, 14, 0, tzinfo=dt.timezone.utc)      # samedi
SUN = dt.datetime(2026, 7, 26, 23, 0, tzinfo=dt.timezone.utc)      # dimanche
MON = dt.datetime(2026, 7, 27, 9, 0, tzinfo=dt.timezone.utc)       # lundi (ouverture)
FRI_EVE = dt.datetime(2026, 7, 24, 21, 0, tzinfo=dt.timezone.utc)  # vendredi 21h
FRI_DAY = dt.datetime(2026, 7, 24, 15, 0, tzinfo=dt.timezone.utc)  # vendredi 15h


def test_is_weekend_window():
    assert ca._is_weekend_window(SAT) is True
    assert ca._is_weekend_window(SUN) is True
    assert ca._is_weekend_window(FRI_EVE) is True     # vendredi soir inclus
    assert ca._is_weekend_window(MON) is False        # lundi = normal
    assert ca._is_weekend_window(FRI_DAY) is False     # vendredi journée = normal


def test_relax_seulement_weekend_flag_on(monkeypatch):
    monkeypatch.setenv("DEMO_STALE_RELAX", "1")
    monkeypatch.delenv("DEMO_STALE_RELAX_BARS", raising=False)
    assert ca._ltf_max_stale_bars(SAT) == 20.0     # relax appliqué le week-end
    assert ca._ltf_max_stale_bars(MON) == 3.0      # AUTO-RESTAURÉ lundi (consigne)


def test_pas_de_relax_flag_off(monkeypatch):
    monkeypatch.setenv("DEMO_STALE_RELAX", "0")
    assert ca._ltf_max_stale_bars(SAT) == 3.0      # flag OFF → normal même le week-end


def test_relax_bars_configurable(monkeypatch):
    monkeypatch.setenv("DEMO_STALE_RELAX", "1")
    monkeypatch.setenv("DEMO_STALE_RELAX_BARS", "40")
    assert ca._ltf_max_stale_bars(SAT) == 40.0
