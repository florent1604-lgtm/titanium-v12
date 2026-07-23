# Contre-revue d'architecture Titanium v12 — Codex (19/07/2026)

> Mission `AUDIT_ARCHI_V12`, directive Florent : revue à trois avant toute
> exécution. **PAPER/DEMO ONLY. Aucun changement runtime, aucun ordre, aucun
> câblage décisionnel.**

## Verdict exécutif

**ACCORD sur le fait principal, avec deux corrections importantes.** Dans le
dépôt v12 indexé, Patron A (`orchestrator`, `agent_registry`, `llm_planner`) ne
se trouve sur aucun chemin d'appel du runtime de trading ni des sinks
d'exécution. GitNexus donne zéro appelant à `run_plan` et `plan_from_text` ;
`get_capability` n'est appelé que par `run_plan`, `map_intent`, `is_mutating` et
un test. Les recherches statiques ciblées ne trouvent aucun appel de
`run_plan()` hors de sa définition.

En revanche :

1. « il ne pilote que la voix » est trop affirmatif. Dans **ce dépôt**,
   `map_intent` a lui aussi zéro appelant GitNexus et aucune intégration
   non-test trouvée. Un consommateur JARVIS externe est possible, mais non
   prouvé par le graphe v12. La formulation démontrée est : **Patron A est une
   frontière d'exécution conçue et testée, mais sans caller runtime in-repo**.
2. Le remède ne doit pas être « mettre Hermes/LLM dans le chemin critique de
   chaque trade ». Un LLM central serait un point de panne, de latence et de
   non-déterminisme. Le centre sûr doit être un **noyau de politique
   déterministe** ; Hermes produit des observations et propositions bornées,
   jamais des appels directs aux moteurs ou exécuteurs.

Verdict de chantier : **GO conception/observation ; BLOCK tout câblage actif**
avant contrats, threat model, tests de panne, protocole M2 et go Florent.

## 1. Preuves indépendantes

### Patron A / cerveau

- GitNexus `context(run_plan)` : zéro entrant ; sorties seulement vers
  `_parse_plan`, `get_capability`, `validate_params`, `make_http_post`.
- GitNexus `context(plan_from_text)` : zéro entrant.
- GitNexus `context(map_intent)` : zéro entrant.
- GitNexus `context(get_capability)` : entrants limités à `run_plan`,
  `map_intent`, `is_mutating` et un test.
- Recherche statique dans `assistant/`, `api/`, `core/`, `domain/`,
  `execution/`, `utils/` : aucune invocation de `run_plan()` ou
  `plan_from_text()` hors définition.
- Les sinks DEMO restent directs : `forex_engine`, `swing_engine` et
  `confluence_demo_engine` appellent `demo_bridge.place_demo_async`, lequel
  mène au garde DEMO puis à `order_send`. Aucun passage par Patron A.

Conclusion : **cerveau non câblé au trading confirmé**. L'affirmation « câblé à
la voix » reste à prouver depuis le runtime JARVIS externe, si c'est bien lui
qui consomme ces fonctions.

### Event bus

Le bus n'est pas purement passif : `emit()` journalise, conserve une deque et
fait déjà un fan-out vers des queues. Mais il est **passif du point de vue de la
décision** : GitNexus montre un seul appelant de `subscribe()`,
`api/cockpit_routes.py::ws_events`. Aucun cerveau ni moteur décisionnel n'est
abonné.

Producteurs actuellement vus par GitNexus : `signal_engine`, `guards`,
`signal_manager`, `PaperExecutor`, `PaperEngine`. Cela ne couvre pas encore les
nouveaux silos confluence/consensus/lead-lag/émotion de manière contractuelle.

### Topologie asyncio

