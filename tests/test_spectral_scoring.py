"""tests/test_spectral_scoring.py — Tests de la dépondération spectrale (Phase 1).

Vérifie que le flag résolu (override par symbole > SPECTRAL_REGIME_FILTER global) laisse
le score /16 inchangé quand il est off, et que la dépondération des critères de cycle
(SPECTRAL_CYCLE_CRITERIA, défaut ["TRIX_5M"]) ne s'applique que si le flag résolu est actif
ET qu'aucun cycle net n'est détecté (has_cycle=False). Aucun nouveau point n'est ajouté au
score max — seule la pondération change.

Le flag global reste à 0 par défaut ; BTC/USDT et PAXG/USDT ont chacun un override validé
indépendamment en walk-forward (voir SYM_OVERRIDES dans utils/config.py) — les résultats ont
divergé par actif (BTC accepté, PAXG refusé), d'où l'override par symbole plutôt qu'un flag
global unique.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from core import scoring_engine as se


def _df(n: int, close: float) -> pd.DataFrame:
    return pd.DataFrame({"close": [close] * n, "high": [close] * n, "low": [close] * n})


def _score_with(spectral_features, sym: str = "ETH/USDT"):
    """Lance score_setup avec toutes les dépendances externes mockées, pour isoler
    uniquement l'effet de la dépondération spectrale sur EMA200_H4 (True) + TRIX_5M (True).

    `sym` par défaut = "ETH/USDT", absent de SYM_OVERRIDES, pour tester le flag global
    (SPECTRAL_REGIME_FILTER) sans interférence d'un override par symbole.
    """
    df_h4 = _df(200, 110.0)
    df30 = _df(60, 110.0)
    with patch.object(se, "compute_ema200", return_value=100.0), \
         patch.object(se, "detect_bos", return_value=False), \
         patch.object(se, "has_ob_or_fvg_alignment", return_value=(False, "none", 0)), \
         patch.object(se, "detect_rejection_candle", return_value=False), \
         patch.object(se, "trix_signal", return_value=True), \
         patch.object(se, "detect_liquidity_sweep", return_value=False), \
         patch.object(se, "get_market_regime", return_value="RANGE"), \
         patch.object(se, "compute_adx", return_value=0.0), \
         patch.object(se, "rsi_signal", return_value=(False, False, 50.0)), \
         patch.object(se, "rsi_divergence", return_value="none"), \
         patch.object(se, "detect_volume_spike", return_value=False):
        return se.score_setup(
            sym=sym, df_h4=df_h4, df_1m=df30, df30=df30,
            spectral_features=spectral_features,
        )


def test_flag_off_ignores_spectral_features():
    """Flag global off (défaut) sur un symbole sans override : score inchangé."""
    with patch.object(se, "SPECTRAL_REGIME_FILTER", False):
        _, _, _, ctx_no_spectral = _score_with(None)
        _, _, _, ctx_with_spectral = _score_with(SimpleNamespace(
            has_cycle=False, phase_zone="creux", dominant_cycle=20))
    assert ctx_no_spectral["weighted"] == ctx_with_spectral["weighted"] == 2.0


def test_flag_on_depondere_when_no_cycle():
    """Flag global on + has_cycle=False → TRIX_5M pondéré ×0.5 (au lieu de ×1.0)."""
    with patch.object(se, "SPECTRAL_REGIME_FILTER", True):
        _, _, _, ctx = _score_with(SimpleNamespace(has_cycle=False, phase_zone="creux", dominant_cycle=20))
    # EMA200_H4 (1.0) + TRIX_5M dépondéré (0.5) = 1.5 — pas de nouveau point ajouté au score max
    assert ctx["weighted"] == 1.5
    assert ctx["score_max"] == len(se.SCORE_CRITERIA)


def test_flag_on_no_depondere_when_cycle_present():
    """Flag global on + has_cycle=True → pas de dépondération (SMC seul ne suffit pas à filtrer)."""
    with patch.object(se, "SPECTRAL_REGIME_FILTER", True):
        _, _, _, ctx = _score_with(SimpleNamespace(has_cycle=True, phase_zone="creux", dominant_cycle=20))
    assert ctx["weighted"] == 2.0
    assert ctx["spectral_has_cycle"] is True
    assert ctx["spectral_phase_zone"] == "creux"


def test_per_symbol_override_takes_precedence_over_global_flag():
    """BTC/USDT (override validé ON) dépondère même si le flag global est off ;
    PAXG/USDT (override validé OFF) ne dépondère jamais, même si le flag global est on."""
    no_cycle = SimpleNamespace(has_cycle=False, phase_zone="creux", dominant_cycle=20)

    with patch.object(se, "SPECTRAL_REGIME_FILTER", False):
        _, _, _, ctx_btc = _score_with(no_cycle, sym="BTC/USDT")
    assert ctx_btc["weighted"] == 1.5  # override BTC=on l'emporte sur le flag global off

    with patch.object(se, "SPECTRAL_REGIME_FILTER", True):
        _, _, _, ctx_paxg = _score_with(no_cycle, sym="PAXG/USDT")
    assert ctx_paxg["weighted"] == 2.0  # override PAXG=off l'emporte sur le flag global on
