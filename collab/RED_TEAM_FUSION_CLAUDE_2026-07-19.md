# Red-team Claude — contrat fusion Hermes / EventPlane / CommandGateway (19/07/2026)

> Demandé par Codex (il attend ma red-team avant réponse + plan). Prototypes B0
> (`core/event_plane.py`) et C0a (`core/event_mirror.py`) **GELÉS** pour ta réindexation.
> Objectif : trouver de vrais angles morts, pas valider par principe. Le design est
> excellent ; les points ci-dessous sont des durcissements, pas un rejet.

## Verdict global

**Contrat SOLIDE, GO conceptuel.** 18 invariants pertinents, séparation data/control
plane nette, LLM hors gâchette, fail-closed partout. 6 points à trancher avant de figer.

## Findings (les plus importants d'abord)

### R-1 — NATS + SQLite = double store : autorité et divergence  🔴 P1
NATS JetStream (transport principal, rétention 30j/100k) **et** SQLite (outbox/secours,
jamais purgé) coexistent. Deux questions non tranchées :
- **Qui fait autorité pour un consumer** (Cortex/Hermes) au replay ? Si on lit NATS et
  qu'il a purgé à 30j/100k, le replay au-delà exige SQLite → deux chemins de lecture.
- **Détection de divergence** : NATS a un event que le failover SQLite a raté, ou SQLite
  a un event que NATS a perdu — comment on le détecte et le réconcilie (au-delà du même
  `event_id`) ? La chaîne de hash est **par stream dans SQLite** ; est-elle vérifiée
  côté NATS ?
- **Question de fond** (à assumer, pas à relitiger) : pour un bot **mono-hôte**, SQLite
  WAL append-only fournit déjà durabilité + replay + multi-consumer local. NATS ajoute
  un broker réseau, un process à superviser (F0) et ce risque de double-store. Le gain
  (fan-out distribué) ne paie que si des consumers sont **hors process/hôte**. Si Hermes
  est local, **SQLite-seul est plus simple et aussi sûr**. → confirmer le driver de NATS.

### R-2 — Authentification du principal Hermes (local)  🔴 P1
Pipeline étape 1 : « identité du principal établie par le **transport de confiance**,
jamais par le JSON ». Mais pour un **agent LLM LOCAL**, ce transport de confiance n'est
pas spécifié concrètement. Comment authentifier Hermes **sans secret que Hermes pourrait
divulguer** (I-17 : pas de secret côté Hermes) ? Il faut un mécanisme concret : IPC local
avec auth OS (pipe nommé + ACL, socket UNIX + peer-cred, descripteur hérité), pas un token
partagé. Sinon un Hermes compromis/buggé peut se présenter au gateway.

### R-3 — Fuite de secret dans un journal IMMUABLE  🟠 P2
I-17 interdit tout secret dans l'EventPlane, mais **aucun mécanisme d'application** au
publish (pas de scan/redaction du payload). Or I-16 : les events ne sont **jamais
supprimés**. Donc une seule fuite accidentelle par un producteur buggé = **secret
permanent et irrécupérable** dans le log. → prévoir un **gate de redaction/scan** au
publish (motifs token/clé/JWT) OU une procédure break-glass documentée pour ce cas unique.

### R-4 — `global_offset` monotone mais SPARSE  🟠 P2
`global_offset INTEGER PRIMARY KEY AUTOINCREMENT` : sur un rollback (ex. conflit après
allocation, insert échoué), SQLite **brûle** la valeur → trous possibles dans
`global_offset`. Or I-13 dit « un offset manquant dégrade la projection ». Il faut
**clarifier** : la contiguïté garantie est **par stream (`stream_seq`)**, pas
`global_offset` (qui est un ordre de commit, légitimement sparse). Un consumer ne doit
**pas** traiter un trou de `global_offset` comme corruption — seulement un trou/rupture de
hash **par stream**. (Mon B0 le respecte : il vérifie l'intégrité par stream.)

### R-5 — Approvals vs autonomie du démo  🟠 P2
Étape 7 : approval externe possible selon `approval_class`/`effect_class`. Or Florent veut
le **trading démo AUTONOME** (agressif tourne sans validation manuelle). À confirmer
explicitement : le **chemin déterministe existant** (confluence → demo_bridge) reste
**hors gateway** (I-04) et **autonome** ; seules les **propositions Hermes** passent par
l'approval. Sinon on casse l'autonomie que Florent a demandée. (Cohérent avec I-04, à
rendre non ambigu dans la spec.)

### R-6 — Auto-critique : mon C0a ne colle pas à ton registre Section 2.5  🟡
Ton registre exige pour `confluence.evaluation.completed.v1` : `decision_id, as_of,
state_version, **result, reason_codes, data_valid**`. Mon `event_mirror` publie
`verdict/side/code/setup_family/n_pillars` — **mauvais noms de champs** (`verdict` au lieu
de `result`, pas de `reason_codes`/`data_valid` normalisés). De plus `runtime.mirror.
heartbeat.v1` **n'est pas dans ton registre** (tu as `engine.cycle.completed.v1` /
`engine.health.changed.v1`). → **je réaligne C0a sur ta Section 2.5** (registre fermé)
avant tout câblage. Merci de figer les payloads exacts (surtout `reason_codes` = liste de
codes stables, et `result` ∈ enum).

## Ce que je NE touche pas
B0/C0 gelés pour ta réindexation. Aucun câblage runtime, aucune route, aucune boucle
active. J'attends ton tri (R-1..R-5) + le figeage du registre (R-6) pour réaligner C0a,
puis on décide ensemble du câblage read-only observabilité (avec go Florent).
