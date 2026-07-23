# Architecture

## En une phrase
Titanium v12 est une application Python qui collecte des données de marché, calcule des signaux, les filtre puis les exécute **uniquement en simulation** ou les diffuse par API/alertes.

## Stack
- **Langage / runtime :** Python ; environnement projet `venv\Scripts\python.exe` (`CLAUDE.md`).
- **Framework principal :** FastAPI + Uvicorn (`requirements.txt`, `api/api_server.py`).
- **Données persistées :** états largement en mémoire, avec fichiers JSON, CSV et JSONL sous `data/` ; [EN ATTENTE : schéma global de persistance].
- **Services externes :** Binance REST/WebSocket, Twelve Data/Yahoo, NewsAPI/GDELT/RSS ; MT5 est déclaré data-only (`utils/config.py`, `data/`).

## Carte des dossiers
- `api/` → routes FastAPI, WebSocket, auth et surfaces dashboard.
- `core/` → orchestration des scans et moteurs crypto/forex/swing.
- `data/` → flux/caches marché, providers et états runtime.
- `execution/` → exécuteur paper, guards, journal et gestion des signaux.
- `engine/`, `indicators/`, `fundamentals/` → optimisation, scoring technique et filtre macro.
- `domain/`, `validation/` → modèles/décision stratégie et validation statistique.
- `assistant/`, `vision/` → Titan/JARVIS et analyse Ollama.
- `tests/` → tests pytest ; `tools/` → outils de validation/opération.
- `collab/` → source de vérité de collaboration : tâches, décisions, revues et pont Hermes/Claude/Codex.

## Orchestration humaine et agents
Florent arbitre et valide. Hermes coordonne, conserve le contexte et synthétise. Claude Code conçoit/implémente ; Codex réalise la revue indépendante/red-team. Les tâches, preuves et verdicts passent par `collab/TASKS.md`, `collab/LOG.md` et `collab/REVIEWS.md` (`collab/README.md`).

## Flux de données
Market feeds → stores/candles → `core/signal_engine.scan_symbol()` → scoring et niveaux SL/TP → modulation macro → `emit_signal()` → WebSocket/alertes → `PaperExecutor` et journal, si les guards passent.

## Ce qui N'EXISTE PAS (et ne doit pas être créé)
- Pas d’exécuteur live : `TRADING_MODE=live` lève une erreur (`execution/executor.py`).
- Pas d’ORM ni de base de données déclarée dans les dépendances.
- Pas de CI/CD ou workflow de déploiement versionné (`.github/workflows` absent).