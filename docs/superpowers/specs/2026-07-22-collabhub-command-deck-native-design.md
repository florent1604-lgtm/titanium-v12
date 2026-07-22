# CollabHub Command Deck natif — conception approuvée

Date : 2026-07-22
Statut : conception approuvée par Florent, spécification à relire avant plan d'implémentation
Périmètre : interface de collaboration, lanceur Windows, broker d'actions supervisées
Garde permanente : PAPER/DEMO ONLY ; compte réel 60261188 interdit

## 1. Objectif

Livrer une application Windows native nommée **CollabHub Command Deck** qui permet
à Florent de :

- consulter l'historique durable des échanges entre Claude, Codex, Hermes et
  Florent ;
- intervenir dans les fils de discussion sous son identité Windows ;
- suivre les décisions, preuves, présences et accusés de réception ;
- centraliser les actions locales autorisées sans contourner GitNexus,
  CommandGateway ou les murs PAPER/DEMO ;
- ouvrir l'espace de développement V12, Claude et Codex depuis un exécutable du
  Bureau ;
- réutiliser ultérieurement la même interface dans le dashboard Titanium.

Le Command Deck n'est ni un nouveau moteur de trading, ni une autorité autonome.
Il est une surface de collaboration, de supervision et de demande d'action.

## 2. Décisions validées

- Forme : application Windows native.
- Technologie : .NET 8 WPF avec WebView2.
- Disposition : **Command Deck A** — agents à gauche, conversation au centre,
  actions à droite.
- Authentification : identité Windows, sans mot de passe Titanium.
- Démarrage : CollabHub, application native, VS Code sur V12, puis terminaux
  Claude et Codex. Titanium ne démarre pas automatiquement.
- Commandes : surface complète, mais toute mutation traverse son garde dédié.
- Échecs : onglet `Échecs à suivre`, relance manuelle uniquement.
- Évolution : le module d'interface web est partagé entre WPF et le futur
  dashboard Titanium ; aucune réécriture fonctionnelle ne doit être nécessaire.
- Accès machine : lecture étendue sous les droits de l'utilisateur Windows ;
  écritures hors V12 et Registre via un Windows Action Broker supervisé.

## 3. Architecture

### 3.1 CollabHub Core

Le service Python existant sur `127.0.0.1:8770` reste l'autorité du journal de
collaboration :

- SQLite WAL/FULL pour la durabilité ;
- offsets globaux, idempotence, replay et ACK ;
- HTTP pour requêtes bornées ;
- WebSocket/SSE pour mise à jour temps réel ;
- MCP pour Claude, Codex et Hermes.

L'interface ne possède aucune base parallèle. Tous les messages, décisions,
tâches et échecs affichés proviennent de contrats CollabHub versionnés.

### 3.2 Interface partagée

Un module web autonome `collab_ui/` contient le rendu, la navigation, les filtres
et les composants du Command Deck. Il ne contient aucune primitive Windows ni
aucun appel direct aux moteurs Titanium.

Deux hôtes utilisent ce même module :

1. la coque WPF l'affiche dans WebView2 ;
2. le futur dashboard Titanium le monte comme vue intégrée.

Les dépendances spécifiques à l'hôte passent par une interface restreinte
`HostBridge`. Dans un navigateur Titanium, les fonctions Windows indisponibles
sont annoncées comme telles au lieu de devenir fail-open.

### 3.3 Coque WPF

La coque .NET 8 fournit :

- fenêtre native, cycle de vie et icône ;
- WebView2 avec stockage persistant limité au profil Command Deck ;
- vérification de l'identité Windows ;
- injection en mémoire d'une session locale éphémère ;
- dialogue natif de confirmation ;
- notifications Windows ;
- ouverture de VS Code et des terminaux approuvés ;
- appel du Windows Action Broker.

Le code web ne reçoit ni mot de passe, ni clé privée, ni jeton dans l'URL. La
session est transmise en mémoire par le pont WebView2 et expire à la fermeture ou
après inactivité.

### 3.4 Lanceur du Bureau

Un exécutable `Lancer CollabHub.exe` est installé sur le Bureau. Son démarrage est
idempotent :

1. résoudre le chemin canonique `C:\Users\flore\Desktop\v12` ;
2. vérifier l'identité Windows attendue ;
3. vérifier les listeners MCP et démarrer seulement ceux qui sont absents via le
   superviseur existant ;
