"""Segment ÉMOTION v2 (circumplex) — 2 axes, capitulation≠panique, espoir, no-RSI."""
from emotion import emotion_engine as em


def test_no_rsi_signal():
    # RSI retiré (directive Florent : mécanique) — aucun signal ne le lit
    assert all("rsi" not in s.name for s in em.REGISTRY)
    st = em.compute_emotion({"rsi": 90})   # rsi ignoré → aucune donnée d'émotion
    assert not st.available


def test_panic_vs_capitulation_same_fear_different_energy():
    # PEUR + haute énergie = PANIQUE (peut encore tomber) → on ne vend pas mais on ne fade pas
    panic = em.compute_emotion({"delta_volume": -0.9, "macro_fear": 90, "macro_risk": 95,
                                "atr_zscore": 3.0, "volume_surge": 0.9, "liquidity_sweep": -0.8})
    assert panic.label == em.PANIC and panic.contrarian_bias is None and panic.filter_block == "short"
    # PEUR marquée (pas extrême) + énergie épuisée = CAPITULATION (le flush) → fade LONG
    capit = em.compute_emotion({"delta_volume": -0.6, "macro_risk": 75,
                                "atr_zscore": 0.2, "volume_surge": 0.05})
    assert -70 < capit.valence <= -40                    # bande capitulation, pas désespoir
    assert capit.label == em.CAPITULATION and capit.contrarian_bias == "long"


def test_euphoria_vs_complacency():
    euph = em.compute_emotion({"delta_volume": 0.9, "funding_rate": 0.0006, "long_short_ratio": 3.0,
                               "atr_zscore": 2.5, "volume_surge": 0.9})
    assert euph.label == em.EUPHORIA and euph.contrarian_bias == "short" and euph.filter_block == "long"
    calm = em.compute_emotion({"delta_volume": 0.8, "funding_rate": 0.0005, "long_short_ratio": 2.5,
                               "atr_zscore": 0.1, "volume_surge": 0.05})
    assert calm.label == em.COMPLACENCY and calm.contrarian_bias is None


def test_despair_is_the_numb_bottom_beyond_capitulation():
    # Peur EXTRÊME + énergie quasi nulle = DÉSESPOIR (fond numb, au-delà de la capitulation)
    st = em.compute_emotion({"delta_volume": -0.95, "macro_risk": 98, "long_short_ratio": 0.4,
                             "atr_zscore": 0.2, "volume_surge": 0.05})
    assert st.valence <= -70 and st.arousal <= 25
    assert st.label == em.DESPAIR and st.contrarian_bias == "long" and st.filter_block == "short"


def test_thrill_is_rising_excitement_before_euphoria():
    # Avidité forte + très haute énergie, mais pas encore le sommet extrême = EXALTATION
    st = em.compute_emotion({"delta_volume": 0.6, "funding_rate": 0.0004, "long_short_ratio": 2.0,
                             "liquidity_sweep": 0.7, "atr_zscore": 3.0, "volume_surge": 0.9})
    assert 55 <= st.valence < 80 and st.arousal >= 70
    assert st.label == em.THRILL and st.filter_block == "long" and st.contrarian_bias is None


def test_hope_when_fear_recedes():
    st = em.compute_emotion({"delta_volume": -0.5, "macro_risk": 70, "atr_zscore": 0.4,
                             "valence_momentum": 0.6})   # peur qui reflue
    assert st.label == em.HOPE


def test_two_axes_separate_direction_and_energy():
    st = em.compute_emotion({"delta_volume": -0.9, "atr_zscore": 3.0, "volume_surge": 0.9})
    assert st.valence < 0 and st.arousal > 60   # peur ET haute énergie


def test_stale_data_lowers_confidence():
    fresh = em.compute_emotion({"delta_volume": 0.5, "atr_zscore": 1.0, "source_age_s": 2})
    old = em.compute_emotion({"delta_volume": 0.5, "atr_zscore": 1.0, "source_age_s": 60, "max_age_s": 15})
    assert not fresh.stale and old.stale and old.confidence < fresh.confidence


def test_failsafe_and_extensible():
    assert not em.compute_emotion({}).available
    em.register_signal(em.EmotionSignal("probe", "valence", 5.0, lambda c: c.get("probe")))
    st = em.compute_emotion({"probe": 1.0})
    em.REGISTRY.pop()
    assert st.available and st.valence == 100.0


def test_nan_signal_is_rejected_not_treated_as_extreme():
    # red-team Codex P0 : un signal NaN ne doit PAS devenir +1 (fausse euphorie)
    assert not em.compute_emotion({"delta_volume": float("nan")}).available
    st = em.compute_emotion({"delta_volume": float("nan"), "atr_zscore": 1.0})
    assert "delta_volume" not in st.breakdown          # NaN ignoré, pas compté extrême


def test_stale_neutralizes_actionable_bias():
    # red-team Codex P0/P1 : stale ne doit plus laisser un biais exploitable
    st = em.compute_emotion({"delta_volume": 0.9, "funding_rate": 0.0006, "long_short_ratio": 3.0,
                             "atr_zscore": 2.5, "volume_surge": 0.9,
                             "source_age_s": 999, "max_age_s": 15})
    assert st.label == em.EUPHORIA and st.stale
    assert st.contrarian_bias is None and st.filter_block is None


def test_low_confidence_neutralizes_actionable_bias():
    # une seule donnée (confiance basse) → aucune sortie actionnable
    st = em.compute_emotion({"delta_volume": -0.9})
    assert st.confidence < em.MIN_ACTIONABLE_CONFIDENCE
    assert st.contrarian_bias is None and st.filter_block is None


def test_register_signal_rejects_invalid():
    import pytest
    with pytest.raises(ValueError):   # axe inconnu
        em.register_signal(em.EmotionSignal("bad_axis", "xxx", 1.0, lambda c: 0.5))
    with pytest.raises(ValueError):   # poids nul
        em.register_signal(em.EmotionSignal("bad_w", "valence", 0.0, lambda c: 0.5))
    with pytest.raises(ValueError):   # nom dupliqué d'un signal existant
        em.register_signal(em.EmotionSignal("delta_volume", "valence", 1.0, lambda c: 0.5))
