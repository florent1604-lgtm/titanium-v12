# GitNexus comme couche commune d’intelligence Titanium

Date : 2026-07-11  
Statut : architecture validée et arbitrée par Florent ; P0/P1 de la revue Claude intégrés ; revue finale Claude/Hermes requise avant production

## 1. Objectif

GitNexus devient la cartographie commune utilisée avant toute analyse, correction,
refactorisation ou transformation de Titanium. Florent l’utilise via l’interface
locale ; Claude, Codex et Hermes utilisent le même registre par MCP ou, si un
client MCP n’est pas disponible, par le CLI contrôlé du projet.

Le système doit :

- couvrir tout le code propriétaire utile de Titanium/Titan et JARVIS ;
- représenter explicitement Hermes, Claude, Codex, les API, WebSockets, services
  locaux et contrats qui relient ces composants ;
- maintenir un index frais avec une latence cible inférieure à 15 secondes après
  une modification stabilisée ;
- imposer un contrôle de fraîcheur et d’impact juste avant toute édition sensible ;
- réduire le coût de découverte initiale en donnant aux agents des requêtes de
  graphe ciblées plutôt qu’une relecture exhaustive du dépôt ;
- rester strictement local et ne jamais indexer de secret.

## 2. Définition de la couverture intégrale

« Intégrale » signifie : 100 % des sources propriétaires, contrats, scripts de
démarrage, configurations projet non sensibles et liens d’architecture nécessaires
pour comprendre ou modifier le système.

Sont volontairement exclus :

- `.env`, clés, tokens, credentials et fichiers explicitement sensibles ;
- `venv`, `site-packages`, `node_modules`, caches, modèles, binaires et installateurs ;
- logs, journaux runtime, fichiers d’état très volatils, rapports générés et backups ;
- historiques, télémétrie, mémoires privées et caches des installations Claude,
  Codex ou Hermes ;
- code tiers qui n’est pas maintenu dans le projet.

Ces exclusions améliorent la précision, la sécurité, la vitesse d’indexation et le
budget de contexte. Elles ne doivent jamais masquer une source propriétaire.

## 3. Architecture retenue

### 3.1 Index canonique Titanium

Le dépôt `C:\Users\flore\Desktop\v12` reste l’index canonique
`titanium-v12`. Il contient Titanium, Titan, le dashboard, les contrats MCP,
le bus de collaboration, les tests et le manifeste d’architecture.

Un `.gitnexusignore` versionné complète les exclusions Git et supprime le bruit
runtime sans exclure les sources ou tests propriétaires.

### 3.2 Index JARVIS assaini

`C:\Program Files\JARVIS` n’est pas un dépôt Git et contient un venv, des
credentials et des sauvegardes. Il ne doit pas être indexé directement.

Un synchroniseur en lecture seule copie uniquement les sources et configurations
non sensibles dans un miroir local :

`%LOCALAPPDATA%\Titanium\gitnexus\jarvis-runtime`

Le miroir :

- conserve les chemins relatifs des sources ;
- exclut `.env`, credentials, venv, caches, sauvegardes et données privées ;
- stocke un manifeste `source_path → hash → mirror_path` ;
- est un dépôt Git local technique, sans remote et sans publication ;
- ne crée un snapshot local que lorsque les hashes propriétaires changent ;
- est indexé comme dépôt GitNexus distinct `jarvis-runtime`.

Le miroir est une vue d’analyse, jamais une source d’édition. Toute correction
JARVIS continue de viser le chemin canonique sous `Program Files` avec autorisation.

### 3.3 Topologie inter-services

Un manifeste versionné dans `architecture/gitnexus/services.json` décrit :

- Titanium API `8090` et ses routes/WS ;
- JARVIS `8765/8080` ;
- GitNexus UI/API `4747` ;
- Hermes comme cerveau/orchestrateur ;
- Claude et Codex comme agents spécialisés ;
- Titan, moteurs swing/forex/crypto, MT5 et fournisseurs de données ;
- les propriétaires de chaque donnée, les sens de lecture/écriture, les protocoles,
  les contrats et les frontières d’autorité.

Ce manifeste complète les graphes statiques : une requête HTTP entre deux processus
n’apparaît pas toujours comme un import de code. Il est validé par schéma et ne
contient ni secret ni configuration privée d’agent.

## 4. Fraîcheur et indexation continue

### 4.1 Démarrage de session

`tools/gitnexus_session.ps1` est idempotent et :

1. acquiert un verrou mono-instance ;
2. vérifie `http://localhost:4747/api/health` ;
3. vérifie que `/api/repos` contient les chemins exacts Titanium et JARVIS miroir ;
4. synchronise le miroir JARVIS ;
5. contrôle les hashes et l’état incrémental des deux index ;
6. lance une analyse incrémentale si nécessaire, ou `--force` si l’index est sale ;
7. lance `gitnexus serve` si aucun serveur sain n’existe ;
8. ouvre `http://localhost:4747/` uniquement avec l’option explicite
   `-OpenBrowser` ; le `folderOpen` et les sessions agents ne créent jamais
   d’onglet automatiquement ;
9. démarre le watcher de fraîcheur.

Une tâche VS Code `runOn: folderOpen` appelle ce script. Les instructions de session
Claude/Codex/Hermes appellent aussi le contrôle idempotent, sans ouvrir plusieurs
serveurs ou watchers.

### 4.2 Surveillance

Le watcher observe uniquement les extensions propriétaires et ignore ses propres
sorties. Il applique :

- debounce de 5 secondes après le dernier changement ;
- délai maximal cible de 15 secondes ;
- une analyse à la fois ;
- nouvelle passe si des changements arrivent pendant l’analyse ;
- reconstruction complète après crash ou drapeau incrémental incomplet ;
- priorité processus basse et suspension pendant `opportunity_scan` afin de ne
  jamais concurrencer le scan MT5 des 141 actifs ;
