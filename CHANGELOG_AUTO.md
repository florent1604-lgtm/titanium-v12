# CHANGELOG AUTO — Titanium v12

## 2026-04-05

### feat: Module FUNDAMENTALS — Scoring macro-économique & modulation de signaux

**Fichiers créés :**
- `fundamentals/__init__.py`
- `fundamentals/news_fetcher.py` — agrégateur multi-sources (NewsAPI, GDELT, RSS ×5)
- `fundamentals/risk_scorer.py` — score 0-100 par keyword weighting + vélocité + EMA lissage
- `fundamentals/signal_modulator.py` — filtre/réduction signaux SMC + auto-rollback
- `fundamentals/fetcher_loop.py` — boucle asyncio de rafraîchissement (15 min)
- `fundamentals/keywords.json` — 60+ mots-clés pondérés (risk_high, risk_medium, risk_low, crypto)
- `fundamentals/tuning_log.md` — audit des reconfigurations
- `api/fundamentals_routes.py` — endpoints /fundamentals/* (score, news, history, reload, enable, disable)
- `config/fundamentals.json` — configuration du module
- `data/risk_history.json` — historique du score (auto-généré)
- `ALERT_FUNDAMENTALS.md` — alertes circuit breaker
- `tests/test_risk_scorer.py` — 9 tests unitaires ✅
- `tests/test_modulator.py` — 10 tests unitaires ✅

**Fichiers modifiés :**
- `utils/config.py` — ajout FUNDAMENTALS_*, NEWSAPI_KEY, GDELT_ENABLED
- `api/api_server.py` — inclusion du router + tâche fundamentals_loop dans lifespan
- `core/signal_engine.py` — modulation macro appliquée avant emit_signal

**Logique de modulation :**
```
risk_score ∈ [0, 30]   → signal inchangé (risk_factor=1.0)
risk_score ∈ (30, 70)  → score réduit (factor = 1 - ((risk-30)/40) × 0.5)
risk_score ∈ [70, 100] → signal annulé (None)
```

**Feature flag :** `FUNDAMENTALS_ENABLED=0` dans `.env` pour désactivation complète.

**Auto-rollback :** si réduction moyenne > 30% sur 20 dernières modulations → désactivation + ALERT_FUNDAMENTALS.md.

---

### fix: Optimizer walk-forward (Sharpe OOS)
- Backtest bidirectionnel (LONG + SHORT) → élimine le biais bear market
- Minimum 10 trades OOS requis (OPT_MIN_OOS_TRADES)
- Sharpe cappé à ±10 (plus de valeurs aberrantes -74/-552)
- Log du gap IS/OOS pour détection overfitting

### fix: Strict engine Sharpe annualization
- Annualisation par trades/jour (pas sqrt(252) flat)
- Filtre EMA200 sur les entrées TRIX (réduction faux signaux range)

### fix: Cooling period signaux
- SIGNAL_COOLDOWN_SEC=300 : même sens bloqué 5 min
- Direction opposée passe immédiatement
- Correlation ID unique par signal

### fix: Delta volume normalisé
- Pondération par notionnel (price × qty) — DELTA_VOL_USE_NOTIONAL=1

### feat: Circuit breaker learning
- Winrate rolling 20 trades < 30% → reset poids + blocage signaux
- Trigger d'adaptation tous les 50 signaux (en plus du trigger 2h)
