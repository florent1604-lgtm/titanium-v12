# Fondation de la fusion Hermes — invariants, EventPlane B0/C0 et CommandGateway

**Statut : contrat de conception implémentable, pas de code runtime.**

**Mission : `AUDIT_ARCHI_V12` — directive Florent du 19/07/2026.**

**Périmètre : PAPER/DEMO ONLY. Aucun flag, aucun ordre, aucun câblage actif.**

## Verdict et frontière d'autorité

La « fusion Hermes à 300 % » signifie que Hermes peut être présent dans toute la
boucle **afférente** (perception), dans la mémoire/apprentissage hors ligne et dans
la boucle **efférente sous forme de propositions**. Elle ne lui donne aucune
autorité directe sur un moteur, un compte, une politique ou un sink d'exécution.

La fondation retenue comporte quatre plans séparés :

```text
Moteurs / données / exécution
        |
        | faits typés, jamais des commandes
        v
EventPlane durable B0 ---> projections read-only ---> Cortex / Hermes / mémoire
                                                       |
                                                       | Proposal non fiable
                                                       v
                                                CommandGateway
                                                       |
                                                PolicyKernel déterministe
                                                       |
                                            registre fermé et versionné
                                                       |
                                          handler codé / sink allowlisté
                                                       |
                                revalidation compte + mode + risque au sink
```

Le `utils/event_bus.py` actuel reste un bus de télémétrie/UI. Il n'est ni modifié,
ni promu, ni utilisé comme plan de contrôle : son `emit()` a un blast radius
GitNexus déjà qualifié **CRITICAL** (11 amonts, 5 flux) et ses files peuvent perdre
silencieusement. B0 est un module et un stockage distincts, d'abord en miroir.

## 1. Invariants de sûreté non négociables

Ces invariants priment sur les prompts, la mémoire, les modèles, les stratégies,
les paramètres, les approvals ordinaires et la disponibilité du système.

### I-01 — Mur compte réel / compte démo

- Le compte Axi réel est **PAPER ONLY**. Aucun `order_send` ni mutation broker ne
  peut être émis vers lui, quelle que soit l'origine de la demande.
- Une action DEMO exige que le sink relise l'identité du compte dans la session
  broker active et la compare à l'identité DEMO attendue issue d'une configuration
  de confiance. Valeur absente, ambiguë, différente ou session changée = refus.
- Un alias de compte peut apparaître dans les événements ; jamais un secret ou une
  identité fournie par Hermes. Le compte effectif n'est jamais choisi par la
  proposition.

### I-02 — Fail-closed par défaut

Tout inconnu, panne, timeout, schéma non reconnu, donnée non finie, état partiel,
horloge incohérente, registre indisponible, policy inconnue, approval absent,
projection stale, gap d'événements ou résultat d'exécution incertain produit
`DENY`, `NO_DECISION`, `STALE`, `DEGRADED` ou `UNKNOWN` — jamais `ALLOW` implicite.

### I-03 — Hermes/LLM n'est jamais décideur

- Un texte, plan, souvenir, embedding, score LLM ou `Proposal` est une entrée non
  fiable. Il ne constitue ni une décision, ni une preuve M2, ni une approval.
- Hermes ne fournit jamais URL, nom de fonction, handler, token, compte effectif,
  règle de risque ou destination d'exécution.
- Aucun subscriber de l'EventPlane ne peut déclencher un handler ou un ordre.

### I-04 — Frontière efférente unique du cerveau

Toute action demandée par Hermes passe obligatoirement par :

`Proposal -> CommandGateway -> PolicyKernel -> registre fermé -> handler codé`.

Aucun appel direct de Hermes à `demo_bridge`, aux moteurs, à HTTP POST, au broker,
au shell, au filesystem mutable ou à une fonction résolue dynamiquement n'est admis.
Les chemins déterministes existants restent hors de cette frontière tant qu'ils ne
sont pas refactorés, mais **tout sink d'ordre**, quelle que soit l'origine, conserve
ses gardes locales compte/mode/risque.

