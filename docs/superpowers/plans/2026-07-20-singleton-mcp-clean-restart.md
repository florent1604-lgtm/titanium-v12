# Plan d'implementation — MCP singleton, flux directs et relance propre

> Statut : HOLD avant intervention runtime, en attente de l'ACK Claude sur le bus
> Garde-fous : PAPER/DEMO ONLY ; compte reel 60261188 interdit ; DEMO 50061786 fail-closed

## Objectif

Supprimer Base44 et les serveurs MCP dupliques, corriger les incoherences de vitalite
observees, migrer Claude/Codex/Hermes vers des endpoints loopback singleton, purger
uniquement les caches regenerables, reindexer la carte puis effectuer une relance
ordonnee et verifiable.

## Conditions d'entree

1. ACK Claude `GO` ou demandes de changement consignees dans le bus.
2. Aucun fichier en cours de modification par Claude dans le lot ci-dessous.
3. Snapshot MT5 : compte 50061786 confirme, aucune position ouverte ; sinon ABORT.
4. EventPlane : integrite OK ; sauvegarde logique disponible ; aucune purge de `data/`.
5. GitNexus : index lisible ou mode degrade explicitement consigne.

## Lot A — Tests de regression avant correction

### A1. Cortex et contrats de sante

Fichiers :

- `tests/test_cortex.py`
- `core/cortex.py`

Ajouter des tests qui imposent :

- consensus lu depuis `heartbeat` + `symbols` ;
- un heartbeat sans `last_cycle_at` reste `cold` ;
- EventPlane sans preuve d'integrite est `unknown`, jamais `ok` par defaut ;
- `overall_health` propage `down`, `stale`, `cold`, `corrupt` et `unknown`.

Avant edition de `_summarize` et `_eventplane` : impact GitNexus upstream obligatoire.
Risque attendu : LOW, mais le dashboard et Hermes dependent de cette projection.

### A2. Univers Axi ROW_*

Fichiers :

- `tests/test_asset_optimizer.py` ou nouveau test cible
- `tests/test_opportunity_scan_state.py`
- `tools/asset_optimizer.py`
- `core/opportunity_scan.py`

Ajouter des tests pour `ROW_STANDARD_FX`, `ROW_CRYPTO`, `ROW_FUTURES`, `ROW_CASH`,
`ROW_STANDARD_METALS` et un invariant fail-visible : un univers vide ne peut pas etre
publie comme scan reussi.

Avant edition de `list_universe` et de la fonction de cycle : impact upstream obligatoire.

### A3. Schema JSON consensus sans collision

Fichiers :

- `tests/test_consensus_engine.py`
- `core/consensus_engine.py`
- `api/consensus_routes.py`

Ajouter un test recursif garantissant l'absence de deux cles identiques a la casse pres.
Separer le contexte brut du scoring et les criteres booleens dans des sous-objets stables
au lieu de les fusionner. Conserver `decision_capability=false`, `orders_capability=false`.

Avant edition de `_run_scoring`, `_scan_one` ou `status_snapshot` : impact upstream.

### A4. Contrat decisionnel pre-M2

Fichiers :

- `tests/test_brain_gate.py`
- `core/brain_gate.py`
- `core/confluence_demo_engine.py`

Ce lot est RISQUE ELEVE car il touche la selection/taille DEMO. Il reste bloque tant que
Claude n'a pas confirme le protocole M2. Test cible : les observations consensus/emotion
restent visibles dans Cortex/EventPlane mais ne bloquent, n'autorisent et ne dimensionnent
aucun ordre quand `decision_capability=false`.

Le lot A4 ne sera pas necessaire a la relance technique si la revue M2 n'est pas rendue :
le moteur DEMO restera desarme plutot que d'appliquer une correction non revue.

## Lot B — Retrait complet de Base44 actif

Fichiers actifs a retirer ou modifier :

- `.mcp.json`
- `.codex/config.toml`
- `api/api_server.py`
- `api/base44_routes.py`
- `core/base44_client.py`
- `core/base44_push.py`
- `mcp_base44.py`
- `utils/config.py`
- `tests/test_mutation_auth.py`
- dashboards/frontends contenant encore des appels `/base44/*`

Procedure test-first :

1. Ajouter un test de contrat qui interdit `base44` dans les configurations MCP, routes
   FastAPI, variables runtime et appels frontend.
2. Executer le test et constater l'echec.
3. Retirer l'import, le task lifespan, le router et les configurations.
4. Supprimer uniquement les modules Base44 actifs ; conserver les mentions historiques
   dans `docs/`, `collab/` et archives.
5. Reexecuter les tests startup, mutation-auth et dashboard.

Impact obligatoire sur `lifespan` et la composition FastAPI avant edition.

