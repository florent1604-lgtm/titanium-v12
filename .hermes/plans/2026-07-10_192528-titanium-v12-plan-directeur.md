# Titanium V12 — Plan directeur de transformation

> **Pour Hermes :** exécuter ce plan tâche par tâche, avec TDD, analyse d’impact GitNexus lorsqu’elle est disponible, revue de conformité puis revue de qualité. Ne jamais activer d’exécution réelle sans une demande distincte et explicite de Florent.

**Objectif :** transformer Titanium en une plateforme locale, traçable et sûre de **swing trading H4 en PAPER ONLY**, capable de produire des intentions déterministes, de simuler leur exécution avec des coûts réalistes, de mesurer les résultats sans surapprentissage et de servir une vue cohérente à Titanium Nexus et JARVIS.

**Architecture cible :** données MT5 clôturées → règles swing pures et versionnées → intention unique par actif/barre → service de risque portefeuille unique → broker paper unique → journal append-only → snapshot API V1 → dashboard/JARVIS/backtest. Le backtest et le forward paper doivent utiliser les mêmes règles et le même modèle de coûts.

**Stack actuelle :** Python 3.12, FastAPI, asyncio, pandas/numpy/scipy/pandas-ta, MetaTrader5 en lecture seule, JSON/CSV, WebSocket, HTML/JS, pytest. Projet canonique : `C:\Users\flore\Desktop\v12`. API locale attendue : port 8090 via `.env`, sans jamais lire ni afficher les secrets.

---

## 1. État réel observé le 10 juillet 2026

### Points solides déjà présents

- `domain/models.py` et `domain/strategy.py` amorcent un contrat de stratégie pure.
- `docs/STRATEGY_CONTRACT.md` définit correctement la convention temporelle `t → t+1`.
- `validation/harness.py` apporte trois segments, bootstrap, PBO, Deflated Sharpe et statuts de validation.
- `api/auth.py` applique une authentification fail-closed par `X-Admin-Token`.
- `utils/config.py` lie désormais l’hôte par défaut à `127.0.0.1` et désactive par défaut les moteurs forex, swing et opportunités.
- `core/portfolio_risk.py` ajoute des plafonds stratégie/cluster/gross.
- `core/swing_engine.py` travaille sur la barre clôturée, possède un anti-réentrée par `bar_ts` et utilise une sauvegarde atomique.
- USTECH et NAS100.fs disposent des meilleures preuves MT5 natives disponibles ; HSI.fs reste une observation. Cela n’établit aucune rentabilité future.

### Blocages actuels

1. **Arbre Git non stabilisé :** 24 fichiers suivis modifiés et 72 entrées non suivies. Les fichiers d’état runtime représentent une grande partie du diff.
2. **Suite de tests rouge :** exécution réelle observée : `100 passed, 29 failed`.
   - 11 échecs MCP : `pydantic_core._pydantic_core` manquant / environnement mélangé.
   - 18 échecs paper trading : helper de test basé sur `asyncio.get_event_loop()` incompatible avec l’état actuel de Python 3.12.
3. **Architecture encore fragmentée :** paper crypto, forex et swing gardent des comptes/moteurs distincts.
4. **Risque partiellement centralisé seulement :** `core/portfolio_risk.py` lit directement les états globaux des moteurs et calcule encore des plafonds à partir de capitaux séparés.
5. **Sizing swing simplifié :** `risk / distance relative`, sans `tick_value`, `contract_size`, marge, conversion de devise ni `order_calc_profit` injecté.
6. **Coûts swing incomplets :** le moteur swing ne comptabilise pas encore explicitement commission, slippage, spread, swap et rollover dans chaque fill.
7. **Univers non gelé :** `data/asset_configs.json` contient de nombreux actifs, dont des actifs H1/intraday ou rejetés ; les auto-configurations peuvent toujours être chargées si le fichier existe.
8. **Documentation divergente :** README et architecture décrivent encore le produit crypto/SMC historique et parfois le port 8080 ; le système réel vise 8090 et la cible recommandée est swing-only.
9. **Backtest non encore branché sur le même broker/règles que le forward paper.**
10. **Dashboard monolithique et hybride :** il mélange signaux crypto, services, Git, JARVIS, paper et diagnostics.

---

## 2. Principes non négociables