### I-05 — Revalidation déterministe au dernier moment

Une autorisation du gateway n'est pas une autorisation durable. Immédiatement avant
l'effet irréversible, le sink relit et revalide au minimum : compte actif, mode,
instrument canonique, marché/session, fraîcheur, kill-switch, limites de risque,
positions/exposition, volume/précision et version de politique. Toute divergence
depuis la décision initiale annule l'action (`TOCTOU_REVALIDATION_FAILED`).

### I-06 — Registre fermé, versionné et default-deny

- Capacité inconnue, inactive, expirée ou mauvaise version = refus.
- Le registre contient des références internes vers des handlers codés ; aucun
  import dynamique ni routage libre n'est accepté.
- Les capacités modifiant flags, compte, garde de risque, policy, registre,
  approvals, kill-switch ou secrets sont absentes du registre Hermes.
- B0/C0 n'ajoute **aucune capacité d'ordre**. C1 reste shadow. Toute capacité PAPER
  ou DEMO ultérieure exige un lot et un go distincts.

### I-07 — Risque et protection indépendants du cerveau

La panne de Hermes, de l'EventPlane, du Cortex ou du gateway interdit les nouvelles
actions issues du cerveau mais ne neutralise jamais les protections déterministes
locales. Stops déjà posés, kill-switch et actions strictement réductrices de risque
peuvent continuer sans LLM selon une policy codée et testée. Hermes ne peut pas
réarmer un circuit-breaker ou augmenter une limite de risque.

### I-08 — Identité instrument fail-closed

Tout instrument utilisé par un événement décisionnel, une proposition ou un sink
doit être résolu par le référentiel canonique versionné. Instrument inconnu,
mapping ambigu, venue inconnue, métadonnée de précision/lot absente ou statut non
tradable = refus. Aucun fallback implicite vers `cfd` n'est admissible.

### I-09 — Données causales, fraîches et traçables

Une décision ne peut s'appuyer que sur des données closes, ordonnées, finies,
horodatées et assez fraîches pour la policy. Chaque fait expose provenance, temps
d'effet et version. Le Cortex est une projection, pas une source autoritaire ; un
composant stale ou manquant rend la décision `NO_DECISION` si la policy le requiert.

### I-10 — Séparation data plane / control plane

L'EventPlane transporte des faits et des résultats d'audit. Une `Proposal` est
soumise directement au CommandGateway via une interface dédiée. Publier un payload
ressemblant à une commande ne provoque aucun effet. Le gateway peut republier ses
résultats comme faits, jamais consommer une « commande » depuis le bus.

### I-11 — Persistance avant acquittement, aucune perte silencieuse

Un publish est réussi uniquement après commit durable. Échec, saturation, conflit
d'idempotence ou corruption sont retournés explicitement au producteur et exposés
dans sa santé. C0 peut rester sans influence décisionnelle, mais il n'avale jamais
une erreur de publication.

### I-12 — Au-moins-une-fois + idempotence obligatoire

Le plan garantit une livraison **au moins une fois**, pas exactement une fois. Les
producteurs dédupliquent par clé d'idempotence ; les consommateurs enregistrent leur
offset et appliquent idempotemment. Une répétition exacte renvoie le reçu original ;
une même clé avec un contenu différent est un incident bloquant.

### I-13 — Ordering défini, gaps visibles

L'ordre global est celui des commits (`global_offset`). L'ordre métier est garanti
par `stream_id` et `stream_seq`. Aucun consommateur ne déduit l'ordre des timestamps.
Un saut de séquence, un offset manquant ou une chaîne de hash rompue dégrade la
projection concernée ; aucun rattrapage silencieux.

### I-14 — Replay sans double effet

Le replay reconstruit uniquement des projections/idempotents. Il ne réémet jamais
un ordre et n'invoque jamais le gateway. Un résultat broker `UNKNOWN` n'est jamais
retried à l'aveugle : il est réconcilié auprès du sink par la même clé métier.

