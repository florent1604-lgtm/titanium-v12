# GitNexus — identité Claude sans surcoût API

Date : 2026-07-19  
Statut : approuvé par GO conditionnel Florent, condition vérifiée  
Portée : infrastructure d'analyse C1 shadow, jamais trading

## 1. Objectif

GitNexus doit reconnaître Claude comme participant nommé de la collaboration
Titanium, au même titre que Codex et Hermes, sans créer une seconde facturation
Anthropic et sans lui attribuer de capacité d'écriture pendant C1.

Le mot « reconnaître » signifie ici :

1. Claude possède une identité stable `claude` dans le manifeste indexé.
2. Claude Code utilise un unique endpoint MCP GitNexus local.
3. L'état des services expose une configuration vérifiable sans confondre
   `configured`, `verified` et `connected`.
4. Nexus AI peut retrouver le rôle, les frontières et les décisions de Claude
   dans le graphe documentaire.
5. Une dérive vers une authentification API payante bloque l'usage Claude et
   oriente explicitement vers Ollama.

## 2. Faits vérifiés

- Claude Code est authentifié par `claude.ai` avec un abonnement `Pro`.
- Le fournisseur est Anthropic direct (`firstParty`).
- Aucune variable `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN` n'est présente.
- L'endpoint utilisateur `http://localhost:4747/api/mcp` est connecté.
- Le projet déclare en plus un transport stdio, ce qui crée un conflit de portée
  et deux identités de transport pour le même service.
- `architecture/gitnexus/services.json` déclare déjà le service `claude`, mais
  ne déclare pas encore la frontière GitNexus vers Claude.

L'absence de facturation API séparée n'est vraie que tant que Claude Code reste
authentifié par l'abonnement `claude.ai`. Les appels restent soumis aux limites
de cet abonnement.

## 3. Approches examinées

### A — endpoint HTTP canonique et identité explicite (retenue)

Conserver `http://127.0.0.1:4747/api/mcp` comme endpoint unique de Claude,
retirer le doublon stdio du scope projet, déclarer la frontière read-only dans
le manifeste et publier un état de configuration non ambigu.

Avantages : une base LadybugDB, aucun verrou concurrent, aucune clé API, même
serveur que l'interface et le watcher. Inconvénient : le poste doit conserver
la configuration utilisateur Claude Code, vérifiée par le script d'installation.

### B — transport stdio projet uniquement

Supprimer l'endpoint HTTP utilisateur et conserver le bootstrap stdio.

Avantage : configuration portable avec le dépôt. Inconvénients : nouveau
processus LadybugDB par client, risque de verrou Windows, approbation MCP à
refaire et divergence avec l'interface 4747.

### C — Ollama uniquement

Ne pas connecter Claude à GitNexus et utiliser Nexus AI avec Ollama.

Avantages : entièrement local et sans quota Anthropic. Inconvénients : perte de
la revue Claude et performances plus faibles sur le contexte long. Cette option
reste le repli obligatoire, pas le chemin nominal.

## 4. Architecture retenue

### 4.1 Identité et transport

- Identité : `claude`.
- Transport : Streamable HTTP MCP local.
- Endpoint canonique : `http://127.0.0.1:4747/api/mcp`.
- Autorité GitNexus : `code-map-only`.
- Mode C1 : `advisory-read-only`.
- Aucun header d'authentification Anthropic, aucune clé API et aucun secret dans
  le dépôt, les journaux ou le bus.

Le scope utilisateur Claude Code porte la connexion. Le scope projet ne doit
pas redéclarer GitNexus avec un endpoint différent. Le configurateur vérifie et
répare cette unicité de façon idempotente.

### 4.2 Contrat de reconnaissance

Le manifeste `architecture/gitnexus/services.json` ajoute :

- une frontière `gitnexus -> claude` pour `code-map`, mode
  `advisory-read-only` ;
- les champs de client `identity`, `transport`, `endpoint`, `billing_guard` et
  `fallback` ;
- aucune écriture GitNexus native dans les capacités Claude de C1.

La reconnaissance dans le graphe est déclarative. GitNexus MCP ne garantit pas
une session durable : l'API et le dashboard ne doivent donc jamais afficher
`connected:true` sur la seule présence d'une configuration.

### 4.3 Garde de facturation

Une vérification locale sans secret classe Claude dans l'un de ces états :