- **PAPER ONLY** à tous les niveaux : configuration, domaine, runtime, API, UI et intégration JARVIS.
- MT5 reste **data-only**. Aucun `order_send`, aucune clé, aucun ordre réel.
- Les décisions sont exclusivement **H4 sur barre clôturée**, avec biais D1/H4.
- Une intention maximum par `(strategy_version, symbol, bar_id)`.
- Entrée au premier prix exécutable de `t+1`, jamais au close ayant servi à décider.
- Absence ou obsolescence de données, coût, calendrier ou métadonnées instrument → `NO_TRADE/BLOCKED`.
- Les métriques doivent être nettes de coûts et accompagnées de provenance, taille d’échantillon et statut de preuve.
- Aucun résultat de backtest ne déclenche automatiquement un changement de paramètres, d’univers ou de runtime.
- Aucun affichage ne doit qualifier Titanium de « rentable » ; statuts autorisés : `UNVALIDATED`, `INSUFFICIENT_EVIDENCE`, `OBSERVATION`, `FORWARD_PAPER`, `BLOCKED`, `REJECTED`.

---

# Phase 0 — Sauvegarder et stabiliser le chantier

## Tâche 0.1 — Inventorier le travail existant sans l’écraser

**Fichiers :**
- Créer : `docs/WORKTREE_BASELINE_2026-07-10.md`
- Modifier : `.gitignore`

**Étapes :**
1. Capturer `git status --short`, `git diff --stat` et la liste des fichiers non suivis pertinents.
2. Classer chaque changement : code source, test, documentation, état runtime, rapport, cache/outillage.
3. Ajouter à `.gitignore` les logs, caches, captures et états régénérables qui ne doivent pas polluer Git.
4. Ne supprimer, restaurer, commit ou pousser aucun fichier sans validation de Florent.
5. Définir de petits lots de commits futurs : sécurité, domaine, validation, UI, documentation.

**Validation :** aucun fichier métier perdu ; le baseline permet de reconstruire précisément ce qui existait avant la refonte.

## Tâche 0.2 — Séparer configuration, code et données runtime

**Fichiers :**
- Modifier : `.gitignore`
- Créer : `data/runtime/.gitkeep`
- Créer : `data/fixtures/README.md`
- Modifier : chemins d’état dans `utils/config.py` après analyse d’impact

**Étapes :**
1. Déplacer progressivement les états mutables vers `data/runtime/`.
2. Garder les fixtures déterministes sous `tests/fixtures/` ou `data/fixtures/`.
3. Garder les rapports versionnés sous `data/backtests/<run_id>/` seulement lorsqu’ils portent provenance et hash.
4. Prévoir une migration non destructive des JSON actuels.

**Validation :** un démarrage/test ne modifie plus des fichiers suivis sans raison.

---

# Phase 1 — Réparer l’environnement et obtenir une base verte

## Tâche 1.1 — Verrouiller les dépendances Python

**Fichiers :**
- Modifier : `requirements.txt`
- Créer : `requirements-dev.txt`
- Créer : `pyproject.toml`
- Créer : `docs/ENVIRONMENT.md`

**Étapes :**
1. Documenter la version exacte de Python réellement utilisée par `venv\Scripts\python.exe`.
2. Diagnostiquer pourquoi le venv du projet importe `mcp`, `pydantic` ou `pydantic_core` depuis le venv Hermes.
3. Créer/recréer un venv isolé sans héritage de `PYTHONPATH` ni site-packages externe.
4. Pinner des versions compatibles de FastAPI, Pydantic, pydantic-core, MCP, pytest et pytest-asyncio.
5. Ajouter une commande de bootstrap reproductible Windows/Git-Bash.

**Tests :**
```bash
./venv/Scripts/python.exe -c "import sys; print(sys.executable); import pydantic_core; print(pydantic_core.__file__)"
./venv/Scripts/python.exe -c "from api.api_server import app; print(len(app.routes))"
```

**Critère de sortie :** aucune dépendance du projet n’est chargée depuis `AppData/Local/hermes/hermes-agent/venv`.

## Tâche 1.2 — Corriger les tests async Python 3.12

**Fichiers :**
- Modifier : `tests/test_paper_trading.py`
- Modifier : `pytest.ini`
- Éventuellement créer : `tests/conftest.py`

