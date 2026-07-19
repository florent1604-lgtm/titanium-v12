# CommandGateway FM — centre neuronal gouverné

Statut : **spécification écrite soumise à la revue de Florent**.

Date : 19 juillet 2026.

Périmètre immédiat : **C1 SHADOW strict, PAPER/DEMO ONLY, zéro handler et zéro
effet**. Aucun ordre réel n'est autorisé, maintenant ou dans les paliers décrits.

## 1. Décision

Titanium adopte l'architecture **B** : un service Windows local séparé, nommé
`TitaniumCommandGateway`, reçoit des `Proposal` non fiables par named pipe,
authentifie le principal par son identité Windows, journalise avant de répondre,
évalue une politique déterministe et publie ses résultats comme faits d'audit.

Pendant C1, le pipeline s'arrête après la décision shadow. Le registre de handlers
est vide et aucun jeton d'autorisation exécutable n'est créé. C1 sert uniquement à
mesurer les propositions, refus, faux positifs, divergences de policy, latences et
qualité des explications.

À terme, le service devient la frontière efférente du **centre neuronal**. Les cinq
participants — Florent, Hermes, Claude, Codex et Nexus AI local — peuvent lire des
projections autorisées et soumettre des propositions selon leur identité propre.
Cette centralisation ne signifie pas « accès brut en lecture/écriture ». Toute
écriture reste une capacité typée, bornée, journalisée, default-deny et soumise au
`PolicyKernel`. Aucun participant IA ne reçoit un secret broker, un token admin, un
shell libre, un handler libre ou une connexion directe à MT5.

## 2. Objectifs et non-objectifs

### Objectifs

- créer une frontière unique, observable et testable pour les demandes d'action IA ;
- conserver Hermes comme cerveau principal de perception et de proposition ;
- donner à Claude, Codex et Nexus AI un rôle de revue, analyse et proposition sans
  autorité implicite ;
- préserver l'autonomie des moteurs DEMO déterministes existants hors gateway ;
- rendre chaque proposition, décision, autorisation, effet et résultat corrélables ;
- permettre une extension graduelle C1 → C2 → C3 sans changer les invariants ;
- garder un contrat de transport abstrait afin qu'une distribution future puisse
  adopter NATS sans réécrire les identités, offsets, digests ou policies.

### Non-objectifs

- aucune activation de capacité PAPER ou DEMO dans ce lot ;
- aucune commande transportée par l'EventPlane ;
- aucune suppression des gardes locales compte/mode/risque aux sinks ;
- aucun accès d'écriture général au code, filesystem, registre ou broker ;
- aucun remplacement du bus UI, du bus de collaboration ou du garde GitNexus signé ;
- aucun changement de stratégie ou de logique de trading sans protocole M2.

## 3. Plans et frontières

```text
EventPlane SQLite/WAL (faits) ---> Cortex/projections ---> lecteurs autorisés
                                            |
                                            v
Florent / Hermes / Claude / Codex / Nexus AI local
                                            |
                                   Proposal non fiable
                                            v
Named pipe + DACL + impersonation ---> CommandGateway
                                            |
                          journal efférent avant réponse
                                            |
                         PolicyKernel pur + registre gelé
                                            |
                       C1: ShadowDecision, puis STOP absolu
                                            |
                  C2/C3 futurs: autorisation one-shot bornée
                                            |
                         handler interne statique allowlisté
                                            |
                     revalidation locale au dernier instant
                                            |
                                  PAPER ou DEMO seulement
```

L'EventPlane est strictement afférent : il transporte des faits et des résultats
d'audit. Le gateway ne consomme jamais un événement comme commande. Le chemin de
soumission est le named pipe dédié. Le bus `utils/event_bus.py` reste réservé à la
télémétrie/UI.

## 4. Composants

### 4.1 `TitaniumCommandGateway` — service Windows

Le service possède son compte ou SID de service dédié, un répertoire de données
minimal et aucun secret broker. Il ouvre un seul named pipe versionné :

`\\.\pipe\Titanium.CommandGateway.Proposal.v1`

Il ne charge pas MT5, ne résout pas de fonctions depuis des chaînes et n'importe
pas les modules d'exécution en C1. Un crash du service ferme le pipe et bloque les
nouvelles propositions ; les protections et moteurs déterministes continuent selon
leurs propres règles.

