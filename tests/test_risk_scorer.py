"""tests/test_risk_scorer.py — Tests unitaires du RiskScorer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fundamentals.risk_scorer import (
    _keyword_score, _velocity_factor, _sigmoid_normalize,
    compute_score, get_current_score,
)


def test_keyword_score_high_risk():
    text = "war nuclear attack collapse bank run hyperinflation"
    score = _keyword_score(text)
    assert score > 20, f"Score trop bas pour un texte à haut risque: {score}"


def test_keyword_score_low_risk():
    text = "rate cut dovish stimulus recovery bullish strong jobs"
    score = _keyword_score(text)
    assert score < 0, f"Score devrait être négatif pour un texte low-risk: {score}"


def test_keyword_score_neutral():
    text = "the market opened today with moderate trading volume"
    score = _keyword_score(text)
    assert -5 < score < 5, f"Score neutre attendu: {score}"


def test_velocity_factor_no_articles():
    factor = _velocity_factor([])
    assert factor == 1.0


def test_velocity_factor_recent():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    articles = [
        {"published": now.isoformat(), "title": "test"},
        {"published": now.isoformat(), "title": "test2"},
    ]
    factor = _velocity_factor(articles)
    assert factor > 1.0, f"Articles récents devraient augmenter le facteur: {factor}"


def test_sigmoid_normalize_bounds():
    assert _sigmoid_normalize(0)   < 50
    assert _sigmoid_normalize(30)  == pytest_approx(50, tolerance=5)
    assert _sigmoid_normalize(100) > 90
    assert 0 <= _sigmoid_normalize(-50) <= 100
    assert 0 <= _sigmoid_normalize(200) <= 100


_abs = abs  # Capturer le builtin avant tout shadowing

def pytest_approx(val, tolerance=1):
    """Mini approx pour éviter la dépendance pytest."""
    class _Approx:
        def __eq__(self, other): return _abs(other - val) <= tolerance
    return _Approx()


def test_compute_score_empty():
    result = compute_score([], "")
    assert "score" in result
    assert 0 <= result["score"] <= 100


def test_compute_score_high_risk_text():
    corpus = "nuclear war attack collapse bank run financial crisis crash meltdown panic"
    articles = [{"title": corpus, "description": "", "published": "", "source": "test", "url": ""}]
    result = compute_score(articles, corpus)
    assert result["score"] > 40, f"Score macro devrait être élevé: {result['score']}"
    assert result["level"] in ("MEDIUM", "HIGH", "EXTREME")


def test_compute_score_low_risk_text():
    corpus = "rate cut dovish stimulus recovery ceasefire peace agreement"
    articles = [{"title": corpus, "description": "", "published": "", "source": "test", "url": ""}]
    result = compute_score(articles, corpus)
    assert result["level"] in ("CALM", "LOW", "MEDIUM")


def test_compute_score_returns_required_fields():
    result = compute_score([], "test")
    for field in ("score", "level", "ts", "articles"):
        assert field in result, f"Champ manquant: {field}"


if __name__ == "__main__":
    test_keyword_score_high_risk()
    test_keyword_score_low_risk()
    test_keyword_score_neutral()
    test_velocity_factor_no_articles()
    test_velocity_factor_recent()
    test_compute_score_empty()
    test_compute_score_high_risk_text()
    test_compute_score_low_risk_text()
    test_compute_score_returns_required_fields()
    print("✅ Tous les tests risk_scorer passent")