**Étapes TDD :**
1. Remplacer le helper `asyncio.get_event_loop().run_until_complete()` par `pytest.mark.asyncio` ou `asyncio.run()` selon le cas.
2. Garantir qu’aucune coroutine non awaitée ne subsiste.
3. Isoler les fichiers d’état dans `tmp_path` pour éviter les mutations de données réelles pendant les tests.
4. Exécuter le module paper seul, puis la suite complète.

**Commandes :**
```bash
./venv/Scripts/python.exe -m pytest tests/test_paper_trading.py -q
./venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -q
./venv/Scripts/python.exe -m pytest tests/ -q
```

**Critère de sortie :** `0 failed`, `0 coroutine was never awaited`.

## Tâche 1.3 — Ajouter les contrôles qualité minimaux

**Fichiers :**
- Modifier : `pyproject.toml`
- Créer : `.github/workflows/tests.yml` si GitHub Actions est souhaité

**Contrôles :** Ruff/format, mypy progressif sur `domain/`, `python -m compileall`, pytest et `git diff --check`.

---

# Phase 2 — Geler la politique swing et l’univers

## Tâche 2.1 — Créer l’univers swing versionné

**Fichiers :**
- Créer : `config/swing_universe.json`
- Créer : `domain/universe.py`
- Créer : `tests/test_swing_universe.py`

**Contenu attendu :**
- USTECH : `FORWARD_PAPER`, H4, cluster `US_INDICES`.
- NAS100.fs : `FORWARD_PAPER`, H4, cluster `US_INDICES`.
- HSI.fs : `OBSERVATION`, non ouvrable automatiquement.
- XAUUSD : `REJECTED` avec preuve MT5 PF 0,90.
- Tous les autres : `DISABLED` ou absents donc refusés.

Chaque entrée contient : `enabled`, `status`, `cluster`, `timeframe`, règles, coût, `evidence_source`, `evidence_period`, `evidence_status`, `reason`, `config_version`.

**Tests rouges puis verts :**
- un actif absent est refusé ;
- un actif non H4 est refusé ;
- `OBSERVATION` n’ouvre pas automatiquement ;
- seuls USTECH/NAS100.fs peuvent atteindre l’étape de risque.

## Tâche 2.2 — Externaliser la politique de risque

**Fichiers :**
- Créer : `config/risk_policy.json`
- Créer : `domain/risk_policy.py`
- Créer : `tests/test_risk_policy.py`

**Limites initiales prudentes :**
- `risk_per_trade_pct: 0.25`
- `max_open_positions: 2`
- `max_gross_exposure_pct: 0.50`
- `max_cluster_initial_risk_pct: 0.50`
- `daily_loss_limit_pct: 1.00`
- `max_drawdown_kill_switch_pct: 5.00`

Ces valeurs sont des limites de sécurité paper et ne doivent pas être optimisées pour améliorer un backtest.

---

# Phase 3 — Finaliser le domaine pur et les contrats

## Tâche 3.1 — Consolider les modèles immuables

**Fichiers :**
- Modifier : `domain/models.py`
- Créer : `tests/test_domain_models.py`

**Modèles :** `ClosedBar`, `MarketSnapshotAtClose`, `InstrumentMetadata`, `TradeIntent`, `Position`, `Fill`, `CostBreakdown`, `PortfolioSnapshot`, `AuditEvent`, `TitaniumSnapshotV1`.

**Règles :** unités explicites, timezone UTC, validation `is_closed`, `source_ts`, `bar_id`, schéma versionné, sérialisation stable.

## Tâche 3.2 — Finaliser la règle swing pure

**Fichiers :**
- Renommer/migrer : `domain/strategy.py` → `domain/swing_rules.py`
- Modifier : `tests/test_strategy_contract.py`
- Créer : `tests/fixtures/swing_bars.json`

**Signature :**
```python
evaluate_closed_bar(history, portfolio, strategy_config, cost_model, context) -> TradeIntent
```

**Tests :** déterminisme, barre ouverte, stale, historique insuffisant, H4 obligatoire, signal à `t`, exécution à `t+1`, `config_hash`, `strategy_version`, position déjà ouverte, intention dupliquée.

## Tâche 3.3 — Créer un registre d’idempotence