### I-15 — Schémas stricts et évolutifs

Les champs réservés de l'enveloppe ne sont pas surchargeables. Le payload est validé
contre le schéma exact de `event_type`; clés inattendues, version future, NaN/Inf,
types ambigus et timestamp naïf sont refusés. Une rupture incompatible crée un
nouveau type/version ; pas de mutation rétroactive des événements.

### I-16 — Audit immuable et explicable

Chaque proposition, décision de policy, refus, dispatch, résultat et réconciliation
porte ses IDs, versions, reason codes et références d'état. Les logs ne peuvent pas
transformer un échec en succès. Les événements ne sont ni modifiés ni supprimés en
B0 ; les corrections sont de nouveaux événements liés par `causation_id`.

### I-17 — Secrets et approvals hors données LLM

Aucun secret, token, clé, passphrase, cookie ou credential n'entre dans l'EventPlane,
le Cortex, une mémoire Hermes, une justification ou le bus de collaboration. Une
approval est authentifiée hors de la proposition, liée au digest exact de l'action,
à une expiration et à un nonce ; Hermes ne peut ni la fabriquer ni l'élargir.

### I-18 — Apprentissage hors ligne, promotion gouvernée

Hermes peut mémoriser, comparer et proposer des hypothèses. Il ne peut modifier live
une policy, une stratégie, le registre ou un seuil. Toute promotion d'apprentissage
est versionnée, testée offline/shadow, soumise à M2 si décisionnelle, revue et
approuvée explicitement par Florent.

## 2. EventPlane control-grade — contrat B0

### 2.1 Enveloppe canonique immuable

Les producteurs créent un `EventDraft`. Le store attribue atomiquement
`event_id`, `recorded_at`, `global_offset`, `stream_seq`, `prev_event_hash` et
`event_hash`, puis retourne un `StoredEvent` frozen.

```json
{
  "schema_version": 1,
  "event_id": "uuid-v4",
  "event_type": "confluence.evaluation.completed.v1",
  "occurred_at": "2026-07-19T07:30:00.123456Z",
  "recorded_at": "2026-07-19T07:30:00.130000Z",
  "global_offset": 1842,
  "stream_id": "engine.confluence|instrument:BTCUSD",
  "stream_seq": 91,
  "source": {
    "component": "core.confluence_demo_engine",
    "instance_id": "runtime-boot-uuid",
    "producer_version": "git-or-build-id"
  },
  "idempotency_key": "confluence:decision-id:v1",
  "partition_key": "instrument:BTCUSD",
  "correlation_id": "cycle-or-trace-uuid",
  "causation_id": null,
  "scope": {
    "operating_mode": "OBSERVE",
    "account_ref": "axi-demo",
    "instrument_id": "BTCUSD",
    "venue": "crypto"
  },
  "classification": "INTERNAL",
  "payload": {
    "decision_id": "stable-business-id",
    "as_of": "2026-07-19T07:15:00Z",
    "state_version": "confluence/1.1.0",
    "result": "NO_DECISION",
    "reason_codes": ["INSUFFICIENT_PILLARS"]
  },
  "payload_sha256": "hex-sha256",
  "prev_event_hash": "hex-sha256-or-null",
  "event_hash": "hex-sha256"
}
```

Contraintes normatives :

