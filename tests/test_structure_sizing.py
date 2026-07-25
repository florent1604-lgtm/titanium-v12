"""Test du sizing par QUALITÉ DE STRUCTURE (Florent) : plus de piliers → plus gros lot."""
from __future__ import annotations

import core.confluence_demo_engine as ce


def test_scale_avec_piliers():
    f = ce._structure_size_factor
    assert f(2, 0.0) < f(3, 0.0) < f(4, 0.0) < f(5, 0.0)
    assert f(5, 0.0) == 1.0        # structure pleine → lot max
    assert f(2, 0.0) == 0.35       # 2 piliers → petit lot
    assert f(0, 0.0) == 0.20       # jamais sous le plancher


def test_meilleur_entre_structure_et_conviction():
    f = ce._structure_size_factor
    assert f(2, 0.90) == 0.90      # conviction cerveau forte l'emporte
    assert f(5, 0.30) == 1.0       # structure pleine l'emporte
    assert f(9, 2.0) == 1.0        # borné haut à 1.0


def test_failsafe_types():
    f = ce._structure_size_factor
    assert f(None, None) == 0.20
    assert f("x", "y") == 0.20
