"""fundamentals/risk_scorer.py — Calcul du score de risque macroéconomique (0–100).

Algorithme :
  1. Keyword matching pondéré sur le texte des articles (titre + description)
  2. Vélocité : ratio articles/heure actuelle vs moyenne 24h
  3. Normalisation vers 0–100 via sigmoid adaptative

Le score final est un rolling mean exponentiel pour éviter les sauts brusques.
"""
from __future__ import annotations
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)

_KEYWORDS_FILE = Path(__file__).parent / "keywords.json"

# EMA du score (lissage entre mises à jour)
_SCORE_EMA_ALPHA = 0.3   # 0=très lisse, 1=instantané
_ema_score: float = 25.0  # valeur initiale (neutre-bas)

# Historique pour calcul vélocité
_history_scores: List[Tuple[float, float]] = []   # (timestamp, raw_score)


def _load_keywords() -> Dict[str, Dict[str, float]]:
    try:
        return json.loads(_KEYWORDS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[RISK] Impossible de charger keywords.json: %s", e)
        return {}


_KEYWORDS = _load_keywords()


def reload_keywords() -> None:
    """Recharge les mots-clés depuis le disque (hot-reload)."""
    global _KEYWORDS
    _KEYWORDS = _load_keywords()
    logger.info("[RISK] Keywords rechargés (%d catégories)", len(_KEYWORDS))


def _keyword_score(text: str) -> float:
    """Compte les occurrences pondérées des mots-clés dans le texte."""
    raw = 0.0
    text_lower = text.lower()

    for category, keywords in _KEYWORDS.items():
        for keyword, weight in keywords.items():
            # Comptage des occurrences (chaque occurrence ajoute le poids)
            count = len(re.findall(r'\b' + re.escape(keyword.lower()) + r'\b', text_lower))
            if count > 0:
                # Diminishing returns : log(1 + count)
                raw += weight * math.log1p(count)

    return raw


def _velocity_factor(articles: List[Dict[str, Any]]) -> float:
    """Calcule un facteur multiplicateur basé sur la vélocité des articles.

    Si beaucoup d'articles sont récents (< 1h) vs la moyenne → risque amplifié.
    Retourne un facteur entre 0.8 et 1.5.
    """
    if not articles:
        return 1.0

    now   = datetime.now(timezone.utc).timestamp()
    recent = 0   # dernière heure
    total  = len(articles)

    for art in articles:
        pub = art.get("published", "")
        if not pub:
            continue
        dt = None
        # 1. RFC 2822 (flux RSS)
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub)
        except Exception:
            pass
        # 2. ISO 8601 (NewsAPI, GDELT)
        if dt is None:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except Exception:
                pass
        if dt is not None:
            age_hours = (now - dt.timestamp()) / 3600
            if age_hours < 1:
                recent += 1

    if total == 0:
        return 1.0

    recent_pct = recent / total
    # Si > 30% des articles sont dans la dernière heure → factor > 1
    return max(0.8, min(1.5, 0.8 + recent_pct * 1.4))


def _cfg_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _sigmoid_normalize(raw: float, k: Optional[float] = None,
                       midpoint: Optional[float] = None) -> float:
    """Transforme un score brut en 0–100 via une sigmoid adaptative.

    k       : pente (plus grand = transition plus abrupte)
    midpoint: score brut correspondant à 50 sur la sortie

    ⚠️ RECALIBRÉ 29/07. L'ancien réglage (midpoint=30, k=0.15) était calé sous le
    régime réel des news : le score BRUT observé tourne autour de 68 → la sigmoid
    saturait à 99,5 en PERMANENCE. Le capteur n'avait plus aucune dynamique : il
    n'informait plus, il bloquait (183 refus `FONDAMENTAUX_BLOCK` en 3 h, seuil 90).
    Un capteur toujours au maximum équivaut à un capteur en panne.

    Nouveau calage (midpoint≈régime observé) → l'échelle redevient discriminante :
      raw  40 →  ~14 (calme)   ·  raw  68 → ~47 (normal)
      raw 100 →  ~86 (élevé)   ·  raw 120 → ~95 (extrême réel)
    Réglable sans redéploiement : FUNDAMENTALS_SIGMOID_MID / _K.
    """
    if midpoint is None:
        midpoint = _cfg_float("FUNDAMENTALS_SIGMOID_MID", 70.0)
    if k is None:
        k = _cfg_float("FUNDAMENTALS_SIGMOID_K", 0.06)
    return 100.0 / (1.0 + math.exp(-k * (raw - midpoint)))


def compute_score(
    articles: List[Dict[str, Any]],
    text_corpus: Optional[str] = None,
) -> Dict[str, Any]:
    """Calcule le score de risque macroéconomique.

    Args:
        articles   : liste d'articles normalisés
        text_corpus: texte pré-concaténé (optionnel, sinon calculé depuis articles)

    Returns: dict avec score (0-100), composantes, timestamp
    """
    global _ema_score, _history_scores

    if not articles and not text_corpus:
        return {
            "score":    _ema_score,
            "raw":      0.0,
            "velocity": 1.0,
            "level":    _score_level(_ema_score),
            "articles": 0,
            "ts":       datetime.now(timezone.utc).isoformat(),
        }

    # Corpus textuel
    if text_corpus is None:
        from fundamentals.news_fetcher import get_all_text
        text_corpus = get_all_text(articles)

    raw_kw   = _keyword_score(text_corpus)
    velocity = _velocity_factor(articles)
    raw      = raw_kw * velocity

    # Normalisation → 0-100
    normalized = _sigmoid_normalize(raw)

    # EMA pour lisser les mises à jour
    _ema_score = _SCORE_EMA_ALPHA * normalized + (1 - _SCORE_EMA_ALPHA) * _ema_score
    _ema_score = round(min(100.0, max(0.0, _ema_score)), 2)

    # Historique pour audit
    now = datetime.now(timezone.utc).timestamp()
    _history_scores.append((now, _ema_score))
    if len(_history_scores) > 1000:
        _history_scores = _history_scores[-500:]

    result = {
        "score":       _ema_score,
        "raw":         round(raw, 2),
        "raw_keywords": round(raw_kw, 2),
        "velocity":    round(velocity, 3),
        "level":       _score_level(_ema_score),
        "articles":    len(articles),
        "ts":          datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "[RISK] Score=%.1f (%s) raw_kw=%.1f vel=%.2f articles=%d",
        _ema_score, result["level"], raw_kw, velocity, len(articles),
    )
    return result


def _score_level(score: float) -> str:
    """Catégorise le score en niveau lisible."""
    if score >= 75:  return "EXTREME"
    if score >= 55:  return "HIGH"
    if score >= 35:  return "MEDIUM"
    if score >= 15:  return "LOW"
    return "CALM"


def get_current_score() -> float:
    """Retourne le score EMA courant (thread-safe, lecture seule)."""
    return _ema_score


def get_score_history() -> List[Tuple[float, float]]:
    """Retourne l'historique (timestamp, score) pour audit."""
    return list(_history_scores)