| Champ | Règle |
|---|---|
| `schema_version` | entier exact `1` pour B0 |
| `event_id` | UUIDv4 généré par le store ; jamais fourni par Hermes |
| `event_type` | `^[a-z][a-z0-9_.-]{2,127}\.v[1-9][0-9]*$` |
| `occurred_at` | UTC avec timezone, microsecondes ; temps du fait, immuable |
| `recorded_at` | UTC attribué dans la transaction ; ne définit pas la causalité métier |
| `global_offset` | entier monotone de commit, unique dans le store |
| `stream_id` | `{source.logical_name}|{partition_key}`, max 192 caractères |
| `stream_seq` | entier contigu, commence à 1, unique par stream |
| `source` | structure stricte ; `component` stable, `instance_id` par boot |
| `idempotency_key` | 1..192 caractères, stable sur retry, unique par `source.component` |
| `partition_key` | ordre métier ; `instrument:<canonical_id>` recommandé |
| `correlation_id` | regroupe un cycle/trace ; UUID ou ID opaque borné |
| `causation_id` | `event_id` du fait causal, ou null |
| `scope` | structure stricte ; jamais de secret ni compte choisi par LLM |
| `classification` | `PUBLIC`, `INTERNAL` ou `SENSITIVE_METADATA`; pas de `SECRET` |
| `payload` | objet JSON, schéma typé, max 256 KiB canonique, profondeur max 16 |
| hashes | SHA-256 sur JSON canonique UTF-8 ; chaîne par stream, détection d'altération |

JSON canonique B0 : UTF-8, clés triées, séparateurs compacts, `ensure_ascii=False`,
`allow_nan=False`. Le hash porte tous les champs immuables sauf `event_hash`.

### 2.2 API Python minimale à implémenter

```python
@dataclass(frozen=True)
class EventSource:
    component: str
    instance_id: str
    producer_version: str

@dataclass(frozen=True)
class EventScope:
    operating_mode: Literal["OBSERVE", "PAPER", "DEMO"]
    account_ref: str | None
    instrument_id: str | None
    venue: str | None

@dataclass(frozen=True)
class EventDraft:
    event_type: str
    occurred_at: datetime
    source: EventSource
    idempotency_key: str
    partition_key: str
    scope: EventScope
    payload: Mapping[str, JsonValue]
    correlation_id: str | None = None
    causation_id: str | None = None
    classification: str = "INTERNAL"

@dataclass(frozen=True)
class PublishReceipt:
    event_id: str
    global_offset: int
    stream_id: str
    stream_seq: int
    duplicate: bool
    event_hash: str

class EventPlane:
    def publish(self, draft: EventDraft) -> PublishReceipt: ...
    async def publish_async(self, draft: EventDraft) -> PublishReceipt: ...
    def read(self, *, after_offset: int, limit: int,
             event_types: tuple[str, ...] = ()) -> tuple[StoredEvent, ...]: ...
    def ack(self, *, consumer_id: str, global_offset: int) -> None: ...
    def consumer_offset(self, consumer_id: str) -> int: ...
    def record_failure(self, *, consumer_id: str, event_id: str,
                       reason_code: str, detail: str) -> None: ...
    def verify_integrity(self, *, stream_id: str | None = None) -> IntegrityReport: ...
    def health(self) -> EventPlaneHealth: ...
```

`publish_async` attend le commit durable (par exemple via `asyncio.to_thread`) ; il
ne place pas l'événement dans une queue volatile avant de répondre.

### 2.3 Stockage autoritaire B0 : SQLite

Fichier dédié recommandé : `data/control_event_plane/events-v1.sqlite3` avec
permissions locales minimales. SQLite est le store autoritaire ; un export NDJSON
est un artefact d'audit/reprise, pas une seconde vérité.

Réglages à l'ouverture : `journal_mode=WAL`, `synchronous=FULL`,
`foreign_keys=ON`, `busy_timeout` borné. Une seule transaction `BEGIN IMMEDIATE`
alloue la séquence, insère l'événement et commit avant acquittement.

