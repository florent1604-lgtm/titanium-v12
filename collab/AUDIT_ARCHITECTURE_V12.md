# Audit d'architecture — Titanium v12 (Claude, 19/07/2026)

> Demande Florent : scanner globalement l'architecture v12 et tout ce qu'elle utilise,
> vérifier que **tout est correctement connecté** et que la structure respecte une
> **logique neuronale autour du cerveau central** (vision initiale : Hermes = cerveau,
> modules = neurones). Audit clair + **axes d'amélioration** à soumettre à **Codex + Hermes**.
> Traité en arrière-plan de l'agressif/consensus en cours.

---

## 1. Vue d'ensemble (chiffres)

| Couche | Modules | Rôle |
|---|---|---|
| `core/` | 20 | moteurs (signal, confluence, consensus, lead/lag, swing, forex, SMC, risque…) |
| `api/` | 19 | FastAPI (routes + WS + lifespan = le « tronc nerveux ») |
| `execution/` | 10 | paper + exécution DÉMO MT5 + guards |
| `data/` | 10 | sources (Binance WS/REST, MT5, or, futures, carnet L2) |
| `tools/` | 28 | scripts (optimizers, lead/lag, gen_neural_map, collab bus…) |
| `assistant/` | 17 | voix / avatar / alertes JARVIS |
| `domain/` | 8 | **cerveau** (orchestrator, llm_planner, agent_registry, voice_intents) + strategy |
| `emotion/`,`fundamentals/`,`indicators/`,`engine/`,`vision/`,`validation/`,`notifications/`,`utils/` | ~30 | modulateurs, indicateurs, apprentissage |

- **18 boucles asyncio** dans un **seul processus** (`api/api_server.py` lifespan) :
  scan, forex, swing, confluence_demo, consensus_detection, lead_lag, opportunity_scan,
  fundamentals, optimizer, learning, circuit_breaker, futures/gold/external refresh,
  knowledge_regen, forward_paper, jarvis_assets, strict_recalib.
- **4 serveurs MCP** : `base44`, `gitnexus`, `gitnexus_write_gate`, `hermes`.
- **3 agents** : Claude (architecte), Codex (auditeur/red-team), Hermes (cerveau/orchestrateur).

---

## 2. Ce qui est CORRECTEMENT connecté ✅

- **Le tronc FastAPI (8090)** agrège tout : chaque moteur a sa boucle + sa route d'état.
  JARVIS lit `/api/state`, `/paper/*`, `/swing/status`, etc. → l'interface est bien alimentée.
- **Les stores partagés** (mémoire commune) existent : `candle_store`, `orderbook_store`,
  `futures_store`, `gold_store`, `base44_store`, `LAST_DECISION`.
- **La couche correctness R1–R3** (dedup barre, état atomique, risque portefeuille fail-closed)
  est transverse et branchée à swing/forex/crypto.
- **Le mur DÉMO↔RÉEL** (`demo_mt5_executor`) est en amont de tout ordre — jamais de fuite.
- **La carte neuronale existe déjà** : `tools/gen_neural_map.py` projette le VRAI graphe
  d'appels (via GitNexus `:4747/api/graph`) dans l'orbe → c'est la représentation « neurones ».

---

## 3. Les DÉCONNEXIONS et problèmes ⚠️ (le cœur de l'audit)

