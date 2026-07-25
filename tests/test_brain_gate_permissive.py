"""Tests du mode BRAIN_GATE_PERMISSIVE (test démo — laisser passer plus de trades).

OFF (défaut) = comportement historique strict. ON = suit le cœur quand le cerveau
n'a pas d'opinion (NO_COVERAGE / INSUFFICIENT / conflit interne de familles), mais
GARDE le veto sur opposition RÉELLE de direction (opposing_engines / cside == -side)
et sur le MASTER.
"""
from __future__ import annotations

import core.brain_gate as bg
from core.brain_gate import gate_entry


def _auto(_s):            # master AUTO
    return None


def _none(_s):            # pas de couverture
    return None


def _insuff(_s):
    return {"status": "INSUFFICIENT", "side": "neutral"}


def _soft_conflict(_s):   # conflit interne, PAS d'opposition de sens
    return {"status": "CONFLICT", "side": "long", "conflict": True, "opposing_engines": []}


def _hard_conflict(_s):   # opposition RÉELLE (moteurs opposés + sens inverse)
    return {"status": "CONFLICT", "side": "short", "conflict": True, "opposing_engines": ["scoring"]}


def test_off_is_historical_strict(monkeypatch):
    monkeypatch.setattr(bg, "BRAIN_GATE_PERMISSIVE", False)
    assert gate_entry("BTCUSDT", 1, consensus_fn=_none, master_fn=_auto).allow is False
    assert gate_entry("BTCUSDT", 1, consensus_fn=_insuff, master_fn=_auto).allow is False
    assert gate_entry("BTCUSDT", 1, consensus_fn=_soft_conflict, master_fn=_auto).allow is False


def test_on_follows_heart_when_brain_has_no_opinion(monkeypatch):
    monkeypatch.setattr(bg, "BRAIN_GATE_PERMISSIVE", True)
    g1 = gate_entry("BTCUSDT", 1, consensus_fn=_none, master_fn=_auto)
    assert g1.allow and g1.side == 1 and "BRAIN_PERMISSIVE_NOCOV" in g1.reason_codes
    g2 = gate_entry("BTCUSDT", 1, consensus_fn=_insuff, master_fn=_auto)
    assert g2.allow and g2.side == 1 and "BRAIN_PERMISSIVE_INSUFF" in g2.reason_codes
    g3 = gate_entry("BTCUSDT", 1, consensus_fn=_soft_conflict, master_fn=_auto)
    assert g3.allow and g3.side == 1 and "BRAIN_PERMISSIVE_SOFTCONFLICT" in g3.reason_codes


def test_on_still_vetoes_real_opposition(monkeypatch):
    """Même permissif, une opposition RÉELLE de direction bloque (garde-fou conservé)."""
    monkeypatch.setattr(bg, "BRAIN_GATE_PERMISSIVE", True)
    g = gate_entry("BTCUSDT", 1, consensus_fn=_hard_conflict, master_fn=_auto)
    assert g.allow is False and "BRAIN_SIDE_CONFLICT" in g.reason_codes


def test_master_always_wins_even_permissive(monkeypatch):
    monkeypatch.setattr(bg, "BRAIN_GATE_PERMISSIVE", True)
    g = gate_entry("BTCUSDT", 1, consensus_fn=_none, master_fn=lambda _s: "PAUSE")
    assert g.allow is False and "MASTER_PAUSE" in g.reason_codes
