# Conventions de code

## Style
- Python avec annotations fréquentes et `from __future__ import annotations` dans les modules inspectés.
- Fonctions et modules en `snake_case`, classes en `PascalCase`, constantes de configuration en `UPPER_SNAKE_CASE`.
- Imports : [EN ATTENTE : ordre de tri imposé — aucun outil/configuration de formatage trouvé].
- La configuration centralisée est `utils/config.py` : les autres modules ne doivent pas appeler `os.getenv()` directement.

## Patterns qu’on UTILISE
- `asyncio` pour les boucles de service FastAPI et les I/O réseau.
- `@dataclass` pour plusieurs modèles métier et résultats de guard.
- Factory/Strategy `BaseExecutor` → `PaperExecutor` ou `DisabledExecutor`.
- Fail-safe : une guard invalide ou en exception bloque le trade.
- Écritures JSON atomiques (`utils/atomic_state.py`) et journaux JSONL append-only.
- Collaboration : une tâche a un owner, un livrable vérifiable et une revue croisée ; les décisions sont tracées dans `collab/`.

## Rôles de collaboration
- **Hermes** : orchestre, synthétise les preuves et ne valide pas une permission sensible seul.
- **Claude Code** : architecture, implémentation et explication du changement.
- **Codex** : audit indépendant, tests critiques et red-team.
- **Florent** : arbitre final ; seul il valide le passage à `DONE`.

## Patterns INTERDITS
- Mode live : non implémenté, ne pas l’ajouter sans décision explicite.
- Contourner les guards ou ouvrir sans stop-loss valide.
- Accéder directement à `os.getenv()` hors de `utils/config.py`.
- Modifier l’interface `/orbe` en la remplaçant : la consigne projet impose une route séparée pour une nouvelle surface (`CLAUDE.md`).

## Tests
- Tests dans `tests/test_*.py`, exécutés avec `venv\Scripts\python.exe -m pytest tests/ -v`.
- Couvrir au minimum guards, paper trading, persistance, démarrage, contrat stratégie et route touchée.

## Commits
- Préfixes observés : `feat:`, `docs:`, `update:`, `sync:`, `merge:`, `wip:`.
- [EN ATTENTE : convention de commit obligatoire non formalisée.]