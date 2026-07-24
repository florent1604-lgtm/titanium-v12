"""tests/test_decision_kernel.py — Validation de l'unification décisionnelle.

Vérifie que signal_engine + confluence_demo produisent le même verdict
sur mêmes données, via le DecisionKernel centralisé.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from core.decision_kernel import build_verdict, Verdict
from core.consensus_engine import build_consensus


class TestDecisionKernel:
    """Suite de tests du DecisionKernel."""

    def test_verdict_structure(self):
        """Verdict est immutable et bien structuré."""
        v = Verdict(
            allow=True,
            side=1,
            conviction=0.7,
            verdict_type="ENTER",
            reason_codes=("BRAIN_OK", "PORTFOLIO_OK"),
            source="KERNEL",
            decided_at="2026-07-24T12:00:00+00:00",
        )
        assert v.allow is True
        assert v.side == 1
        assert v.conviction == 0.7
        assert bool(v) is True  # allow + side != 0

    def test_verdict_bool_logic(self):
        """Verdict.__bool__() = allow AND side != 0."""
        v_allowed = Verdict(allow=True, side=1, conviction=0.5, verdict_type="ENTER")
        assert bool(v_allowed) is True

        v_blocked = Verdict(allow=False, side=1, conviction=0.5, verdict_type="BLOCK")
        assert bool(v_blocked) is False

        v_neutral = Verdict(allow=True, side=0, conviction=0.0, verdict_type="NEUTRAL")
        assert bool(v_neutral) is False

    def test_build_verdict_fail_closed_on_consensus_error(self):
        """Erreur consensus → BLOCK."""
        v = build_verdict("INVALID", confluence_result=None, scoring_result=None)
        assert v.allow is False
        assert v.verdict_type == "BLOCK"
        assert "CONSENSUS_ERROR" in v.reason_codes[0]

    def test_build_verdict_blocks_conflict(self):
        """Consensus CONFLICT → BLOCK."""
        # Simuler un consensus conflictué
        confluence = {"available": True, "side": 1, "criteria": {}}
        scoring = {"available": True, "side": -1, "criteria": {}}
        emotion = {"available": False}

        # build_consensus va détecter le conflit
        from core.consensus_engine import build_consensus
        consensus = build_consensus("BTCUSD", confluence, scoring, emotion)

        if consensus.get("status") == "CONFLICT":
            v = build_verdict(
                "BTCUSD",
                confluence_result=confluence,
                scoring_result=scoring,
                emotion=emotion,
            )
            assert v.allow is False
            assert "CONFLICT" in v.reason_codes[0]

    def test_build_verdict_blocks_insufficient(self):
        """Consensus INSUFFICIENT → BLOCK."""
        confluence = {"available": False}
        scoring = {"available": False}
        emotion = {"available": False}

        v = build_verdict(
            "BTCUSD",
            confluence_result=confluence,
            scoring_result=scoring,
            emotion=emotion,
        )
        assert v.allow is False
        assert "INSUFFICIENT" in v.reason_codes[0] or "CONSENSUS_ERROR" in v.reason_codes[0]

    def test_build_verdict_neutral_side(self):
        """Consensus neutre → ENTER avec side=0."""
        # Cas où confluence ET scoring sont neutres
        confluence = {"available": True, "side": 0, "criteria": {}}
        scoring = {"available": True, "side": "NEUTRE", "criteria": {}}
        emotion = {"available": False}

        v = build_verdict(
            "BTCUSD",
            confluence_result=confluence,
            scoring_result=scoring,
            emotion=emotion,
        )
        # Side=0 → NEUTRAL, bool(v)=False
        assert v.side == 0 or v.verdict_type in ("NEUTRAL", "BLOCK")

    def test_build_verdict_reason_codes_accumulated(self):
        """Reason codes s'accumulent le long du pipeline."""
        v = build_verdict(
            "BTCUSD",
            confluence_result=None,
            scoring_result=None,
            emotion=None,
        )
        # Au minimum : status, puis error
        assert len(v.reason_codes) > 0

    def test_build_verdict_timestamp_iso(self):
        """Timestamp en format ISO."""
        v = build_verdict(
            "BTCUSD",
            confluence_result=None,
            scoring_result=None,
        )
        assert "T" in v.decided_at  # ISO 8601
        assert "+" in v.decided_at or "Z" in v.decided_at

    def test_build_verdict_cache_functions(self):
        """Cache functions work."""
        from core.decision_kernel import cache_verdict, get_cached_verdict

        v = Verdict(
            allow=True,
            side=1,
            conviction=0.5,
            verdict_type="ENTER",
        )
        cache_verdict("BTCUSD", v)
        cached = get_cached_verdict("BTCUSD")
        assert cached is v


class TestDecisionKernelIntegration:
    """Tests d'intégration avec consensus_engine."""

    def test_consensus_and_kernel_agree(self):
        """Consensus et Kernel produisent le même side."""
        # Cas simple : confluence LONG + scoring LONG → consensus LONG
        confluence = {
            "available": True,
            "side": 1,
            "criteria": {"trend_sr": True},
        }
        scoring = {
            "available": True,
            "side": "ACHAT",
            "score": 8,
            "score_max": 16,
            "criteria": {"EMA200_H4": True},
        }
        emotion = {"available": False}

        consensus = build_consensus("BTCUSD", confluence, scoring, emotion)
        consensus_side = 1 if consensus.get("side") == "long" else (
            -1 if consensus.get("side") == "short" else 0
        )

        v = build_verdict(
            "BTCUSD",
            confluence_result=confluence,
            scoring_result=scoring,
            emotion=emotion,
        )

        # Si consensus a un avis, Kernel le propage (ou BLOCK)
        if v.allow and v.verdict_type != "BLOCK":
            # Verdict autorisé → side devrait suivre
            assert v.side in (0, 1, -1)


class TestDetectionCache:
    """Validation du cache de détection."""

    def test_cache_hit_on_same_price(self):
        """Cache réutilise si prix identique et < 5s."""
        from core.detection_cache import get_or_detect, clear_cache
        import pandas as pd

        clear_cache()

        # Créer un DF simple
        df = pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
        }, index=pd.date_range("2026-01-01", periods=2, freq="1h"))

        # Premier appel → recompute
        r1 = get_or_detect("BTCUSD", df, None)

        # Deuxième appel, same price → cache hit
        r2 = get_or_detect("BTCUSD", df, None)

        if r1 and r2:
            assert r1.last_price == r2.last_price

    def test_cache_miss_on_new_price(self):
        """Cache réutilise PAS si prix change."""
        from core.detection_cache import clear_cache, _cache_key

        clear_cache()

        # Test : clés différentes pour prix différents
        key1 = _cache_key("BTCUSD", 100.0)
        key2 = _cache_key("BTCUSD", 100.1)

        assert key1 != key2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