```sql
CREATE TABLE metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE streams (
  stream_id TEXT PRIMARY KEY,
  last_seq INTEGER NOT NULL CHECK (last_seq >= 0),
  last_event_hash TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE events (
  global_offset INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  schema_version INTEGER NOT NULL CHECK (schema_version = 1),
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  stream_id TEXT NOT NULL,
  stream_seq INTEGER NOT NULL CHECK (stream_seq > 0),
  source_component TEXT NOT NULL,
  source_instance_id TEXT NOT NULL,
  producer_version TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  partition_key TEXT NOT NULL,
  correlation_id TEXT,
  causation_id TEXT,
  scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
  classification TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  payload_sha256 TEXT NOT NULL,
  prev_event_hash TEXT,
  event_hash TEXT NOT NULL,
  UNIQUE (stream_id, stream_seq),
  UNIQUE (source_component, idempotency_key),
  FOREIGN KEY (causation_id) REFERENCES events(event_id)
);

CREATE INDEX events_type_offset ON events(event_type, global_offset);
CREATE INDEX events_stream_seq ON events(stream_id, stream_seq);
CREATE INDEX events_correlation ON events(correlation_id);

CREATE TABLE consumer_offsets (
  consumer_id TEXT PRIMARY KEY,
  global_offset INTEGER NOT NULL CHECK (global_offset >= 0),
  updated_at TEXT NOT NULL
);

CREATE TABLE consumer_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  consumer_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  attempt INTEGER NOT NULL CHECK (attempt > 0),
  reason_code TEXT NOT NULL,
  detail TEXT NOT NULL,
  failed_at TEXT NOT NULL,
  resolved_at TEXT,
  UNIQUE (consumer_id, event_id, attempt),
  FOREIGN KEY (event_id) REFERENCES events(event_id)
);
```

Algorithme transactionnel de `publish` :

1. Valider enveloppe et payload avant I/O.
2. Canonicaliser le payload et calculer `payload_sha256`.
3. `BEGIN IMMEDIATE`.
4. Chercher `(source_component, idempotency_key)` :
   - même type/stream/occurred_at/scope/payload hash : retourner le reçu existant
     avec `duplicate=true`, sans consommer de séquence ;
   - contenu différent : rollback et `IDEMPOTENCY_CONFLICT`.
5. Lire/créer `streams`, allouer `last_seq + 1`, récupérer le hash précédent.
6. Attribuer UUID, temps enregistré, calculer le hash complet, insérer `events`.
7. Mettre à jour `streams`, commit, puis seulement retourner le reçu.
8. Sur erreur : rollback, exception typée, health `DEGRADED`; jamais `logger.debug`
   seul, jamais de succès synthétique.

### 2.4 Garanties de consommation et replay

- Un consumer lit strictement `global_offset > consumer_offset`, en ordre croissant.
- Il applique l'événement idempotemment, puis avance son offset. Pour une projection
  SQLite, application + offset doivent partager la même transaction.
- Sur erreur, l'offset n'avance pas. Après un nombre borné d'essais, l'incident est
  inscrit dans `consumer_failures`; la projection est `DEGRADED`, pas contournée.
- Le replay repart d'un offset choisi vers une projection vide ou isolée. Il n'efface
  pas la projection active avant comparaison de digest et validation.
- Le lag (`head_offset - consumer_offset`), l'âge du dernier événement, les gaps,
  échecs et conflits d'idempotence sont exposés au Cortex.
- B0 ne supprime rien. Une future rétention exigera archive atomique, manifeste de
  hashes, watermark de tous les consumers et procédure de restauration testée.

### 2.5 Registre de types initial pour C0

Le registre de schémas est fermé dans le code. C0 publie uniquement des faits après
mise à jour réussie de l'état moteur :

| `event_type` | `partition_key` | Payload obligatoire |
|---|---|---|
| `confluence.evaluation.completed.v1` | instrument | `decision_id`, `as_of`, `state_version`, `result`, `reason_codes`, `data_valid` |
| `consensus.observation.updated.v1` | instrument | `observation_id`, `as_of`, `state_version`, `status`, `inputs`, `decision_capability=false` |
| `leadlag.observation.updated.v1` | paire+TF | `observation_id`, `as_of`, `state_version`, `timeframe`, `leader`, `follower`, `metrics`, `m2_eligible=false` |
| `emotion.observation.updated.v1` | instrument | `observation_id`, `as_of`, `state_version`, `label`, `valence`, `arousal`, `decision_capability=false` |
| `engine.cycle.completed.v1` | moteur | `cycle_id`, `started_at`, `ended_at`, `status`, `counts`, `error_codes` |
| `engine.health.changed.v1` | moteur | `previous`, `current`, `reason_codes`, `last_good_at` |
| `execution.outcome.observed.v1` | instrument | `attempt_id`, `status`, `sink_ref`, `broker_ref?`, `reason_codes`; audit factuel seulement |