### 4.2 `PrincipalAttestor`

Le serveur impersonate le client à chaque connexion, lit son token Windows et
compare son SID à une allowlist locale versionnée. Le champ JSON `principal` est
informatif : il ne peut jamais remplacer l'identité OS.

Identités cibles :

- un compte/service Hermes dédié ;
- le SID du service Gateway ;
- Florent via une console opérateur distincte et auditée ;
- des identités séparées pour Claude, Codex ou Nexus AI uniquement lorsqu'un palier
  futur les autorise explicitement.

Compte partagé, SID absent, impersonation impossible, token anonyme, distant ou
élevé de manière inattendue : `AUTHENTICATION_FAILED`, journalisation redigée et
fermeture de la connexion. Aucun bearer token n'est accepté.

### 4.3 `ProposalIngress`

Le protocole est un flux local longueur-préfixée : entier non signé 32 bits little
endian suivi d'un JSON canonique UTF-8. Une trame est limitée à 64 KiB, une connexion
à 8 requêtes en vol, et chaque requête possède une deadline bornée. Les trames
partielles, compressées, surdimensionnées ou contenant des octets après le document
JSON sont refusées. Les clés inconnues sont interdites.

Le service impose une limite par principal et une limite globale. Une saturation
retourne `RATE_LIMITED`; elle ne crée pas de file mémoire illimitée.

### 4.4 `EfferentJournal`

SQLite/WAL est la vérité autoritaire locale. Réglages : `journal_mode=WAL`,
`synchronous=FULL`, `foreign_keys=ON`, `busy_timeout` borné. Le fichier recommandé
est `data/control_gateway/command-gateway-v1.sqlite3`, accessible uniquement au SID
du Gateway et aux opérateurs d'audit autorisés.

Tables normatives :

```sql
CREATE TABLE proposals (
  proposal_id TEXT PRIMARY KEY,
  principal_sid TEXT NOT NULL,
  principal_kind TEXT NOT NULL,
  capability_id TEXT NOT NULL,
  capability_version INTEGER NOT NULL,
  requested_mode TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  proposal_sha256 TEXT NOT NULL,
  proposal_json TEXT NOT NULL CHECK (json_valid(proposal_json)),
  received_at TEXT NOT NULL,
  UNIQUE (principal_sid, idempotency_key)
);

CREATE TABLE decisions (
  decision_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL UNIQUE,
  policy_version TEXT NOT NULL,
  registry_digest TEXT NOT NULL,
  state_digest TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('ALLOW','DENY','NO_DECISION')),
  shadow INTEGER NOT NULL CHECK (shadow IN (0,1)),
  reason_codes_json TEXT NOT NULL CHECK (json_valid(reason_codes_json)),
  decided_at TEXT NOT NULL,
  FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id)
);

CREATE TABLE authorizations (
  authorization_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL UNIQUE,
  authorization_digest TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  consumer_handler_id TEXT,
  FOREIGN KEY (decision_id) REFERENCES decisions(decision_id)
);

CREATE TABLE outcomes (
  outcome_id TEXT PRIMARY KEY,
  authorization_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN
    ('SUCCEEDED','REJECTED','FAILED','UNKNOWN')),
  reason_codes_json TEXT NOT NULL CHECK (json_valid(reason_codes_json)),
  broker_ref TEXT,
  recorded_at TEXT NOT NULL,
  FOREIGN KEY (authorization_id) REFERENCES authorizations(authorization_id)
);
```

En C1, la table `authorizations` doit rester vide par invariant vérifié au démarrage,
pendant les tests et dans la santé runtime.

### 4.5 `CommandCapabilityRegistry`

Le registre est fermé, versionné et son digest SHA-256 est calculé au démarrage. Une
entrée contient ID/version, schéma de paramètres, modes permis, classe d'effet,
policy requise, TTL, rate limit, preuve M2, approval et `handler_id` interne.

En C1 :

- les capacités peuvent être décrites pour évaluation shadow ;
- leur statut exécutable est `SHADOW_ONLY` ;
- la table interne `handler_id -> callable` est vide ;
- toute tentative de résolution d'un handler est une violation critique.

Les capacités de changement de policy, limite de risque, compte, mode, registre,
secret, kill-switch, circuit-breaker ou approval ne sont jamais exposées aux IA.