4. attendre la santé CollabHub avec délai borné ;
5. ouvrir ou focaliser le Command Deck ;
6. ouvrir ou réutiliser VS Code sur V12 ;
7. ouvrir un terminal Claude et un terminal Codex via des adaptateurs versionnés ;
8. publier un événement de démarrage assaini dans CollabHub.

Le lanceur ne tue pas les processus inconnus, ne force pas un port occupé et ne
démarre pas Titanium. Une fermeture du Command Deck ne ferme ni les agents, ni
GitNexus, ni Titanium.

## 4. Expérience utilisateur

### 4.1 Rail des organes

Le rail gauche affiche Florent, Hermes, Claude, Codex, GitNexus, CollabHub et
Titanium avec : présence, dernier ACK, latence, tâche active et état
`ONLINE/IDLE/DEGRADED/OFFLINE/UNKNOWN`. `UNKNOWN` n'est jamais affiché en vert.

### 4.2 Conversation centrale

La conversation présente :

- ordre global exact du journal ;
- auteur, destination, type, tâche, corrélation et classification ;
- fils par `task_id` et `in_reply_to` ;
- recherche plein texte locale ;
- filtres agent, tâche, décision, revue, alerte et période ;
- liens de preuve ouvrables après validation du chemin ;
- marqueurs lu/ACK sans modifier l'historique.

Florent publie sous le principal `florent`, attesté par la session Windows. Les
commandes textuelles initiales sont `/status`, `/task`, `/review`, `/decision` et
`/command`. Une commande produit d'abord une proposition explicite ; elle ne
déclenche jamais un effet par simple interprétation conversationnelle.

### 4.3 Dock d'actions

Chaque action porte un état visible :

- `Disponible` : opération locale réversible et allowlistée ;
- `Validation requise` : aperçu puis consentement Florent ;
- `Double signature` : GitNexus `rename`/`group_sync` ;
- `Bloquée` : garde ou prérequis non satisfait ;
- `Indisponible` : service absent ou santé inconnue.

La feuille de confirmation affiche avant validation : cible, environnement,
ancienne et nouvelle valeur, effet attendu, impact, preuves, approbations,
expiration et rollback disponible.

### 4.4 Onglet « Échecs à suivre »

L'onglet consolide les tâches échouées avec :

- identifiant, tâche source et tentative ;
- propriétaire et organe concerné ;
- date, priorité et impact ;
- cause normalisée ;
- preuve ou log assaini ;
- action suivante proposée ;
- états `Nouveau`, `À analyser`, `Correctif en cours`, `À revalider`, `Clos`.

Les causes autorisées sont au minimum : `SERVICE_UNAVAILABLE`,
`VALIDATION_REJECTED`, `PERMISSION_REQUIRED`, `TIMEOUT`, `TEST_FAILED`,
`GUARD_TRIGGERED`, `CONFLICT` et `UNKNOWN_FAILURE`.

Aucune relance automatique n'est autorisée. Une relance manuelle crée une
nouvelle tentative liée à l'originale ; elle ne modifie ni ne supprime le fait
historique.

## 5. Autorité et sécurité

### 5.1 Matrice de capacités

| Niveau | Exemple | Règle |
|---|---|---|
| L0 lecture | historique, santé, code, graphe | autorisée sous droits Windows, secrets assainis |
| L1 collaboration | message, tâche, décision, ACK | session Florent requise |
| L2 local réversible | ouvrir VS Code, démarrer un singleton absent | confirmation simple selon politique |
| L3 mutation supervisée | fichier hors V12, Registre allowlisté | aperçu, sauvegarde, validation Florent, journal |
| L4 sensible | zone système critique, élévation | confirmation Windows/UAC distincte et garde dédiée |
| L5 trading | PAPER/DEMO via gateway validé | M2 si applicable, garde compte, validation prévue |
| Interdit | compte réel 60261188, secret, bypass | capacité absente |

### 5.2 Windows Action Broker

Claude et Codex conservent la visibilité offerte par le compte Windows sur les
dossiers locaux. La collecte destinée au chat ou aux journaux applique toutefois
un secret gate avant persistance et exclut les coffres d'identifiants.

Toute écriture hors V12 ou dans le Registre passe par un broker séparé :