Les payloads `consensus`, `leadlag` et `emotion` portent explicitement leur absence
d'autorité décisionnelle actuelle. Pas de type générique `COMMAND`, `ACTION` ou
`ORDER_REQUEST` dans l'EventPlane.

Clés d'idempotence C0 : utiliser d'abord l'ID métier stable existant. S'il n'existe
pas encore, employer le digest déterministe
`sha256(event_type | source.component | partition_key | occurred_at | payload_sha256)`.
Un compteur mémoire seul ou un UUID recréé à chaque retry est interdit.

### 2.6 Politique d'erreur C0 (miroir)

C0 ne change ni résultat moteur ni exécution existante. Après un changement d'état
réussi, il publie et attend le reçu. Si la publication échoue :

1. le cycle garde son résultat métier préexistant ;
2. la santé du producteur devient `EVENT_PUBLISH_FAILED` avec reason code stable ;
3. l'erreur est remontée au superviseur et au Cortex, sans payload sensible ;
4. aucun consumer ne considère la projection complète tant que le gap persiste ;
5. aucun retry infini dans l'event loop ; reprise bornée avec la même idempotency key.

Avant toute utilisation décisionnelle future, l'outbox devra être atomique avec le
changement d'état autoritaire concerné. B0/C0 en miroir mesure précisément ce gap
avant de prétendre à cette garantie.

## 3. CommandGateway efférent — contrat

### 3.1 Proposal non fiable

```json
{
  "proposal_schema_version": 1,
  "proposal_id": "uuid-v4",
  "created_at": "2026-07-19T07:31:00Z",
  "expires_at": "2026-07-19T07:31:15Z",
  "principal": {
    "kind": "HERMES",
    "principal_id": "hermes-local",
    "model_id": "opaque-model-version",
    "prompt_version": "sha256-or-version"
  },
  "capability_id": "run_observation_scan",
  "capability_version": 1,
  "requested_mode": "OBSERVE",
  "params": {},
  "idempotency_key": "hermes:proposal-business-key",
  "correlation_id": "trace-uuid",
  "context_refs": {
    "event_ids": ["uuid"],
    "cortex_projection_version": "offset:1842",
    "policy_version_expected": "policy/1.0.0"
  },
  "justification": "texte non fiable, borné et non exécutable"
}
```

Interdits dans une proposition : URL, méthode HTTP, handler, module, fonction,
commande shell, chemin libre, token, approval, compte/login effectif, override de
mode, règle de risque, volume broker brut, policy inline ou code.

### 3.2 Entrée de registre fermée

```python
@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    version: int
    status: Literal["ACTIVE", "DISABLED", "RETIRED"]
    effect_class: Literal[
        "READ", "OBSERVE", "PAPER_MUTATE", "DEMO_MUTATE", "RISK_REDUCE"
    ]
    params_schema_id: str
    allowed_modes: frozenset[str]
    handler_id: str                 # résolution interne statique seulement
    required_policy_version: str
    required_m2_evidence: str | None
    approval_class: str | None
    max_ttl_ms: int
    timeout_ms: int
    rate_limit_id: str
    idempotency_scope: str
    requires_sink_revalidation: bool
```

À chaque démarrage, le registre calcule un digest de son contenu. Une proposition
est liée à une version exacte ; aucun « latest » implicite. Le mapping
`handler_id -> callable` est construit dans le code et non depuis les données.

### 3.3 Pipeline normatif

1. **Authenticate** : identité locale du principal établie par le transport de
   confiance, jamais par le JSON seul.
2. **Persist proposal received** : journal efférent durable distinct ; le gateway
   émet ensuite un fait d'audit vers l'EventPlane si celui-ci est disponible.