### 4.6 `PolicyKernel`

Fonction pure :

`evaluate(AttestedProposal, TrustedState, FrozenRegistry) -> PolicyDecision`

Le kernel n'effectue ni réseau, ni I/O, ni appel LLM. Il valide identité, schéma,
TTL, idempotence, capability/version, mode, compte, instrument, fraîcheur,
intégrité EventPlane, policy/digest, M2, approval, limites et kill-switch. Un champ
inconnu ou une preuve absente produit `DENY` ou `NO_DECISION`.

En C1, même un verdict logique `ALLOW` devient `ShadowDecision(verdict=ALLOW,
dispatch_permitted=false, reason_codes=['C1_SHADOW_NO_DISPATCH'])`.

### 4.7 `GatewayReply`

Réponse stricte et stable :

```json
{
  "reply_schema_version": 1,
  "request_id": "uuid",
  "proposal_id": "uuid-or-null",
  "decision_id": "uuid-or-null",
  "status": "SHADOW_RECORDED",
  "verdict": "ALLOW|DENY|NO_DECISION|null",
  "dispatch_permitted": false,
  "reason_codes": ["C1_SHADOW_NO_DISPATCH"],
  "policy_version": "policy/1.0.0",
  "registry_digest": "sha256",
  "recorded_at": "UTC",
  "correlation_id": "opaque"
}
```

Les messages libres, stack traces, chemins locaux, SIDs complets et contenus
sensibles sont absents. Les détails d'exploitation restent dans le journal local
redigé.

### 4.8 `AuditFactPublisher`

Après commit dans le journal efférent, le gateway tente de publier vers
l'EventPlane des faits versionnés : proposal received, policy decided, dispatch
attempted et outcome observed. Une panne EventPlane ne modifie jamais le verdict
ni ne crée un succès ; le journal marque `AUDIT_PUBLISH_PENDING` et réessaie avec la
même idempotency key. Aucun subscriber ne peut réinjecter ces faits dans le gateway.

## 5. Machine d'états

```text
RECEIVED
  -> REJECTED_AUTH
  -> REJECTED_SCHEMA
  -> DEDUPLICATED
  -> PERSISTED
       -> SHADOW_DENIED
       -> SHADOW_NO_DECISION
       -> SHADOW_ALLOWED_NO_DISPATCH

Paliers futurs seulement :
PERSISTED -> POLICY_ALLOWED -> APPROVAL_BOUND -> AUTHORIZED_ONCE
           -> DISPATCHING -> SUCCEEDED | REJECTED | FAILED | UNKNOWN
```

Transitions interdites en C1 : `AUTHORIZED_ONCE`, `DISPATCHING` et tout outcome
d'effet. Elles provoquent arrêt fail-closed et santé `CRITICAL`.

Un retry exact retourne le même `proposal_id`, `decision_id` et reply. Une même clé
d'idempotence avec un digest différent retourne `IDEMPOTENCY_CONFLICT`. Un timeout
après une future frontière broker devient `UNKNOWN` et déclenche une réconciliation,
jamais un second ordre automatique.

## 6. Centre neuronal : trajectoire de libération des flux

La cible long terme centralise les flux sans supprimer les frontières :

1. **Lecture** : chaque organe lit une projection dédiée, bornée et versionnée. Les
   sources autoritaires restent leurs stores ; le centre neuronal expose une vue,
   pas une copie mutable universelle.
2. **Proposition** : chaque principal soumet un contrat typé avec son SID, son rôle,
   son budget, son TTL et ses références de contexte.
3. **Écriture** : seule une capability active peut modifier un état. Policy,
   approval, autorisation one-shot et revalidation au sink restent obligatoires.
4. **Apprentissage** : mémoire et hypothèses restent offline/shadow. Leur promotion
   est versionnée, testée, revue et soumise à M2 si décisionnelle.
5. **Cartographie** : GitNexus et Nexus AI fournissent contexte et impact. Ils ne
   deviennent ni source de policy ni autorité d'exécution.

Le garde GitNexus `rename/group_sync` reste un canal séparé avec approbations signées.
Une autorisation de code n'est jamais réutilisable comme autorisation de trading.

## 7. Migration des chemins actuels

Avant C2, les chemins suivants doivent être rendus inaccessibles à Hermes et à tout
principal IA :

