# CollabHub temps réel — conception

**Statut :** validé par Florent (« GO » du 21/07/2026), implémentation autorisée en C1 shadow.

## Objectif

Remplacer le bus NDJSON pollé par un centre de collaboration local, durable et
temps réel pour Florent, Claude, Codex et Hermès. Le système partage des messages,
des hypothèses synthétiques, des preuves, des décisions et des états de travail ;
il ne collecte ni ne révèle le raisonnement interne brut des modèles.

## Frontière de sécurité

Le CollabHub est séparé de `core.event_plane` et du CommandGateway :

- il ne contient aucun ordre, aucune autorisation broker et aucun secret ;
- Hermès agit comme orchestrateur C1 shadow : lecture, analyse, orientation,
  publication et propositions sans dispatch ;
- le compte réel `60261188` reste interdit et PAPER/DEMO restent les seuls modes ;
- `permissions_respond`, shell, administration Windows, écriture arbitraire,
  commit/push/reset et modification de logique trading ne sont pas exposés ;
- les écritures GitNexus restent dans le garde existant. Tant que Claude n'a pas
  arbitré H2, la double signature documentée reste fail-closed.

## Architecture retenue

```text
Claude MCP ─┐
Codex MCP  ─┼──────────────┐
Hermès MCP ─┘              │
                           v
                    CollabHub :8770
                 ┌───────────────────┐
                 │ contrats typés    │
                 │ SQLite WAL/FULL   │
                 │ ACK + curseurs    │
                 │ présence/health   │
                 │ WS + SSE + MCP    │
                 └───────────────────┘
                           │
                   dashboard / JARVIS

NDJSON actuel <── export/fallback temporaire, jamais source autoritaire
```

Le store autoritaire est `data/collab_hub/collab-v1.sqlite3`. Un commit durable
précède toujours l'acquittement de publication. Le serveur écoute uniquement sur
`127.0.0.1:8770`.

## Contrat de message v1

Champs immuables :

- `schema_version=1` ;
- `message_id` UUIDv4 attribué par le store ;
- `global_offset` monotone attribué au commit ;
- `created_at` UTC attribué au commit ;
- `principal` dans `{florent, claude, codex, hermes, system}` ;
- `target` : principal ou sujet `topic:<nom>` ;
- `kind` dans `status`, `handoff`, `question`, `review`, `decision`, `ack`,
  `presence`, `alert` ;
- `task_id`, `correlation_id` et `in_reply_to` optionnels et bornés ;
- `content` obligatoire, UTF-8, 1 à 32 000 caractères ;
- `evidence_refs` : liste de références opaques bornées, jamais des secrets ;
- `idempotency_key` obligatoire et unique par principal ;
- `classification` dans `PUBLIC`, `INTERNAL`, `SENSITIVE_METADATA`.

Les champs inconnus, NaN/Inf, contenu vide, principal inconnu et cible libre non
conforme sont refusés. Un retry identique retourne le même reçu ; une réutilisation
de clé avec contenu différent retourne `IDEMPOTENCY_CONFLICT`.

## Garanties du store

- SQLite `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`,
  `busy_timeout=5000` ;
- transaction `BEGIN IMMEDIATE` pour publication et séquence ;
- lecture par `global_offset`, ordre strict et limite 1..1000 ;
- curseur durable par consumer, monotone et jamais régressif ;
- ACK explicite par message et consumer ;
- présence avec heartbeat, état `ONLINE/IDLE/OFFLINE/DEGRADED` et expiration ;
- aucune suppression dans v1 ; export NDJSON déterministe disponible pour audit.

## Transports

### HTTP/temps réel

- `GET /health` : santé store, head offset, connexions, présence ;
- `POST /v1/messages` : publication ;
- `GET /v1/messages?after_offset=&limit=&target=` : replay/lecture ;
- `POST /v1/consumers/{consumer_id}/ack` : curseur durable ;
- `POST /v1/presence` et `GET /v1/presence` ;
- `GET /v1/stream` : SSE avec reprise `Last-Event-ID` ;
- `WS /v1/ws` : diffusion après commit, heartbeat et déconnexion nettoyée.

Un client lent ne bloque pas le store : chaque connexion possède une file bornée.
En cas de saturation, la connexion est fermée et reprend depuis son dernier offset.

### MCP

Le même processus monte un serveur Streamable HTTP à `/mcp` avec les outils :

- `collab_publish` ;
- `collab_read` ;
- `collab_ack` ;
- `collab_presence` ;
- `collab_health`.

Les outils exposent uniquement le contrat C1. Aucun outil d'approbation, de shell,
d'écriture fichier, de Git ou de trading n'est créé.

## Identité

La phase fonctionnelle démarre en loopback avec principal déclaré et journalisé.
Avant de déclarer l'attribution « signée », chaque adaptateur reçoit une identité
Ed25519 de service : clé privée hors dépôt sous le profil Windows, clé publique
dans `collab/governance/collab_principals.json`. La signature couvre le JSON
canonique, un nonce et une fenêtre temporelle. Un principal ne peut signer pour un
autre. Les lectures INTERNAL restent loopback ; toute publication exige ensuite
une signature valide lorsque `COLLAB_REQUIRE_SIGNATURES=1`.

Le passage de `0` à `1` requiert une répétition complète des tests d'intégration et
une revue Claude/Codex. Aucun secret de service ne transite dans le bus.

## Migration

1. Lancer CollabHub sans modifier le runtime Titanium.
2. Importer l'historique NDJSON en lecture seule avec clés d'idempotence stables.
3. Connecter Claude/Codex/Hermès via MCP.
4. Conserver `collab_bus.mjs` comme fallback et export durant une période bornée.
5. Ajouter l'affichage dashboard/JARVIS après preuve de stabilité.
6. Retirer le polling NDJSON seulement après comparaison des offsets et ACK.

## Critères d'acceptation

1. deux publications simultanées obtiennent des offsets uniques et contigus ;
2. retry identique ne duplique pas ; retry divergent est refusé ;
3. redémarrage conserve messages, ACK et présence durable ;
4. un consumer ne peut faire régresser son offset ;
5. SSE et WebSocket reprennent sans perte depuis un offset ;
6. une connexion lente est isolée sans bloquer les autres ;
7. la liste MCP ne contient que les cinq outils C1 ;
8. aucune dépendance vers `execution/`, broker ou CommandGateway ;
9. configuration réseau strictement loopback ;
10. les tests existants du bus, d'Hermès et des singletons restent verts.