3. **Parse strict** : schéma exact, tailles, types, TTL, horloge, clés interdites.
4. **Deduplicate** : même principal + idempotency key + digest retourne le résultat
   antérieur ; digest différent = `IDEMPOTENCY_CONFLICT`.
5. **Resolve capability** : ID/version exacte, statut ACTIVE, params stricts.
6. **PolicyKernel** : décision pure `ALLOW | DENY | NO_DECISION` avec reason codes.
7. **Approval binding** : si requise, approval externe liée au digest exact,
   capability/version, mode, TTL et nonce ; jamais transportée par Hermes.
8. **Issue one-shot authorization** : token interne opaque, court, consommable une
   fois, lié au digest de proposition, policy, état, compte attendu et capability.
9. **Dispatch internal handler** : aucune destination fournie par la proposition.
10. **Sink revalidation** : relire compte/mode/risque/kill-switch/état effectif et
    consommer atomiquement l'autorisation avant effet.
11. **Record outcome** : `SUCCEEDED`, `REJECTED` ou `UNKNOWN`, avec reason codes et
    références. Un timeout n'est jamais converti en succès ni retried aveuglément.
12. **Publish audit facts** : received/denied/dispatched/outcome deviennent des faits
    immuables, sans créer de boucle de commande.

### 3.4 Checks minimaux du PolicyKernel

Le kernel est déterministe, versionné, sans appel LLM et sans réseau. Il refuse si
un seul check requis n'est pas prouvé :

- principal et capability autorisés ; paramètres exacts ; TTL et nonce valides ;
- mode demandé compatible avec capability et mode runtime de confiance ;
- combinaison compte/mode permise par la matrice (réel=PAPER, DEMO=compte DEMO) ;
- instrument canonique actif, non ambigu et compatible avec la venue ;
- policy attendue = policy active ; registre/digest attendus identiques ;
- événements/projection requis présents, sans gap, frais et assez frais ;
- stratégie/preuve M2 éligible lorsque l'action est décisionnelle ;
- approval valide lorsqu'exigée ; rate limit et budget d'action disponibles ;
- kill-switch non déclenché ; risque et exposition dans les limites ;
- idempotency key jamais consommée par un effet incompatible.

`NO_DECISION` et `DENY` ne dispatchent rien. Le texte de justification n'entre dans
aucun calcul d'autorisation.

### 3.5 Revalidation obligatoire au sink

Pour toute mutation PAPER/DEMO future, le handler transmet au sink un
`AuthorizedCommand` interne, jamais la Proposal brute. Le sink vérifie :

- signature/digest interne, expiration et usage unique de l'autorisation ;
- identité réelle de la session broker et compte attendu ;
- mode runtime issu de la configuration de confiance ;
- symbole broker résolu depuis l'instrument canonique ;
- tick/lot/précision, volume calculé côté déterministe, SL/TP et marché ;
- kill-switch, marge, exposition, perte journalière et limites au moment T ;
- clé d'idempotence d'exécution dans le journal du sink.

Un échec produit un refus durable. Si l'appel broker a peut-être franchi la frontière
mais que l'ACK est perdu, statut `UNKNOWN` puis réconciliation par identifiant broker
et idempotency key — **jamais un second ordre automatique**.

### 3.6 État des capacités par palier

| Palier | Capacités Hermes autorisables | Effet trading |
|---|---|---|
| B0/C0 actuel | aucune nouvelle capacité ; perception EventPlane/Cortex | aucun |
| C1 shadow | `READ`/`OBSERVE`, propositions journalisées non dispatchées | aucun |
| C2 PAPER | allowlist PAPER séparée, tests de panne/replay/TOCTOU + go | paper seulement |
| C3 DEMO | allowlist DEMO séparée, M2 + go Florent distinct + mur sink | démo seulement |
| Réel | aucune capacité d'ordre | interdit |

## 4. Reason codes stables minimaux