**Fichiers :**
- Créer : `domain/intent_registry.py`
- Créer : `tests/test_intent_registry.py`

**Clé :** `(strategy_version, symbol, decision_bar_id)` ; journalisation du premier résultat, refus explicite des doublons, restauration après redémarrage.

---

# Phase 4 — Construire le portefeuille et le broker paper uniques

## Tâche 4.1 — Remplacer le risque couplé aux globals

**Fichiers :**
- Créer : `domain/portfolio_risk.py`
- Migrer depuis : `core/portfolio_risk.py`
- Créer : `tests/test_unified_portfolio_risk.py`

**API :** `PortfolioRiskService.check(intent, portfolio, market, policy) -> RiskDecision`.

**Tests :** nombre max de positions, gross après ajout, cluster US indices, risque initial agrégé, perte journalière, DD kill-switch, stale data/calendrier/coût, cash/marge insuffisants.

## Tâche 4.2 — Sizing fondé sur les métadonnées MT5

**Fichiers :**
- Créer : `domain/sizing.py`
- Modifier : `data/mt5_provider.py`
- Créer : `tests/test_mt5_sizing.py`

**Données :** `contract_size`, `tick_size`, `tick_value`, `volume_min/max/step`, devise de profit, marge, conversion vers EUR. Injecter un adaptateur mockable autour de `order_calc_profit` ; aucune formule notionnelle approximative comme source d’autorité.

## Tâche 4.3 — Implémenter le broker paper unique

**Fichiers :**
- Créer : `domain/paper_broker.py`
- Créer : `domain/costs.py`
- Créer : `tests/test_paper_broker_parity.py`

**Comportements :** bid/ask, slippage signé, commission, spread, swap/rollover, arrondis instrument, TP partiels, break-even, SL, time-stop, convention pessimiste si SL/TP touchés dans la même barre.

**Critère central :** même fixture → mêmes fills, coûts et PnL dans le broker forward et le backtest.

## Tâche 4.4 — Journal append-only et état reconstructible

**Fichiers :**
- Créer : `domain/repositories.py`
- Créer : `data/runtime/audit_events.jsonl` au runtime seulement
- Créer : `tests/test_event_replay.py`

**Tests :** écriture atomique, crash simulé, détection de ligne corrompue, replay donnant exactement le même `PortfolioSnapshot`, version de schéma et migration.

---

# Phase 5 — Adapter le moteur live-paper swing

## Tâche 5.1 — Créer l’orchestrateur swing V2

**Fichiers :**
- Créer : `core/swing_orchestrator.py`
- Modifier : `api/api_server.py`
- Créer : `tests/test_swing_orchestrator.py`

**Flux :** récupérer barres clôturées → construire snapshot canonique → règles pures → idempotence → risque → broker paper → journal → snapshot.

**Garde-fous :** une seule instance écrivain, aucune entrée si MT5/tick/calendrier/coût stale, pas d’auto-ajout d’actif.

## Tâche 5.2 — Retirer les moteurs legacy du chemin actif

**Fichiers :**
- Modifier : `api/api_server.py`
- Modifier : `utils/config.py`
- Documenter : `docs/LEGACY_COMPONENTS.md`

**Composants désactivés du runtime produit :** `core/signal_engine.py`, `core/forex_engine.py`, `core/opportunity_scan.py`, optimiseurs crypto/strict/learning pour les décisions. Les conserver temporairement en lecture/recherche si nécessaire, sans démarrage automatique ni route visible.

**Tests :** le lifespan par défaut ne lance que les providers nécessaires, l’orchestrateur swing, le snapshot et les diagnostics.

---

# Phase 6 — Backtest identique et validation défendable

## Tâche 6.1 — Construire le moteur d’événements

**Fichiers :**
- Créer : `backtest/engine.py`
- Créer : `backtest/provenance.py`
- Créer : `tests/test_backtest_timing.py`

**Tests :** entrée à `t+1`, jamais au close `t`; no-lookahead ; ordre stable des événements ; convention intrabar pessimiste ; marché fermé/gap ; coûts et rollover.

## Tâche 6.2 — Réutiliser exactement règles et broker

**Fichiers :**
- Créer : `backtest/adapters.py`
- Modifier : `domain/paper_broker.py`
- Créer : `tests/test_live_backtest_parity.py`