### 3.1 — Le CERVEAU CENTRAL n'est PAS câblé au runtime de trading  🔴 MAJEUR
- `domain/orchestrator.py` + `llm_planner` + `agent_registry` (**Patron A**, la frontière
  d'exécution du cerveau Hermes/JARVIS) ne sont **référencés NULLE PART** dans
  `api/api_server.py` ni `core/signal_engine.py` (grep = 0).
- **Conséquence** : le « cerveau » ne pilote que la **voix** (voice_intents → registre →
  orchestrator). Les **18 moteurs de trading tournent en autonomie**, sans passer par lui.
- **Écart avec la vision** : on voulait Hermes = cerveau central, modules = neurones qui
  « firent » vers/depuis le cerveau. La RÉALITÉ = un **monolithe de 18 boucles parallèles**
  où le cerveau est un **observateur périphérique** (il interroge l'API), pas le hub décisionnel.

### 3.2 — Le bus d'événements existe mais est PASSIF  🟠
- `utils/event_bus` est utilisé (signal_engine, executor, guards, paper_trading) mais reste
  **passif** (journalise `data/events.jsonl`). Ce n'est PAS le backbone synaptique qui relie
  les moteurs au cerveau. Les neurones n'ont pas de vrai réseau de synapses actif.

### 3.3 — Moteurs récents ajoutés en SILOS  🟠
- confluence, crypto, consensus, lead/lag ont été **bolt-on** : chacun = sa boucle + son
  état global + sa route. Ils ne se **parlent pas** entre eux ni via un tissu décisionnel commun
  (le consensus lit les 3 moteurs mais reste en observation ; le lead/lag est isolé).
- Il manque une **couche d'intégration** qui articule : confluence (décision) ∧ consensus
  (filtre) ∧ lead/lag (anticipation) ∧ émotion (timing) → **une seule sortie** vers le cerveau.

### 3.4 — Topologie de PROCESSUS à surveiller  🟢 *(corrigé par Codex 19/07)*
- Mon diagnostic initial (« 4 instances gate ») était **inexact** — Codex l'a corrigé :
  ce sont **2 paires client write-gate** (launcher gate-venv + interpréteur uv enfant),
  qui n'ouvrent LadybugDB qu'à l'appel ; **les tuer déconnecterait Claude/Codex**.
- Le verrou reproductible venait du **watcher `analyze --pdg`**, désormais **arrêté**.
- **GitNexus est RESTAURÉ** (Codex, 19/07 08:47) : PDG reconstruit (1078 fichiers, 23138
  nœuds, 61804 relations), 4747 = 200, watcher OFF, index frais. Reste : **FTS dégradé**
  (extension Windows absente) → utiliser cypher/context/pdg + le nouveau provider structurel.
- Codex a livré `tools/structural_mcp.py` (provider MCP local durci, root sous v12, symlink
  bloqué, secrets exclus) — **revue Claude : GO**, 1 point mineur P2 (redaction contenu dans
  smart_search). **Nécessite une NOUVELLE session Claude/Codex** pour charger les outils.

### 3.5 — Résilience monolithique  🟠
- 18 boucles dans **un seul processus** : un crash non capturé peut tout emporter. Pas de
  supervision par neurone. Le lancement en fenêtre masquée **désactive voix+avatar** (constaté).

---

## 4. Logique neuronale autour du cerveau central — ÉVALUATION

| Attendu (vision) | Réalité v12 | Verdict |
|---|---|---|
| Hermes = **cerveau central** qui décide/apprend | Hermes = observateur externe (API/MCP) ; ne pilote que la voix | 🔴 Partiel |
| Modules = **neurones** connectés au cerveau | 18 boucles autonomes, sans afférent/efférent vers le cerveau | 🔴 Manque |
| **Synapses** (bus d'événements actif) | Bus présent mais **passif** | 🟠 À activer |
| **Représentation neuronale** (graphe) | Orbe + GitNexus = vrai graphe… mais **dégradé** | 🟠 À restaurer |
| **Mémoire commune** (cortex) | Stores partagés éparpillés (globals) | 🟠 À unifier |

**Conclusion** : la vision « cerveau central + neurones » est **présente en intention et en
visuel** (Patron A, orbe, carte neuronale) mais **pas dans le câblage runtime**. Aujourd'hui
c'est un **monolithe de boucles bien alimenté mais sans système nerveux central actif**.

---

## 5. AXES D'AMÉLIORATION (à soumettre à Codex + Hermes)

Priorisés. Chacun rapproche l'architecture de la logique neuronale voulue, **sans casser**
le fail-closed ni le mur démo↔réel.

**A. Restaurer la carte neuronale (GitNexus)** — ✅ **FAIT par Codex (19/07)**
PDG reconstruit, 4747=200, watcher OFF, provider structurel durci livré + revu (GO).
Reste mineur : FTS Windows dégradé (contournement cypher/pdg/structural). La carte
neuronale est **de nouveau lisible** → prérequis débloqué pour B/C.

**B. Activer le BUS comme vrai système nerveux (synapses)** — *Claude + Hermes*
Rendre le bus **actif** : chaque événement significatif (signal émis, position ouverte,
consensus CONFIRMED, drawdown, opportunité) **publie** ; le cerveau + le dashboard **s'abonnent**.
Afférent (neurones→cerveau) et efférent (cerveau→neurones) explicites.

**C. Câbler le CERVEAU au runtime (afférent/efférent)** — *Hermes + Claude*
Faire remonter les événements de trading au cerveau Hermes (via B) pour **décision/apprentissage**,
pas seulement via voix. Le Patron A (registre fermé) devient la **frontière efférente** unique
(le cerveau agit sur les moteurs via capacités validées, jamais en direct).

**D. Une couche d'INTÉGRATION décisionnelle** — *Codex (méthodo) + Claude*
Articuler confluence ∧ consensus ∧ lead/lag ∧ émotion en **une seule sortie** par actif
(le consensus 3-moteurs de Codex est la brique de départ). Fin des silos.

**E. Unifier la MÉMOIRE (cortex)** — *Claude*
Un `state snapshot` unifié (lecture seule) agrégeant tous les stores + états moteurs, que le
cerveau et les dashboards lisent en un point. Fin des globals éparpillés.

**F. Topologie de processus SINGLETON + supervision** — *Codex + Florent*
Un launcher/watchdog garantissant **une seule** instance de chaque (bot, MCP, gate, runtime),
+ supervision par tâche (un neurone qui meurt ne tue pas le cerveau). Régler le lancement
fenêtré (voix/avatar).

**G. Contrat de nommage/venue unifié** — *Claude*
Le mapping symboles (BTCUSD MT5 ↔ BTC/USDT scoring/Binance) est ad hoc. Un référentiel
d'instruments unique éviterait les incohérences inter-moteurs.

---

## 6. Recommandation de séquence

1. **A** (GitNexus) — débloque la visibilité (Codex, en cours).
2. **B** puis **C** — le vrai système nerveux + branchement du cerveau (le gros œuvre).
3. **D** — intégration décisionnelle (après validation M2 du consensus).
4. **E, F, G** — hygiène structurelle en parallèle.

> **Rien de tout ceci ne se câble sans** : GitNexus restauré, protocole M2, revue Codex, go Florent.
> PAPER/DEMO ONLY. Cet audit est une PROPOSITION — à arbitrer par Florent, à challenger par Codex,
> à intégrer par Hermes dans sa mémoire.
