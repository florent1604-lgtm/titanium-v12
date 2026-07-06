# Titanium v12 — Design Spec
**Date :** 2026-04-05
**Statut :** Approuvé

---

## Contexte

Titanium v11 est un dashboard de signaux trading crypto (SMC — Smart Money Concepts) monolithique de 6 044 lignes, actuellement désactivé. L'objectif est de le refactoriser en architecture modulaire propre (Option B : réutilisation de la logique métier validée, sans réécriture from scratch).

---

## Décisions de périmètre

| Paramètre | Valeur |
|-----------|--------|
| Mode trading | Simulation uniquement |
| Assets | BTC/USDT + PAXG/USDT |
| Dashboard HTML | Conservé tel quel |
| Alertes Telegram | Conservées (seuil 7/11) |
| Vision IA Ollama | Conservée + bug corrigé |
| Airtable | Ignoré |

---

## Architecture — Structure des fichiers

```
v12/
├── main.py
├── requirements.txt
├── core/
│   ├── signal_engine.py
│   ├── scoring_engine.py
│   └── smc_engine.py
├── data/
│   ├── binance_ws.py
│   ├── binance_rest.py
│   ├── gold_provider.py
│   └── futures_data.py
├── indicators/
│   ├── rsi.py
│   ├── adx.py
│   └── trix.py
├── engine/
│   ├── optimizer.py
│   ├── strict_engine.py
│   └── learning_engine.py
├── execution/
│   ├── signal_manager.py
│   └── risk_manager.py
├── api/
│   ├── api_server.py
│   └── websocket.py
├── vision/
│   └── ollama_vision.py
├── notifications/
│   └── telegram.py
└── utils/
    ├── config.py
    ├── logger.py
    └── cache.py
```

---

## Principes d'architecture

- `utils/config.py` est la seule source de vérité pour toutes les variables `.env` — aucun `os.getenv()` ailleurs dans le projet
- Flux unidirectionnel : `data → indicators → smc → scoring → signal → execution`
- Zéro import circulaire : `utils` n'importe rien du projet, `data` n'importe pas `core`
- Zéro `except Exception: pass` — toutes les exceptions sont loggées ou remontent
- Tous les flags de synchronisation asyncio utilisent `asyncio.Lock()` (plus de booleans partagés)
- Broadcast WebSocket uniquement si le signal change (hash comparé)

---

## Corrections critiques

### Fix 1 — Vision IA (jamais fonctionnel en v11)
**Cause :** timeout non catchés + modèle rechargé depuis disque à chaque appel (22s)
**Correction :**
- `keep_alive=3600s` pour maintenir le modèle en RAM
- Timeout par phase : connexion 5s / génération 60s
- Retry x2 avec backoff exponentiel avant fallback texte-only
- Détection de présence Ollama au démarrage (warning propre si absent)

### Fix 2 — Walk-forward backtest (résultats surestimés 30-50%)
**Cause :** backtests entièrement in-sample, Sharpe non annualisé
**Correction :**
- Split obligatoire : 60 jours in-sample / 20 jours out-of-sample
- Sharpe annualisé `× √252` partout
- Métriques reportées = out-of-sample uniquement

### Fix 3 — Seuil Telegram trop bas
**Cause :** `TELEGRAM_SCORE_THRESHOLD=6/11` → alertes à 55% qualité
**Correction :** seuil par défaut 7/11 dans config, détail des critères dans l'alerte

### Fix 4 — Race conditions asyncio
**Cause :** flags booléens partagés sans protection
**Correction :** `asyncio.Lock()` sur toutes les ressources partagées

---

## Flux de données temps réel

```
binance_ws.py (aggTrade BTC/PAXG)
gold_provider.py (Twelve Data / Yahoo)
futures_data.py (OI + Funding, TTL 60s)
        │
        ▼
signal_engine.py (toutes les 5s)
  → binance_rest.py → klines [cache TTL]
  → rsi.py + adx.py + trix.py
  → smc_engine.py (OB/FVG/BOS/Sweep/Breaker)
  → scoring_engine.py (score /11 + régime)
        │
   score ≥ 7/11 ?
        │
   signal_manager.py + risk_manager.py (SL/TP ATR)
        │
   websocket.py (broadcast si changement)
   telegram.py (alerte)
```

## Boucles arrière-plan

| Tâche | Intervalle | Module |
|-------|-----------|--------|
| Scan signaux | 5s | signal_engine |
| Recalibration STRICT TRIX | 2 jours | strict_engine |
| Optimisation SL/TP | 24h | optimizer |
| Adaptation poids | 2h | learning_engine |
| Circuit breaker | 1h | risk_manager |
| Refresh Gold | 3min | gold_provider |

---

## Détection de régime marché

Trois régimes détectés par `adx.py` + `scoring_engine.py` :
- **TREND** : ADX ≥ 27 — favorise continuations FVG
- **RANGE** : ADX < 20 — favorise rebonds OB intact
- **VOLATILE** : ATR spike + ADX instable — réduction du score minimum requis

---

## Lancement

```bash
cd C:\Users\flore\Desktop\TITANIUM\Titanium\v12
pip install -r requirements.txt
python main.py
```

Dashboard disponible sur `http://localhost:8080`