- `SUBSCRIPTION_OK` : connecté, `authMethod=claude.ai`, abonnement Pro ou Max,
  aucune clé/jeton API ni fournisseur tiers ;
- `API_BILLING_RISK` : clé API, jeton, login Console, Bedrock, Vertex, Foundry
  ou gateway avec credential détecté ;
- `UNVERIFIED` : état impossible à lire ou CLI absent.

Seul `SUBSCRIPTION_OK` autorise la proposition de Claude comme analyste. Les
deux autres états basculent Nexus AI vers Ollama et restent visibles. Aucun
secret, email, identifiant d'organisation ou jeton ne doit être persisté.

Cette garde ne promet pas un usage illimité : elle prouve seulement l'absence
de facturation API séparée dans la configuration observée.

### 4.4 État des services

`GET /services/status` expose sous `gitnexus.clients.claude` :

- `identity: "claude"` ;
- `configured` ;
- `verified_at` ;
- `transport: "http"` ;
- `endpoint_scope: "loopback"` ;
- `access: "advisory-read-only"` ;
- `billing_guard` ;
- `fallback: "ollama:qwen2.5:7b"`.

Le champ `connected` est omis tant qu'aucun heartbeat MCP fiable n'existe. Le
dashboard affiche « reconnu/configuré » et non « connecté en permanence ».

### 4.5 Repli Ollama

Ollama reste local sur `127.0.0.1:11434` avec `qwen2.5:7b`. Le repli intervient
si la garde n'est pas `SUBSCRIPTION_OK`, si Claude atteint ses limites
d'abonnement ou si l'utilisateur choisit le mode local. Le repli n'obtient
aucune capacité d'écriture et ne publie aucun ordre.

## 5. Flux

1. Le configurateur vérifie l'authentification Claude sans afficher de données
   personnelles ni de secret.
2. Il vérifie l'endpoint HTTP local unique dans le scope utilisateur.
3. Il supprime uniquement l'entrée GitNexus projet conflictuelle ; les autres
   MCP ne sont pas modifiés.
4. GitNexus sert le graphe sur 4747 et identifie les requêtes comme provenant du
   client logique `claude` par contrat local.
5. Claude lit la carte et publie ses revues sur le bus de collaboration.
6. Si la garde change, Claude n'est plus proposé et Ollama devient le moteur
   Nexus AI de repli.

## 6. Erreurs et sécurité

- GitNexus indisponible : état `UNAVAILABLE`, aucun démarrage d'un second
  backend concurrent.
- Auth Claude illisible : `UNVERIFIED`, repli Ollama.
- Auth API détectée : `API_BILLING_RISK`, repli Ollama ; aucune tentative
  Anthropic automatique.
- Endpoint hors loopback : rejet fail-closed.
- C1 interdit `rename`, `group_sync`, CommandGateway et toute mutation runtime
  à Claude par ce canal.
- Le compte réel demeure PAPER ONLY ; aucune modification de logique trading.

## 7. Tests d'acceptation

1. Le manifeste contient Claude et la frontière GitNexus read-only.
2. Un seul endpoint GitNexus apparaît dans `claude mcp list` et il est connecté.
3. Aucun endpoint stdio GitNexus concurrent n'est déclaré pour Claude.
4. `SUBSCRIPTION_OK` est produit pour l'état actuel sans persister l'email ou
   l'identifiant d'organisation.
5. Une clé API simulée produit `API_BILLING_RISK` et sélectionne Ollama.
6. Une erreur CLI produit `UNVERIFIED` et sélectionne Ollama.
7. `/services/status` distingue `configured` de `connected`.
8. L'enveloppe GitNexus RC `value` est correctement lue par la route services.
9. Les commandes start/stop de la route réutilisent le runtime gracieux validé
   et ne terminent jamais brutalement LadybugDB.
10. Les tests structurels prouvent qu'aucune capacité d'écriture/trading n'est
    ajoutée à Claude ou Ollama.

## 8. Déploiement et retour arrière

Déploiement : tests ciblés, `detect_changes`, vérification Claude CLI, cycle
GitNexus stop/start, requête Cypher/BM25, puis relecture Claude. Aucun canari
trading n'est nécessaire car le lot est purement analytique.

Retour arrière : restaurer l'entrée MCP précédente et le manifeste, sans toucher
à l'index ni aux données Titanium. Ollama reste disponible pendant toute
l'opération.