**Golden fixtures :** TP1→BE→SL, cascade TP, gap au-delà du SL, time-stop, swap sur plusieurs jours, rejet de risque cluster.

## Tâche 6.3 — Brancher le harnais de validation

**Fichiers :**
- Modifier : `validation/harness.py`
- Créer : `backtest/validation_gate.py`
- Créer : `tests/test_validation_end_to_end.py`

**Seuils :** final verrouillé, au moins 30 trades, PF ≥ 1,20, expectancy nette positive, borne bootstrap basse non négative, DD conforme, PBO/DSR documentés, absence de divergence défavorable avec MT5 natif.

**Sorties :** `data/backtests/<run_id>/manifest.json`, `trades.jsonl`, `metrics.json`, `report.md`, hashes dataset/code/config/cost model.

---

# Phase 7 — API V1 sûre et contrat JARVIS

## Tâche 7.1 — Exposer un snapshot unique

**Fichiers :**
- Créer : `api/schemas.py`
- Créer : `api/swing_v2_routes.py`
- Créer : `docs/contracts/titanium_snapshot_v1.json`
- Créer : `tests/test_snapshot_contract.py`

**Endpoints :**
- `GET /api/v1/snapshot`
- `WS /api/v1/stream` facultatif pour deltas versionnés
- diagnostics lecture seule séparés

Toutes les valeurs sensibles portent source, timestamp, fraîcheur et unité. Réponses dynamiques : `Cache-Control: no-store`.

## Tâche 7.2 — Réduire la surface de mutation

**Fichiers :**
- Modifier/supprimer routes concernées dans `api/services_routes.py`, `api/paper_routes.py`, `api/webhook_routes.py`, `api/opportunity_routes.py`
- Modifier : `api/auth.py`
- Créer : `tests/test_api_security_surface.py`

**Objectif :** supprimer le push Git et les contrôles de processus du web ; toute mutation conservée répond fail-closed sans token. Le webhook TradingView est désactivé par défaut et ne peut, au maximum, que créer une intention `STAGED` authentifiée et anti-rejeu.

## Tâche 7.3 — Migrer JARVIS

**Périmètre externe à modifier seulement après validation explicite :** `C:\Program Files\JARVIS`.

**Travail :** URL unique via environnement, consommation de `TitaniumSnapshotV1`, fraîcheur appliquée, unités correctes, retrait de close-all, compilation de `jarvis_agent.py`, test de contrat partagé.

---

# Phase 8 — Titanium Nexus — Swing Desk

## Tâche 8.1 — Choisir une source frontend unique

**Fichiers :**
- Canonique : `titanium_unified.html` ou nouveau `frontend/`
- Généré/déployé : `titanium_v12_dashboard.html`
- Tests : `tests/ui/`

Décider entre HTML modulaire sans build ou Vite/TypeScript. Éviter la coexistence de plusieurs dashboards édités manuellement.

## Tâche 8.2 — Construire les cinq vues

1. **Desk :** mode PAPER ONLY, fraîcheur MT5, dernière clôture H4, equity, cash, DD, risque cluster.
2. **Décisions :** intentions H4, `bar_id`, coût, risque, preuve, motif de blocage.
3. **Evidence :** période, hash, trades, PF, DD, expectancy, intervalle, statut.
4. **Journal :** événements append-only et refus.
5. **Diagnostics :** santé providers, snapshot, JARVIS ; aucun bouton Git/processus/ordre.

## Tâche 8.3 — Fiabiliser le flux UI

Une source principale `/api/v1/snapshot`, un seul WebSocket, fallback REST ≤ toutes les 15 s, `AbortController`, protection des réponses hors ordre, aucun polling concurrent, affichage systématique `WARMING_UP/STALE/BLOCKED/UNVALIDATED`.

## Tâche 8.4 — Tester l’interface

**Cas :** desktop, tablette, aucune position, position ouverte, donnée stale, risque bloqué, décision H4, navigation clavier, contraste, reduced-motion, absence de bouton dangereux et absence de signal intraday.

---

# Phase 9 — Observabilité et exploitation locale

## Tâche 9.1 — Journaliser la santé sans secrets

**Fichiers :**
- Modifier : `utils/logger.py`
- Créer : `core/health.py`
- Créer : `tests/test_health_snapshot.py`