« 18 boucles » décrit au mieux des familles de boucles, pas le nombre réel de
tâches. `lifespan` contient au moins 19 créations fixes/conditionnelles, plus
une tâche WS par symbole, plus les tâches pouvant être créées dans
`start_orderbook_streams`, `start_titan` et le moteur d'alertes. Une route crée
aussi une optimisation ad hoc non ajoutée à la liste supervisée.

Autre nuance : une exception non récupérée dans **une Task asyncio** ne tue pas
normalement tout le processus ; elle peut faire mourir silencieusement ce
neurone. Le risque « tout tombe » vient plutôt d'un crash process/event loop,
d'une ressource partagée bloquée ou épuisée. Le défaut actuel est donc surtout
**absence de supervision et inventaire incomplet**, puis seulement le
monolithe comme domaine de panne.

## 2. Challenge des axes et nouvelle priorité

### A — GitNexus : fait, mais pas un prérequis runtime

Accord sur le statut : graphe/PDG utilisables, FTS dégradé clairement signalé.
La carte aide à auditer ; elle ne doit jamais devenir une dépendance du runtime
de trading.

### B — Event bus : à scinder, pas à « rendre actif » indistinctement

**Priorité haute en mode miroir seulement.** Le même bus ne doit pas mélanger
télémétrie et commandes. Deux plans sont nécessaires :

- `EventPlane` afférent, append-only, sans effet décisionnel ;
- `CommandGateway` efférent, synchrone du point de vue de l'autorisation,
  strictement adossé au registre fermé.

Le bus actuel n'est pas assez sûr pour devenir backbone : écriture disque
synchrone dans l'event loop, état mémoire local au processus, queues bornées
avec pertes silencieuses, exceptions avalées, aucune identité/sequence/schema,
pas de replay fiable ni d'idempotence, et le `**data` final peut écraser les
champs réservés `type`/`ts`. Il peut rester télémétrique pendant qu'un contrat
v2 est conçu ; **ne pas brancher une décision dessus en l'état**.

### C — Cerveau : afférent tôt, efférent très tard

Je sépare C en paliers :

1. **C0 observe-only** : Hermes lit une projection read-only et reçoit les
   événements ; aucune sortie runtime.
2. **C1 shadow proposals** : il émet des propositions auditées, comparées aux
   décisions déterministes, jamais exécutées.
3. **C2 PAPER approval** : seulement des capacités PAPER explicitement
   allowlistées, après tests de panne/rejeu/staleness.
4. **C3 DEMO borné** : go Florent distinct, protocole M2 et mur DEMO inchangé.

L'efférent ne doit accepter que `Proposal -> PolicyKernel -> AgentRegistry ->
handler`. Aucun moteur ne s'abonne à des « ordres du cerveau » sur le bus.

### D — Intégration : avant l'efférent, mais pas sous forme d'un AND fixe

Claude propose `confluence ∧ consensus ∧ leadlag ∧ emotion`. Ce n'est pas
justifié aujourd'hui : lead/lag a produit 0 paire M2 survivante et l'émotion est
observationnelle. Un AND les transformerait arbitrairement en veto, tandis
qu'un score les double-compterait possiblement avec des données corrélées.

La couche D doit être un **DecisionKernel déterministe et versionné**, testé
offline/shadow :

- invariants non négociables : données closes/fraîches, risque, mode, compte,
  kill-switch, admissibilité instrument ;
- stratégies M2 éligibles seulement ;
- modulateurs optionnels uniquement après preuve M2 de valeur incrémentale ;
- résultat explicable : `ALLOW`, `DENY`, `NO_DECISION`, reason codes et version
  de politique.

Le consensus existant est une bonne brique d'observation, pas encore une
autorité.

### E — State unifié : projection, jamais vérité absolue

Accord avec correction : un snapshot unifié est une **projection matérialisée**
avec `as_of`, provenance, version et fraîcheur par composant. Les vérités
autoritaires restent séparées : broker/MT5 pour positions et exécutions,
journal pour décisions, stores de marché pour observations. Un snapshot stale
ou partiel doit produire `UNKNOWN/NO_DECISION`, jamais une fausse certitude.

### F — Supervision : remonter plus tôt ; singleton par rôle, pas global

À traiter avant tout efférent actif. Il faut un registre de tâches, health,
heartbeat, politique de restart bornée, backoff, budget d'échecs et shutdown
attendu (`cancel` + `gather`). Les tâches ad hoc doivent aussi être suivies.

Le singleton concerne impérativement le **trading runtime/executor par compte**.
Il ne faut pas imposer « un seul MCP/gate » global : les paires client-enfant
Claude/Codex sont légitimes. Définir des scopes et ownership explicites.

### G — Référentiel instruments : remonter au tout début

Ce n'est pas de l'hygiène finale. Les clés des événements, du snapshot, de
l'idempotence, du risque et de M2 dépendent d'un identifiant canonique stable.
G doit précéder B v2/E/D : `instrument_id`, venue, symbole d'exécution, symbole
data/référence, classe, devise, timezone/session, précision/tick/lot, statut et
version du mapping. Inconnu ou ambigu = fail-closed.

## 3. Architecture B/C sûre proposée

```text
Moteurs/data/exécution
        |
        | événements factuels (jamais commandes)
        v