## Lot C — Transport MCP singleton et connexions directes

### C1. GitNexus

- Endpoint canonique : `http://127.0.0.1:4747/api/mcp`.
- Un seul watcher `tools/gitnexus_runtime.py watch` protege par mutex.
- Claude et Codex : HTTP natif read-only.
- Hermes : client HTTP direct ; aucun `command` Python/Node intermediaire.
- Ecriture `rename/group_sync` reste derriere approbation signee d'un superviseur.

Tests : un listener 4747, un watcher, zero enfant `server.mjs` par client, lecture MCP
OK, outil d'ecriture absent/refuse sans approbation.

### C2. Titanium Control MCP

- Creer un serveur Streamable HTTP singleton loopback sur `127.0.0.1:8091/mcp`.
- Exposer d'abord le catalogue lecture seule.
- Ne pas exposer les mutations avant authentification locale et fermeture Section 7.
- Remplacer les configurations `command = python ...mcp_server.py` par `url = ...`.

Fichiers probables :

- `mcp_server.py`
- nouveau `tools/titanium_mcp_http.py` si la separation transporte mieux le serveur
- `.mcp.json`
- `.codex/config.toml`
- configuration utilisateur Codex
- configuration Hermes
- tests MCP/configuration

Impact obligatoire sur chaque symbole transporte ou registre d'outils.

### C3. Hermes/JARVIS

Le WS JARVIS `8765` reste vivant. Ne pas greffer un protocole HTTP incompatible sur le
meme listener. Claude doit choisir avant implementation entre :

- monter `/mcp` dans le serveur HTTP JARVIS existant si le framework le permet ; ou
- reserver un listener MCP Hermes distinct et singleton, documente dans la spec.

Dans les deux cas : aucun `hermes mcp serve` stdio par session ; outils sensibles masques
ou authentifies ; `permissions_respond` jamais automatique.

## Lot D — Nettoyage controle et reindexation

### D1. Arret ordonne

1. Desarmer DEMO et verifier compte/positions.
2. Arreter les boucles d'execution Titanium par leur mecanisme gracieux.
3. Arreter les services MCP geres, puis JARVIS/Titanium selon dependances.
4. Identifier les PID par commande ET chemin executable ; jamais de kill global
   `python`/`node`.
5. Fermer seulement les anciens shells/lanceurs dont le processus enfant est absent.

### D2. Purge autorisee

Supprimer seulement :

- `__pycache__/`, `.pytest_cache/`, caches Vite temporaires ;
- locks/PID temporaires prouves orphelins ;
- caches GitNexus regenerables via la commande officielle `clean`/`analyze` ;
- sorties temporaires explicitement classees non probantes.

Ne jamais supprimer : `.env`, secrets, EventPlane, journaux DEMO/PAPER, etats de compte,
calibrations, memoires Hermes, documents de collaboration, backups ACL.

### D3. Reindexation

1. Reindex Titanium avec `node .gitnexus/run.cjs analyze` en exclusion des caches/data.
2. Reindex JARVIS dans son depot/snapshot canonique.
3. Construire un snapshot Hermes expurge de secrets et chemins personnels.
4. Synchroniser le groupe `titanium-neural` et verifier les trois composantes.
5. Tester BM25, graphe, processus et impact sur un symbole connu de chaque composante.

## Lot E — Relance propre et recette

Ordre : GitNexus -> EventPlane/Titanium data plane -> Titanium API -> Titanium MCP ->
JARVIS/Hermes -> dashboards -> DEMO desarme.

Recette minimale :

- exactement un listener par port prevu ;
- aucun processus `mcp_base44.py` ni route `/base44/*` ;
- aucun enfant stdio GitNexus/Titanium/Hermes apres redemarrage des clients ;
- `/cortex` ne signale plus de faux `cold` ;
- univers opportunity non vide et categories ROW_* presentes ;
- schema consensus sans collision de casse ;
- EventPlane integrite OK, compteur d'echecs sans delta ;
- GitNexus frais et requetes cross-composants valides ;
- JARVIS dialogue disponible ;
- compte reel 60261188 non touche ;
- DEMO 50061786 reste desarme jusqu'au GO explicite post-recette.

## Commandes de verification finales

```powershell
python -m pytest tests/test_cortex.py tests/test_consensus_engine.py tests/test_opportunity_scan_state.py -q
python -m pytest tests/test_main_startup.py tests/test_mutation_auth.py tests/test_hermes_bridge_config.py -q
node .gitnexus/run.cjs status
node tools/collab_bus.mjs tail --limit 20
```

Puis `detect_changes(scope=compare, base_ref=master)` ou son fallback CLI/statique si le
MCP est indisponible. Aucun commit runtime sans revue du rayon d'impact.