Métriques : âge des données, dernière barre H4, latence MT5, erreurs provider, intents/rejets/fills, état du kill-switch, version code/config/snapshot. Aucun token ou clé dans logs/réponses.

## Tâche 9.2 — Créer des runbooks

**Fichiers :**
- Créer : `docs/RUNBOOK_START_STOP.md`
- Créer : `docs/RUNBOOK_INCIDENT.md`
- Créer : `docs/RUNBOOK_DATA_STALE.md`
- Mettre à jour : `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/COMMANDES.txt`

Documenter le port 8090, l’usage du venv, le redémarrage requis pour le code serveur, les migrations d’état et le diagnostic JARVIS.

---

# Phase 10 — Programme de forward paper

## Tâche 10.1 — Lancer en mode observation contrôlée

- USTECH et NAS100.fs passent par le même cluster ; le service de risque peut n’en autoriser qu’un selon la politique.
- HSI.fs reste observation et ne crée pas d’ouverture automatique.
- Zéro autre actif.
- Aucune adaptation online des poids/règles pendant la période de preuve.

## Tâche 10.2 — Collecter des preuves comparables

Pour chaque décision/fill : règle/version, bar_id, timestamps, bid/ask, spread, slippage, commission, swap, refus, durée, MAE/MFE, résultat net et provenance.

## Tâche 10.3 — Revue périodique

Après le seuil le plus long entre **12 semaines** et **30 sorties forward** : comparer distributions attendues/réelles, coûts, taux TP/SL, DD, incidents et violations de limites. Toute modification de règle redémarre une nouvelle cohorte versionnée ; elle ne réécrit pas l’historique.

---

# Phase 11 — Porte éventuelle vers une démo, pas vers le réel

Aucune implémentation d’ordre réel dans ce plan. Une phase distincte ne pourra être ouverte que si Florent la demande explicitement après :

- suite de tests verte et CI reproductible ;
- audit sécurité indépendant ;
- preuve forward suffisante ;
- zéro violation de risque/données ;
- réconciliation avec tester MT5 natif ;
- kill-switch, limites journalières, garde spread et confirmation humaine ;
- test sur **compte DEMO dédié**, jamais directement sur le compte live Axi.

---

## Ordre d’exécution recommandé

| Priorité | Lot | Résultat attendu |
|---|---|---|
| P0 | Phases 0–1 | Travail sauvegardé, venv isolé, 129/129 tests verts ou inventaire exact actualisé |
| P0 | Phases 2–4 | Univers gelé, domaine pur, portefeuille/broker uniques et sûrs |
| P1 | Phases 5–6 | Un seul moteur swing actif, parité backtest/paper prouvée |
| P1 | Phase 7 | Snapshot V1 et surface API minimale/sécurisée |
| P2 | Phase 8 | Titanium Nexus lisible, cohérent et sans actions dangereuses |
| P2 | Phase 9 | Exploitation et diagnostic reproductibles |
| Long terme | Phase 10 | Forward paper mesuré sur une cohorte figée |
| Hors périmètre | Phase 11 | Éventuelle démo uniquement après nouvelle décision |

---

## Vérification finale de chaque lot

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -m pytest tests/ -q
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -m compileall -q api core domain backtest validation execution data
./venv/Scripts/python.exe -c "from api.api_server import app; print(f'{len(app.routes)} routes')"
git diff --check
git status --short
```

Avant toute modification d’un symbole, lancer l’analyse d’impact GitNexus si disponible. Avant tout commit futur, lancer la détection des changements GitNexus, vérifier l’absence de secrets, examiner chaque fichier d’état et obtenir l’accord de Florent sur le périmètre du commit.

## Définition globale de « terminé »

- Un seul chemin métier actif : H4 swing, PAPER ONLY.
- Une seule source de vérité pour les règles, le portefeuille, les coûts et les snapshots.
- Même intention/fill/PnL entre replay, backtest et forward paper sur les fixtures de référence.
- Suite de tests verte et environnement reproductible.
- UI et JARVIS lisent le même contrat versionné et respectent la fraîcheur.
- Univers et règles ne changent jamais automatiquement.
- Aucun ordre réel, aucune route dangereuse, aucun secret dans le code ou le frontend.
- Les résultats sont présentés comme preuves limitées avec incertitude, jamais comme promesse de rendement.