- allowlist d'opérations et de chemins ;
- résolution canonique des chemins, refus des jonctions hors cible ;
- aperçu déterministe ;
- sauvegarde préalable pour les clés Registre ;
- validation Florent liée au digest exact de l'opération ;
- TTL, nonce, anti-rejeu et journal du résultat ;
- rollback proposé, jamais destructif automatiquement.

Une validation simple suffit aux clés allowlistées et réversibles. Les zones
`HKLM\SECURITY`, gestion des comptes, credentials, Defender, pare-feu, UAC,
pilotes, services critiques et démarrage système exigent une élévation Windows
distincte. Hermes ne détient aucune capacité du broker.

### 5.3 GitNexus et trading

- GitNexus : `rename` et `group_sync` uniquement, dans V12, avec double signature
  Florent + superviseur, TTL, anti-rejeu et `detect_changes` fail-closed.
- CommandGateway : aucune commande DEMO tant que sa re-revue n'est pas validée.
- Le Command Deck ne possède aucun appel direct vers un moteur, `order_send`, une
  route d'administration ou une clé broker.
- Le compte réel reste absent du registre de capacités.

## 6. Contrats ajoutés

Les nouveaux contrats CollabHub sont versionnés et validés avant persistance :

- `task.created.v1` ;
- `task.state_changed.v1` ;
- `task.attempt_failed.v1` ;
- `task.retry_requested.v1` ;
- `action.proposed.v1` ;
- `action.approval_requested.v1` ;
- `action.result.v1` ;
- `agent.presence.v1`.

Les payloads utilisent des reason codes stables. Les exceptions brutes, variables
d'environnement, jetons, clés, mots de passe et données de coffres ne sont jamais
persistés.

## 7. Gestion des erreurs

- CollabHub indisponible : fenêtre en lecture locale limitée, publication et
  actions désactivées, reprise manuelle ou automatique bornée du transport.
- WebSocket coupé : replay HTTP depuis le dernier offset confirmé, sans supposer
  la contiguïté des offsets.
- Port occupé : identifier le listener ; ne jamais tuer un PID non géré.
- VS Code/agent absent : afficher l'erreur et proposer le chemin de correction ;
  aucune installation silencieuse.
- Broker en erreur : effet considéré `UNKNOWN` jusqu'à vérification indépendante.
- Échec partiel du lanceur : Command Deck reste ouvert avec diagnostic ; aucun
  démarrage de Titanium en compensation.

## 8. Validation et critères d'acceptation

### 8.1 Tests automatisés

- contrats et migrations SQLite ;
- replay, ACK, reconnexion WebSocket et idempotence ;
- publication attestée comme Florent ;
- recherche, filtres et fils ;
- création, classification et clôture d'échecs ;
- preuve qu'aucun retry automatique n'existe ;
- matrice de capacités et états des boutons ;
- expiration/anti-rejeu de session et approbations ;
- secret gate avant persistance ;
- Action Broker avec faux Registre et rollback ;
- idempotence du lanceur et ports occupés ;
- ouverture VS Code/Claude/Codex via doubles de processus ;
- absence d'appel direct trading/registre dans le module web ;
- parité du module web entre hôte WPF et hôte Titanium.

### 8.2 Vérifications manuelles Windows

- double-clic depuis le Bureau sans privilège administrateur ;
- affichage correct avec mise à l'échelle 100 %, 125 % et 150 % ;
- verrouillage de session Windows et expiration du jeton ;
- dialogue UAC seulement pour une action L4 explicitement demandée ;
- fermeture/réouverture sans perte d'historique ;
- fonctionnement lorsque VS Code ou un singleton est déjà actif.

### 8.3 Livraison

- build `.exe` reproductible ;
- raccourci Bureau ;
- manifeste de version et SHA-256 ;
- signature Authenticode si un certificat de signature est disponible ;
- procédure de désinstallation limitée aux artefacts Command Deck ;
- aucun secret ni chemin de clé privée dans le package.

## 9. Hors périmètre de cette première livraison

- démarrage automatique de Titanium ;
- exécution d'ordre réel ;
- activation de CommandGateway non validé ;
- signature GitNexus automatique ;
- retry automatique des tâches ;
- modification autonome du Registre par un agent ;
- remplacement du dashboard Titanium existant.

L'intégration dans Titanium constituera une phase ultérieure : elle réutilisera
le module `collab_ui/`, les mêmes contrats et les mêmes tests de parité.