`SCHEMA_UNKNOWN`, `SCHEMA_INVALID`, `RESERVED_FIELD_OVERRIDE`,
`PAYLOAD_NOT_CANONICAL`, `IDEMPOTENCY_CONFLICT`, `STORE_UNAVAILABLE`,
`STORE_CORRUPT`, `SEQUENCE_GAP`, `HASH_CHAIN_BROKEN`, `CONSUMER_LAGGING`,
`PROJECTION_STALE`, `CAPABILITY_UNKNOWN`, `CAPABILITY_DISABLED`,
`CAPABILITY_VERSION_MISMATCH`, `PARAMS_INVALID`, `MODE_FORBIDDEN`,
`ACCOUNT_MISMATCH`, `REAL_ACCOUNT_ORDER_FORBIDDEN`, `INSTRUMENT_UNKNOWN`,
`INSTRUMENT_AMBIGUOUS`, `POLICY_VERSION_MISMATCH`, `M2_EVIDENCE_MISSING`,
`APPROVAL_REQUIRED`, `APPROVAL_INVALID`, `TTL_EXPIRED`, `RATE_LIMITED`,
`KILL_SWITCH_ACTIVE`, `RISK_LIMIT_EXCEEDED`, `STATE_CHANGED`,
`TOCTOU_REVALIDATION_FAILED`, `SINK_REJECTED`, `SINK_TIMEOUT_UNKNOWN`.

## 5. Critères d'acceptation B0/C0 avant GO suivant

Tests obligatoires et déterministes :

1. override de `type/ts/seq/source` par payload refusé ; NaN/Inf refusés ;
2. publish réussi uniquement après réouverture du store et lecture de l'événement ;
3. retry exact retourne même event/offset/seq ; retry divergent = conflit ;
4. séquences contiguës sous concurrence et ordre de commit reproductible ;
5. crash simulé avant/après commit : zéro ACK fantôme, zéro doublon au retry ;
6. replay complet produit le même digest de projection ; replay n'invoque aucun sink ;
7. offset consumer n'avance pas après exception ; failure visible ;
8. corruption/gap/hash cassé détecté et Cortex `DEGRADED` ;
9. panne disque/lock/saturation remontée au producteur, jamais avalée ;
10. C0 publie les types fermés avec IDs métier et flags observationnels corrects ;
11. aucune dépendance de décision ou d'exécution vers B0/C0 (`mirror only`) ;
12. unknown capability, URL/handler injecté, stale state et mode inconnu refusés ;
13. changement de compte entre PolicyKernel et sink refusé ;
14. même commande/retry ne peut produire qu'un effet ; timeout => réconciliation ;
15. compte réel + toute demande d'ordre = refus inconditionnel ;
16. panne Hermes/EventPlane/gateway ne désactive pas kill-switch/protections locales.

## 6. Séquence d'implémentation recommandée à Claude

1. **B0a** : types frozen, canonicalisation, registre de schémas et validations.
2. **B0b** : store SQLite transactionnel, idempotence, hashes, read/ack/replay/health.
3. **B0c** : tests de crash, concurrence, corruption, replay et observabilité.
4. **C0a** : publisher miroir `confluence` et heartbeat, sans effet métier.
5. **C0b** : `consensus`, `leadlag`, puis `emotion`, toujours observationnels.
6. **E0b** : Cortex expose head offset, offsets/lag, fraîcheur et état des projections.
7. Revue Codex + mesure de pertes/lag sur durée bornée avant tout C1.

Chaque édition de symbole runtime devra être précédée de son impact GitNexus. Le
FTS GitNexus est actuellement dégradé et les recherches conceptuelles de cette revue
n'ont retourné aucun flux ; cela ne remet pas en cause les impacts déjà établis mais
impose de continuer avec `context`/impact ciblé ou le fallback structurel explicite.

## Décision de conception

**GO pour implémenter B0/C0 strictement en miroir selon ce contrat. BLOCK tout
CommandGateway actif, toute capacité d'ordre, tout flag et toute action broker.**
Le passage C1/C2/C3 reste soumis à tests de panne, revue indépendante, exigences M2
applicables et go explicite de Florent à chaque élargissement.
