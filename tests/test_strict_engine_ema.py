"""tests/test_strict_engine_ema.py — l'EMA du moteur STRICT doit rester la MÊME.

La boucle Python d'origine a été remplacée par `ewm(adjust=False)` pour le CPU.
C'est une entrée de calibration de trading : le gain de vitesse n'a d'intérêt que
si les chiffres sont rigoureusement inchangés. Ces tests comparent la nouvelle
implémentation à la récurrence d'origine, réécrite ici comme référence.
"""
import numpy as np
import pytest

from engine.strict_engine import _ema_recursive, _ema_series, _trix_series


def _ema_reference(arr: np.ndarray, span: int) -> np.ndarray:
    """Récurrence d'origine, conservée comme oracle."""
    alpha = 2.0 / (span + 1)
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def _serie(n: int, graine: int = 7) -> np.ndarray:
    rng = np.random.default_rng(graine)
    return np.cumsum(rng.normal(0.0, 1.0, n)) + 50_000.0


@pytest.mark.parametrize("n,span", [(3, 2), (500, 9), (5_000, 14), (20_000, 200)])
def test_ema_identique_a_la_reference(n, span):
    x = _serie(n)
    assert np.array_equal(_ema_recursive(x, span), _ema_reference(x, span))


def test_ema_series_delegue_sans_devier():
    x = _serie(1_000)
    assert np.array_equal(_ema_series(x, 21), _ema_reference(x, 21))


def test_trix_identique_a_la_triple_ema_de_reference():
    x = _serie(2_000, graine=11)
    e3 = _ema_reference(_ema_reference(_ema_reference(x, 14), 14), 14)
    attendu = np.zeros(len(e3))
    attendu[1:] = (e3[1:] - e3[:-1]) / np.where(e3[:-1] != 0, e3[:-1], 1e-9) * 100
    assert np.allclose(_trix_series(x, 14), attendu, rtol=0, atol=1e-12)


def test_serie_vide_ne_leve_pas():
    """La boucle d'origine plantait sur arr[0] ; on ne régresse pas là-dessus."""
    assert len(_ema_recursive(np.array([], dtype=float), 14)) == 0