- JARVIS `_orchestrateur_titanium` ne doit plus lire `ADMIN_TOKEN` ni appeler
  `run_plan(..., allow_mutate=True)` pour une intention vocale ;
- `titanium_connector.action_close_all` ne doit plus appeler directement un POST
  mutable ;
- `run_swing_scan` ne doit plus être classé comme simple lecture tant qu'il peut
  atteindre `place_demo_async` puis `mt5.order_send` ;
- `reset_circuit_breaker` est retiré de toute allowlist IA ;
- le journal historique best-effort de `run_plan` ne peut pas servir de journal
  control-grade ;
- un résultat broker incertain doit être `UNKNOWN`, jamais `None` interprétable
  comme absence d'effet.

Ces corrections sont des lots séparés, avec impact GitNexus, tests RED/GREEN et
revue indépendante. Aucun changement JARVIS n'est implicite dans cette spec.

## 8. Santé et observabilité

Le service expose une projection GET-only contenant : état, âge heartbeat, version,
registry digest, policy version, mode `C1_SHADOW`, nombre de proposals, verdicts,
conflits d'idempotence, latence p50/p95, audit pending, invariant
`authorization_count=0`, DACL/SID attestation et dernier reason code redigé.

États : `STARTING`, `HEALTHY`, `DEGRADED`, `STALE`, `FAILED`, `STOPPED`, `UNKNOWN`.
`UNKNOWN` n'est jamais vert. Le superviseur peut redémarrer le service d'observation
selon un budget borné ; il ne clear jamais un kill-switch ou circuit-breaker.

## 9. Tests d'acceptation C1

1. DACL refuse tout SID non allowlisté ; impersonation absente refuse la connexion.
2. Principal JSON usurpé ne change pas le SID attesté.
3. Trame >64 KiB, partielle, invalide ou avec clés inconnues est refusée.
4. Proposal valide est durable après réouverture du store avant reply.
5. Retry exact retourne les mêmes IDs ; retry divergent produit un conflit.
6. PolicyKernel est déterministe et sans I/O ; justification n'influence pas le verdict.
7. Unknown capability/version/mode/policy/state produit default-deny.
8. Compte réel plus toute capacité d'ordre produit `REAL_ACCOUNT_ORDER_FORBIDDEN`.
9. `handler_id -> callable` est vide et aucun import d'exécution n'existe en C1.
10. Même `ALLOW` shadow produit `dispatch_permitted=false`.
11. `authorizations` et `outcomes` restent vides sous charge, panne et replay.
12. EventPlane ne contient aucun consumer qui appelle le gateway ou un sink.
13. Panne journal avant commit retourne `STORE_UNAVAILABLE`, sans reply positif.
14. Panne EventPlane après commit conserve la décision et marque l'audit pending.
15. Horloge incohérente, TTL expiré, projection stale, gap/hash cassé sont refusés.
16. Fuzz du protocole n'entraîne ni crash, ni fuite, ni croissance mémoire non bornée.
17. Tests structurels prouvent l'absence de `order_send`, HTTP POST mutable, shell,
    filesystem libre et import dynamique dans le service C1.
18. Canari 24 h shadow : zéro handler, zéro authorization, zéro effet trading.

## 10. Paliers et gates

| Palier | Fonction | Gate obligatoire |
|---|---|---|
| C0 actuel | EventPlane/Cortex read-only | déjà séparé du contrôle |
| C1 | proposals + policy shadow | cette spec, plan TDD, revue Claude/Codex, go Florent |
| C2 | capacités PAPER unitaires | registre/digest v2, tests panne/TOCTOU, approval séparée |
| C3 | capacités DEMO unitaires | preuve M2, compte DEMO revalidé au sink, go séparé |
| C4 | centre neuronal multi-principal | identités OS séparées, budgets, audits et révocation |
| Réel | ordre broker | interdit sans exception |

Le rollback C1 désactive le service, ferme le pipe et conserve le journal en lecture
seule pour audit. Il ne modifie ni EventPlane, ni stratégies, ni moteurs, ni compte.

## 11. Critères de sortie de la conception

La rédaction du plan d'implémentation ne commence qu'après validation explicite de
ce document par Florent. L'implémentation commence ensuite par les contrats purs,
le journal et les tests C1 ; aucun handler, flag d'activation trading ou câblage
JARVIS n'entre dans le premier plan.