EventPlane durable -> projections read-only -> BrainView/Hermes
                                             |
                                             | Proposal non fiable
                                             v
                                      PolicyKernel déterministe
                                             |
                                   DENY ------+------ VALIDATE
                                                        |
                                             registre fermé unique
                                                        |
                                        handler codé et allowlisté
                                                        |
                                  garde risque/mode/compte/approval
                                                        |
                                            PAPER/DEMO executor
                                                        |
                                       ACK/REJECT redevient événement
```

### Contrat afférent minimal

Chaque événement porte au minimum : `schema_version`, `event_id`,
`event_type`, `source`, `instrument_id`, `venue`, `mode`, `observed_at`,
`effective_at`, `sequence`, `correlation_id`, `causation_id`, payload typé et
classification de sensibilité. Les clés réservées ne sont jamais surchargeables.

Garanties : outbox durable au point de changement d'état, livraison au moins une
fois, consommateurs idempotents, ordre défini par stream/instrument, replay,
dead-letter, métrique de lag, overflow explicite. Une perte ou une rupture de
schéma est visible et rend la projection concernée `DEGRADED/STALE`.

### Contrat efférent minimal

Hermes ne produit qu'une `Proposal` contenant : capability ID, paramètres,
mode demandé, state/policy versions, TTL, idempotency key, modèle/prompt version
et trace de justification. Il ne fournit ni URL, ni fonction, ni token, ni
approbation.

Le `PolicyKernel` valide avant le registre :

- capability connue et handler codé ;
- mode autorisé (`READ`, `OBSERVE`, `PAPER_MUTATE`, `DEMO_MUTATE`; pas seulement
  le couple trop grossier READ/MUTATE) ;
- preuve M2/policy version éligible ;
- snapshot frais et version attendue (anti-TOCTOU) ;
- TTL, nonce/idempotence, rate limit et limites par instrument ;
- approval séparée et authentifiée quand exigée ;
- kill-switch/risk gate et compte DEMO revalidés au dernier moment.

Le registre fermé reste **l'unique frontière de tout efférent venant du
cerveau**. Les approvals ne transitent pas dans la proposition et ne sont pas
contournables par un event subscriber. Les capacités d'ordre restent absentes
tant que M2 + go Florent ne les autorisent pas.

### Sémantique fail-closed en panne

- cerveau indisponible : aucune nouvelle action issue du cerveau ; observation
  déterministe possible ;
- EventPlane/projection stale : aucune nouvelle entrée ;
- PolicyKernel/registre indisponible : aucune nouvelle entrée ;
- protection locale : stops, fermeture de réduction de risque et kill-switch
  continuent sans attendre le LLM — **fail-closed asymétrique** ;
- ACK inconnu/timeout : état `UNKNOWN`, jamais retry aveugle d'un ordre ;
- redémarrage : replay idempotent, aucune double exécution.

## 4. Ce que l'audit initial a mal vu ou sous-estimé

1. **Le cerveau n'est peut-être même pas câblé à la voix in-repo.** À qualifier
   par une preuve du consommateur externe JARVIS.
2. **Le bus a déjà des abonnés actifs**, mais uniquement UI ; il n'est pas juste
   un fichier. Son problème est l'absence de contrat fiable/consommateur
   décisionnel, pas l'absence totale de fan-out.
3. **Le bus actuel peut perdre silencieusement et bloquer l'event loop** ; le
   promouvoir tel quel serait un P0 architectural.
4. **18 n'est pas le nombre de tâches.** Les WS par symbole et tâches internes/
   ad hoc élargissent le domaine à superviser.
5. **Une Task morte ne tue pas forcément le monolithe** ; elle peut surtout
   mourir sans restauration. Le risque process existe mais doit être formulé
   précisément.
6. **G et F ne sont pas une finition** : identité canonique et supervision sont
   des prérequis du contrôle.
7. **D ne peut pas être un AND des quatre modules** sans preuve statistique ;
   lead/lag est aujourd'hui négatif M2 et émotion non décisionnelle.
8. **« apprentissage du cerveau » est une mutation de politique.** Toute
   promotion d'un apprentissage doit être offline, versionnée, M2, revue et
   approuvée ; jamais de self-modification live.
9. **Le registre actuel est trop grossier pour des ordres futurs.** Un simple
   `allow_mutate=True` + token non vide côté orchestrateur délègue la vraie auth
   à l'endpoint, ce qui est correct en défense en profondeur, mais insuffisant
   comme modèle de politique complet. `reset_circuit_breaker` mérite notamment
   une classe d'approbation plus forte qu'une mutation ordinaire.
10. **Deux autorités d'exécution existent déjà conceptuellement** : les boucles
    déterministes appellent directement `demo_bridge`, tandis que le futur
    cerveau passerait par le registre. Il faut déclarer clairement si le
    registre est unique pour le cerveau seulement, ou introduire un
    `ExecutionGateway` commun sous le DecisionKernel. Aucun double chemin caché.

## 5. Séquence corrigée proposée

1. **P0 — invariants et inventaire** : data/control/execution planes, autorités,
   modes, threat model, catalogue exact des tâches et sinks. Documentation only.
2. **G — identité instruments** : contrat canonique, toujours read-only au départ.
3. **E0 + B0 — projection et événements v2 en miroir** : aucune influence sur
   les décisions ; comparer avec les états actuels et mesurer pertes/lag.
4. **F0 — supervision/ownership** : suivre toutes les tâches et garantir un seul
   executor par compte avant tout efférent.
5. **D0 — DecisionKernel offline/shadow** : intégrer seulement les preuves M2 ;
   lead/lag/émotion restent observationnels tant que non validés.
6. **C0/C1 — Hermes observe puis propose en shadow** : registre jamais invoqué
   automatiquement.
7. **C2 PAPER**, puis éventuellement **C3 DEMO** : chaque palier exige tests de
   panne/replay/TOCTOU, revue Codex, M2 et go Florent explicite.

## Conclusion à Florent et Claude

Le diagnostic de déconnexion est utile et confirmé, mais la bonne cible n'est
pas « un LLM au centre de 18 boucles ». La cible sûre est : **un centre de
politique déterministe et auditable, alimenté par des événements fiables ;
Hermes observe et propose ; le registre fermé autorise l'unique efférent du
cerveau ; les gardes locales protègent même quand le cerveau tombe**.

Je recommande donc de valider à trois les invariants et la séquence ci-dessus
avant d'écrire une ligne runtime. **BLOCK exécution/câblage actif à ce stade.**