- journal synthétique sans contenu source ni secret.

Les fichiers d’état paper, `data/*.json` et journaux runtime ne déclenchent pas
une réindexation du graphe de code. Un test anti-churn le démontre.

### 4.3 Garde avant édition

Avant toute modification dans `core/`, `execution/`, `domain/`, `api/` ou dans
les modules d’état de `utils/` :

1. contrôle de fraîcheur ;
2. mise à jour incrémentale si nécessaire ;
3. requête `context`/`query` ;
4. `impact` upstream avec avertissement HIGH/CRITICAL ;
5. édition ;
6. tests ;
7. `detect_changes` avant commit ou déploiement.

Ce garde est documenté dans `AGENTS.md`, `CLAUDE.md` et le contexte Hermes, hors
des blocs générés qui peuvent être réécrits par GitNexus. Il est facultatif pour
les docs, HTML et tests, et ne bloque jamais le travail si MCP est absent : le
fallback documenté reste l’exploration locale `rg`/lecture avec blast radius manuel.

## 5. Accès des quatre participants

- **Florent** : interface web locale `http://localhost:4747/`.
- **Claude** : serveur MCP GitNexus multi-dépôts via `gitnexus mcp`.
- **Codex** : même serveur MCP et même registre global.
- **Hermes** : client MCP GitNexus stdio confirmé par Florent ; il consomme le
  même registre multi-dépôts que Claude et Codex.

L’acceptation exige toutefois une preuve de handshake et une requête réelle depuis
Hermes ; la confirmation de capacité ne sera pas confondue avec une connexion testée.

## 6. Route GitNexus et orbe

Arbitrage Florent : `/orbe` reste l’interface JARVIS/Hermes. GitNexus obtient une
route dédiée `/nexus`, une carte dans le panneau Services et un accès direct à
`4747`.

Les deux visions sont reliées : l’orbe consomme en priorité le registre GitNexus
pour afficher symboles et flux d’exécution, avec repli AST explicite si `4747`
est indisponible. Claude réserve et maintient `titanium_orbe.html`,
`titanium_orbe_v1.html` et `tools/gen_neural_map.py`; le lot Codex ne les édite pas.

`/nexus` fournit :

- santé vérifiée avant navigation ;
- accès direct à `4747` lorsque le serveur est disponible ;
- écran local fail-visible avec procédure de relance si GitNexus est indisponible ;
- aucune mutation de trading, aucun token et aucun ordre réel.

Les agents consomment MCP, pas l’interface graphique. Le graphe présenté à Florent,
celui alimentant l’orbe et celui interrogé par les agents proviennent du même registre.

## 7. Alignement du panneau Services

`api/services_routes.py` doit abandonner les anciens ports `3000/3001/4000` et
la route obsolète `/api/graph/stats`. Le statut GitNexus utilise :

- `4747/api/health` pour la santé ;
- `4747/api/repos` pour les dépôts, chemins, dates et statistiques ;
- le nom et le chemin exacts du dépôt pour éviter un faux positif.

Le démarrage utilise la commande actuelle `gitnexus serve`, pas l’ancien
`gitnexus server`.

Les routes start/stop conservent `require_admin`; le statut reste en lecture seule.

## 8. Sécurité et limites

- bind localhost uniquement ;
- aucun partage réseau sans nouvelle décision explicite ;
- aucun secret copié dans le miroir ou les logs ;
- liste blanche d’extensions et de chemins JARVIS ;
- test rouge interdisant au minimum `.env`, credentials,
  `jarvis_conversations.json`, `jarvis_memoire.json`, `knowledge/`, `*.bak-*` et
  les fichiers audio ;
- manifeste de hashes auditable ;
- aucun push/remote pour le miroir ;
- GitNexus conseille et cartographie, mais n’autorise aucune mutation ;
- PAPER ONLY reste le garde-fou permanent de Titanium.

GitNexus ne représente pas l’état neuronal réel d’un LLM. Il cartographie le code,
les dépendances, les flux détectés et la topologie déclarée du système.

## 9. Vérification et critères d’acceptation

Avant production :

- revue de la spécification puis du diff par Claude et Hermes ;
- test du synchroniseur avec fichiers autorisés/interdits ;
- test du debounce, du verrou et de la reprise après analyse interrompue ;
- preuve qu’un changement source apparaît dans l’index en moins de 15 secondes ;
- preuve que `.env`, credentials, venv, caches et backups sont absents du miroir ;
- `/api/health` retourne 200 ;
- `/api/repos` contient les deux chemins attendus avec statistiques non nulles ;
- Claude, Codex et Hermes démontrent une requête sur le même registre ;
- `/nexus` donne accès à GitNexus et `/orbe` reste opérationnelle ;
- l’orbe indique si sa source est `gitnexus` ou le fallback `ast` ;
- le panneau Services indique le bon port, les bons dépôts et la fraîcheur ;
- la charge CPU du watcher est mesurée et sa pause pendant `opportunity_scan` prouvée ;
- la churn de `data/*.json` ne déclenche aucune analyse ;
- aucune double instance après deux ouvertures successives du workspace ;
- redémarrage final GitNexus puis contrôle complet UI/MCP/services.

## 10. Déploiement et retour arrière

Le déploiement reste local et progressif : scripts et index, puis MCP, puis panneau
Services et route `/nexus`. `/orbe` et ses fichiers ne sont supprimés à aucun moment.

Le rollback désactive la tâche VS Code, arrête uniquement les processus gérés par
le lanceur, retire `/nexus` et conserve `/orbe` ainsi que les index pour diagnostic.
Il ne touche ni aux positions paper ni aux états de trading.
