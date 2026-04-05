"""fundamentals — Module de scoring macroéconomique pour Titanium v12.

Composants :
  news_fetcher    : agrégateur multi-sources (NewsAPI, GDELT, RSS)
  risk_scorer     : calcul du score de risque 0-100
  signal_modulator: filtre/réduction des signaux SMC selon le risque

Point d'entrée principal : `get_current_score()` depuis risk_scorer.
"""
from fundamentals.risk_scorer import get_current_score, compute_score
from fundamentals.signal_modulator import modulate, is_active, get_modulation_stats

__all__ = ["get_current_score", "compute_score", "modulate", "is_active", "get_modulation_stats"]
