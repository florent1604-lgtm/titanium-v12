# Architecture — Titanium v12

*Généré le 2026-04-05*

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway (FastAPI)                     │
│  /state  /ws/{sym}  /optim/*  /chat  /fundamentals/*       │
└─────────────────────────────────────────────────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    ▼                      ▼                      ▼
┌──────────────┐  ┌─────────────────┐  ┌──────────────────────┐
│ Signal Engine│  │   Optimizer     │  │   FUNDAMENTALS       │
│ scan_loop    │  │ walk-forward    │  │  ┌─────────────────┐  │
│ 5s/symbole   │  │ SL/TP 24h      │  │  │ news_fetcher    │  │
└──────┬───────┘  └────────┬────────┘  │  │ (NewsAPI/GDELT/ │  │
       │                   │           │  │  RSS)           │  │
       ▼                   ▼           │  ├─────────────────┤  │
┌──────────────┐  ┌─────────────────┐  │  │ risk_scorer     │  │
│ scoring_     │  │ strict_engine   │  │  │ (0-100, EMA)    │  │
│ engine /11   │  │ TRIX recalib 2d │  │  ├─────────────────┤  │
└──────┬───────┘  └─────────────────┘  │  │ signal_modulator│  │
       │                               │  │ (filtre/réduit) │  │
       ▼                               └──┴─────────────────┘  │
┌──────────────────┐                          │                 │
│ signal_modulator │◄─────────────────────────┘                 │
│ (macro filter)   │   risk_score courant                       │
└──────┬───────────┘                                            │
       │                                                        │
       ▼
┌──────────────────┐
│ emit_signal      │
│ + cooling 300s   │
│ + correlation_id │
└──────────────────┘
       │
    ┌──┴──────────────────┐
    ▼                     ▼
┌──────────┐     ┌────────────────┐
│ WebSocket│     │ Telegram alert │
│ broadcast│     └────────────────┘
└──────────┘
```

## Modules

| Module | Fichier | Rôle |
|--------|---------|------|
| Signal Engine | `core/signal_engine.py` | Scan 5s, score SMC, modulation macro |
| Scoring | `core/scoring_engine.py` | 11 critères SMC avec poids adaptatifs |
| SMC Engine | `core/smc_engine.py` | OB/FVG, BOS, liquidity sweep |
| Optimizer | `engine/optimizer.py` | Walk-forward SL/TP (24h) |
| Strict Engine | `engine/strict_engine.py` | TRIX recalibration (2 jours) |
| Learning | `engine/learning_engine.py` | Poids adaptatifs + circuit breaker |
| **FUNDAMENTALS** | `fundamentals/` | **Scoring macro 0-100, modulation signaux** |
| Signal Manager | `execution/signal_manager.py` | Cooling period 300s, correlation ID |
| Risk Manager | `execution/risk_manager.py` | ATR SL/TP adaptatifs |
| Binance WS | `data/binance_ws.py` | aggTrade stream + delta volume (notionnel) |
| Gold Provider | `data/gold_provider.py` | XAU/USD via Twelve Data / Yahoo fallback |
| Futures Data | `data/futures_data.py` | OI, funding rate, mark price |
| Ollama Vision | `vision/ollama_vision.py` | LLaVA/Qwen2.5-VL analyse chart |
| API Server | `api/api_server.py` | FastAPI + lifespan (9+ tâches asyncio) |

## Module FUNDAMENTALS (nouveau)

### Score de risque (0–100)

| Plage | Niveau | Action |
|-------|--------|--------|
| 0–14  | CALM   | Signal inchangé |
| 15–34 | LOW    | Signal inchangé |
| 35–54 | MEDIUM | Réduction légère du score |
| 55–69 | HIGH   | Réduction forte du score |
| 70+   | EXTREME| Signal annulé |

### Endpoints API

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/fundamentals/score` | GET | Score courant + niveau + stats modulation |
| `/fundamentals/news` | GET | Derniers articles agrégés |
| `/fundamentals/history` | GET | Historique du score (7 jours) |
| `/fundamentals/reload` | POST | Refresh manuel immédiat |
| `/fundamentals/enable` | POST | Active le module (runtime) |
| `/fundamentals/disable` | POST | Désactive le module (runtime) |

### Configuration (.env)

```env
FUNDAMENTALS_ENABLED=1           # 0 pour désactiver complètement
FUNDAMENTALS_REFRESH_SEC=900     # Fréquence de rafraîchissement (15 min)
FUNDAMENTALS_RISK_BLOCK=70       # Score au-delà duquel le signal est annulé
FUNDAMENTALS_RISK_REDUCE=30      # Score à partir duquel la réduction commence
FUNDAMENTALS_ROLLBACK_DELTA=0.3  # Seuil de rollback automatique
NEWSAPI_KEY=your_key_here        # Optionnel (100 req/j en gratuit)
GDELT_ENABLED=1                  # GDELT gratuit, pas de clé
```

## Flux de données

```
aggTrade WS (Binance) → raw_1s[] → candle_store[sym]
                                        │
                             score_setup() [11 critères]
                                        │
                            get_macro_risk() [FUNDAMENTALS]
                                        │
                            effective_score = score × risk_factor
                                        │
                             emit_signal() [cooling 300s]
                                        │
                         ┌──────────────┴──────────────┐
                    broadcast()                  send_signal_alert()
                  (WebSocket)                    (Telegram)
```

## Boucles asyncio actives

| Tâche | Intervalle | Priorité |
|-------|-----------|---------|
| `ws_binance` (×N sym) | Continu | Critique |
| `scan_loop` | 5s | Haute |
| `fundamentals_loop` | 900s (15 min) | Moyenne |
| `optimisation_loop` | 24h | Basse |
| `strict_recalib_loop` | 2 jours | Basse |
| `learning_report_loop` | 2h | Basse |
| `circuit_breaker_loop` | 1h | Basse |
| `gold_refresh_loop` | Variable | Moyenne |
| `futures_refresh_loop` | 60s | Moyenne |
