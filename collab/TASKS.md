# Tableau de tâches — Titanium v12

Statuts : `TODO` · `DOING` · `REVIEW` (revue croisée) · `DONE` (validé Florent) · `BLOCKED`

| # | Tâche | Owner | Statut | Critère de « fait » |
|---|-------|-------|--------|---------------------|
| C0 | Établir le canal de collaboration Claude⇄Codex | Claude | DONE | Round-trip prouvé + scaffold `collab/` + plan co-signé |
| — | **P0 sécurité** | | | |
| S1 | Binder l'API sur 127.0.0.1 | Claude | REVIEW | ✅ écoute 127.0.0.1 vérifié |
| S2 | **Auth fail-closed** sur toute mutation + retrait git push dashboard | Claude | REVIEW | ✅ 403 sans token / 200 avec ; push retiré. Revue Codex faite |
| S2b | Corriger trous revue Codex : webhook fail-closed + /paper/close | Claude | REVIEW | ✅ webhook secret vide→403 + compare_digest ; close protégé |
| S3 | Balayer les mutations restantes (forex/swing reset, optim/run, base44 push, fundamentals, context/regen, journal/approve, Titan) | Codex | REVIEW | routes mutantes inventoriées et protégées ; `/api/chat` reste opérationnel (sans mutation d’état) |
| — | **P1 correctness** | | | |
| R1 | Dédoublonnage par barre swing/forex | Claude | DOING | `bar_id` traité ; pas de ré-entrée même barre |
| R2 | Écritures atomiques + **verrou mono-écrivain** | Claude | TODO | temp+rename ; un seul écrivain par état |
| R3 | Risque portefeuille : cluster + **par stratégie + gross/net** | Claude | TODO | Plafonds appliqués avant 2e position |
| R4 | Contrat de données JARVIS (+ fix jarvis_agent.py) | Claude | TODO | champs alignés, score /16, fraîcheur |
| R5 | **Data gate commun** (barre close, source_ts, âge max, stale→no-trade) | Claude/Codex | TODO | Aucune décision sur donnée stale/ouverte |
| — | **P2 méthodologie** | | | |
| M1 | Fonction de stratégie pure partagée live↔backtest | Codex | REVIEW | contrat immuable + décision t→t+1 + tests déterministes livrés |
| M2 | Découpage 3 segments + PBO/Deflated Sharpe + seuil trades | Codex | REVIEW | dev/sélection/final verrouillés, bootstrap bloc, PBO/DSR et gate d'évidence livrés |
| X1 | Revue croisée de chaque lot Claude | Codex | TODO | `codex review` + note dans LOG.md |

*Mise à jour à chaque passage de statut. Décisions dans `LOG.md`.*

## Réservations actives

- **Codex / C0 extension** : `tools/collab_bus.mjs`, `collab/messages/README.md`,
  `collab/README.md` pour un canal fichier append-only et accusés de lecture.
- **Codex / S3** : audit puis modifications limitées aux routeurs de mutation restants ;
  aucun fichier déjà réservé par Claude ne sera modifié sans annonce dans `LOG.md`.
- **Codex / M1** : nouveaux modules et tests de stratégie pure, noms finalisés après
  cartographie des moteurs existants ; aucune modification de `core/swing_engine.py`
  ou `core/forex_engine.py` avant coordination.
- **Codex / M2** : nouveau harnais de validation et fixtures déterministes, sans
  remplacement des rapports historiques.

## Addendum de statut — 2026-07-10 13:50 CEST

Cet addendum prévaut sur les statuts historiques du tableau ci-dessus :

| # | Statut actuel | Décision |
|---|---------------|----------|
| S1/S2/S2b/S3 | DONE | Validés par Florent, selon LOG.md |
| M1/M2 | DONE | Validés par Florent, selon LOG.md |
| R1 | REVIEW | Revue Codex : corriger la concurrence de `scan_once` et ajouter la couverture forex |
| R2 | REVIEW | Atomicité acquise ; mono-écrivain inter-processus non démontré |
| R3 | DOING | Lot actif Claude |
| R6 | TODO | Remplacer progressivement le cerveau JARVIS/Gemini par Hermes comme cerveau principal et mémoire/orchestrateur ; Claude/Codex agents spécialisés via MCP/bus ; parité, fallback et rollback obligatoires avant bascule |
| X1 | DOING | Revue croisée R1/R2 transmise à Claude |

## Addendum de statut — 2026-07-10 23:31 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| M1B | DESIGN | Architecture validée par Florent et go Claude ; validation finale des scénarios encore attendue avant édition |
| R3 | REVIEW | Revue Codex `REQUEST CHANGES` : net absent, crypto exclu, NaN et état malformé autorisés fail-open |
| R4 | DESIGN | Claude délègue à Codex le contrat `TitaniumSnapshot v1` ; aucune édition de JARVIS hors dépôt |
| R6 | DESIGN | Hermes devient cerveau principal/mémoire/orchestrateur ; critères de parité, fallback et rollback à auditer avant bascule |

## Addendum de statut — 2026-07-11 08:42 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3 | REVIEW | Corrections fail-closed attendues de Claude avant nouvelle revue Codex |
| R4 | DESIGN | `TitaniumSnapshot v1` délégué à Codex ; fichiers à réserver après synchronisation Claude |
| R6 | REVIEW | Correctif asyncio fonctionnel, mais `REQUEST CHANGES — CRITICAL` : `hermes -z` contourne les approbations et l'environnement reste hérité |

## Addendum de statut — 2026-07-11 08:50 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3 | REVIEW | **rev.2 fail-closed LIVRÉE par Claude** : net signé + plafond \|net\| portefeuille, `RISK_INPUT_INVALID` (NaN/inf/0/side), `RISK_STATE_UNAVAILABLE` (état malformé), crypto paper agrégé, plafonds sur equity live ; 15/15 tests verts, bot 8090 redémarré — re-revue Codex attendue (LOG 11/07, bus `2d08106a`) |
| R6 | REVIEW | ACK Claude de l'audit CRITICAL ; lot **R6b** proposé : profil Hermes sans outils pour le chemin vocal JARVIS, env launcher nettoyé, kill switch testé, tests d'injection — arbitrage Florent requis avant toute édition JARVIS |

## Addendum de statut — 2026-07-11 (re-revue R3 rev.2 / DASH)

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3 | REVIEW | **REQUEST CHANGES Codex** : les 4 bloquants `462b1e62` sont corrigés, mais check puis insertion non atomiques entre swing/forex ; ajouter réservation/verrou portefeuille + test concurrent inter-moteurs. Preuve pytest non reproductible : venv pointe vers Python 3.12 supprimé. |
| DASH | DESIGN | Exigences non négociables consignées : provenance/fraîcheur visible, validation versionnée par stratégie, séparation crypto/forex/swing, orbe non autoritatif et mutations PAPER explicites, CSP stricte + offline fail-visible. |
| R6 | TEST | Décision Florent actée : Gemini retiré, Hermes garde ses outils, phase de test avant sécurisation ; R6b différé, threat review conservée au dossier. |

## Addendum de statut — 2026-07-11 09:20 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3c | DOING (Codex) | Délégation Florent : Codex implémente l'atomicité check+insertion portefeuille + test concurrent inter-moteurs ; Claude relecteur ; réservation levée sur les 2 sites `_open_position` |
| R4 | TODO (Codex) | Enchaîner après R3c : TitaniumSnapshot v1 + champs provenance DASH (source_ts/âge/LIVE-STALE-UNAVAILABLE, statut validation versionné) |
| DASH | DESIGN | Concertation à 3 terminée (exigences Codex + vision orbe Hermes au bus) ; design/HTML : Claude avec skill frontend-design ; données : Codex (R4) |
| R6 | TEST | Cutover Gemini→Hermes APPLIQUÉ et prouvé end-to-end (LOG 11/07) ; phase de test en cours, R6b différé sur décision Florent |

## Addendum de statut — 2026-07-11 09:24 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3c | REVIEW (Claude) | Implémentation Codex livrée : `check_and_insert` atomique sous verrou portefeuille, câblage swing/forex et test concurrent exactement une acceptée ; bus R3 `cbb03952-f2da-4898-8d95-82731057e49a` |
| R4 | NEXT (Codex) | Après clôture R3c : `TitaniumSnapshot v1`, provenance/fraîcheur `source/source_ts/âge/LIVE-STALE-UNAVAILABLE` par donnée et validation versionnée par stratégie |

## Addendum de statut — 2026-07-11 09:55 CEST (VALIDATION PRODUCTION PAPER)

Mandat Florent (« teste, contrôle et valide pour continuer ; passe en production ») :

| # | Statut actuel | Décision |
|---|---------------|----------|
| R1 | **DONE** | Dédup par barre + verrou de scan, tests concurrents verts, revue Codex intégrée |
| R2 | **DONE** | Écritures atomiques (jamais de JSON déchiré) ; mono-écrivain = bind port + kill zombie (décision Codex acceptée) |
| R3 (+R3c) | **DONE** | Fail-closed complet + **check_and_insert atomique portefeuille** (implémenté par Codex, relu par Claude) ; 16/16 tests verts ; bot 8090 redémarré dessus, MT5 data-only vérifié |
| R4 | DOING (Codex) | GO donné : TitaniumSnapshot v1 + provenance DASH (source_ts/âge/LIVE-STALE-UNAVAILABLE + statut validation versionné) |
| DASH | DESIGN → BUILD | Claude démarre la refonte (skill frontend-design) sur la base des exigences Codex + vision orbe Hermes |

## Addendum de statut — 2026-07-11 · R3c rev.3 (prévaut sur DONE ci-dessus)

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3c | **REVIEW (Claude)** | Reliquat découvert après validation swing/forex : `PaperEngine.open_position` crypto contournait le garde central. Correctif TDD livré : contrôle + mutation sous `check_and_insert`, instance crypto appelante explicite, refus sans effet ; régressions `36 passed`. Aucun redémarrage après cette rev.3. |
| R4 | NEXT (Codex) | Reprendre après verdict Claude sur R3c rev.3 afin de ne pas superposer correctness et contrat dashboard. |

## Addendum de statut — 2026-07-11 14:35 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| R3 | **DONE (rev.3)** | Codex a corrigé en TDD le contournement crypto du garde (preuve rouge/verte) ; verdict croisé Claude APPROVE, 36/36, bot 8090 redémarré dessus |
| R4 | DOING (Codex) | GO reconfirmé après rev.3 |
| DASH | SIMULATION | /orbe v3 (orbe neuronale réelle) en attente de validation visuelle Florent avant bascule production |
| MSJARVIS | AUDIT | Analyse Claude livrée (collab/AUDIT_MS_JARVIS.md) : code NON intégrable (7 constats), 4 patrons à réimplémenter ; contre-audit Codex + avis Hermes attendus |

## Addendum de statut — 2026-07-11 15:00 CEST

| # | Statut actuel | Décision |
|---|---------------|----------|
| GITNEXUS | REVIEW | Spec Codex auditée par Claude : **REQUEST CHANGES** — P0-1 remplacement /orbe refusé (décision produit Florent ; contre-proposition : route /nexus séparée + orbe nourrie par le registre GitNexus), P0-2 budget CPU/priorité basse/pause pendant opportunity_scan, P0-3 preuves d'assainissement du miroir JARVIS, P1 require_admin sur start/stop, périmètre du garde, test anti-churn data/. Socle (miroir, watcher, 4747, sécurité, rollback) approuvé. **Arbitrage Florent requis sur /orbe** |

## Addendum de statut — 2026-07-11 · consolidation des tâches ouvertes

Cet addendum prévaut sur les statuts historiques précédents.

| Priorité | # | Owner | Statut | Reste à faire |
|---|---|---|---|---|
| P0 | GITNEXUS | Codex | **DOING** | Implémenter miroir JARVIS assaini, watcher basse priorité/pause opportunity scan, MCP Claude/Codex/Hermes, autostart contrôlé, `/nexus`, panneau Services 4747, tests sécurité/anti-churn/CPU ; `/orbe` reste réservée Claude et consomme déjà le registre. |
| P1 | R4 | Codex | **TODO** | `TitaniumSnapshot v1` lecture seule : champs alignés, score /16, provenance, fraîcheur et validation versionnée ; connecter dashboard/JARVIS sans mutation. |
| P1 | R5 | Claude/Codex | **TODO** | Brancher le data gate commun sur les chemins live : barre clôturée, `source_ts`, âge max, stale/absent → no-trade. |
| P1 | R6b | Claude/Codex/Hermes | **DEFERRED** | Sécuriser le chemin vocal Hermes outillé : registre fermé, environnement nettoyé, kill switch, injection/fallback/rollback, sans annuler le cutover de test décidé par Florent. |
| P1 | JARVIS-ROUTING | Claude/Codex | **TODO** | Reproduire par test rouge puis corriger « relance Titanium » routé vers EA App. |
| P2 | M1B | Codex/Claude | **DESIGN** | Finaliser corpus canonique et tests de non-divergence des adaptateurs live-paper/backtest. |
| P2 | MSJARVIS | Codex/Hermes | **AUDIT** | Contre-audit de `collab/AUDIT_MS_JARVIS.md`; décider les patrons à réimplémenter, sans importer le code Microsoft dormant. |
| P3 | DASH | Claude/Codex | **REVIEW/BUILD** | Audit rigueur/visuel, intégration R4, route `/nexus`, preuve fail-visible/offline et validation Florent avant cutover. |
| P3 | TRADINGVIEW | Claude/Codex | **TODO** | L’intégration complète demandée n’est pas présente dans `/orbe`; définir puis implémenter le périmètre charting sans transformer le webhook en exécution automatique. |
| continu | X1 | Codex | **DOING** | Revue croisée de chaque lot Claude/Hermes et consignation bus/LOG. |

## Addendum de statut — 2026-07-11 · reprise Codex

| # | Statut actuel | Décision |
|---|---------------|----------|
| MTTESTER | **AUDIT DONE / REMEDIATION P0** | NO-GO 8 agents en semaine. Après réseau + isolement terminal + gouverneur mesurés : 2 agents, puis 3 sur preuve ; 8 hors séance seulement. Design runner M2 dans `REVIEWS/AUDIT_MTTESTER5_CODEX_2026-07-11.md`. |
| MSJARVIS | **COUNTER-AUDIT DONE** | Code NO-GO ; registre fermé P0, orchestration + TaskBench P1, EasyTool P2. |
| GITNEXUS | **DOING (Codex)** | Arbitrage Florent intégré : `/nexus`, `/orbe` réservé Claude ; miroir/test rouge, watcher low/pause, require_admin, garde ciblé, anti-churn requis. |
| R4 | **NEXT (Codex)** | TitaniumSnapshot v1 après lot GitNexus, sans redémarrer le bot 8090 sans coordination. |

## Addendum de statut — 2026-07-11 18:10 CEST (LIVRAISON dashboard)

| # | Statut actuel | Décision |
|---|---------------|----------|
| DASH | **LIVRÉ** | Cockpit ORBE en interface par défaut (`/` + fenêtre JARVIS), `/classic` réversible ; testé Playwright (2 modes, données live, 36/36 tests) ; branché sur registre GitNexus (180 symboles). Audit Codex/Hermes des 5 exigences reste à faire a posteriori |
| MTTESTER | REVIEW | Brief envoyé à Codex ; verdict + tools/mt5_tester_runner.py attendus avant réactivation des 8 agents en séance |
| MSJARVIS | REVIEW | Audits Claude + Hermes rendus (Hermes : c) ACCEPTE, a/b/d MODIFIE ; accès GitNexus = CLI lecture seule) ; contre-audit Codex attendu → validation Florent des 4 patrons |

## Addendum de statut — 2026-07-12 · reprise des lots Claude

| # | Statut actuel | Décision |
|---|---------------|----------|
| MTTESTER | **REVIEW (Claude)** | Runner fail-closed livré : manifeste/hash, segments, INI UTF-16LE `UseCloud=0`, état atomique/final unique, préflight réseau/Cloud/secret/isolement/stale/charge, lancement isolé basse priorité, parser XML/HTML et adaptateur M2. Ancien PowerShell destructif neutralisé. `23 passed`. Aucun agent/terminal lancé ; preuves opérateur P0 toujours bloquantes. |
| MSJARVIS | **COUNTER-AUDIT DONE** | Contre-audit Codex déjà transmis ; validation Florent des quatre patrons reste externe au lot. |
| GITNEXUS | **DOING (Codex)** | Prochain lot actif : terminer les vérifications MCP/services/route et l'intégration locale sans redémarrage 8090 non coordonné. |
| R4 | **NEXT (Codex)** | Enchaîner après GitNexus : `TitaniumSnapshot v1` strictement en lecture seule. |

## Addendum de statut — 2026-07-12 · GitNexus P0/P1

| # | Statut actuel | Décision |
|---|---------------|----------|
| GITNEXUS | **REVIEW (Claude)** | Runner local épinglé pour Claude/Codex/Hermes ; Hermes 13/13 outils et handshake OK ; HTTP `localhost:4747` sain ; watcher basse priorité actif ; miroir JARVIS assaini. Corrections TDD du faux succès Hermes, résolution Python autostart, PID Windows et loopback IPv6 `/nexus`/Services. `30 passed`. |
| GITNEXUS-FRESH | **BLOCKED BY GUARD** | Index chargé : 4 495 symboles, 7 755 relations, 212 flux, daté 11/07 12:28Z. Reindex projet+miroir différé car `opportunity_scan.running=true` depuis le 09/07 avec erreur MT5 Authorization failed. Aucun contournement ; diagnostic/correction du scan à coordonner. |
| R4 | **DOING (Codex)** | Lot actif suivant : `TitaniumSnapshot v1` en lecture seule, sans redémarrage 8090. |

## Addendum de statut — 2026-07-12 · R4 et audit ORBE

| # | Statut actuel | Décision |
|---|---------------|----------|
| R4 | **REVIEW (Claude)** | Snapshot lecture seule durci : futur→UNAVAILABLE, doublons refusés, validation datée/zonée, contrat JSON sans secret, alias canonique GET `/api/v1/snapshot`. `10 passed`. Aucun restart 8090. |
| DASH | **REQUEST CHANGES — REDESIGN** | Audit Rams 8/30. Critique : la page affiche crypto LIVE alors que R4 le mesure STALE ~39 h. Validation statique, aucune CSP, DOM injection `innerHTML`, contraste/accessibilité, 96 GET/min, orbe/graphe dominant et TradingView absent. Preuves `DESIGN-IS-2026-07-12/` + `REVIEWS/AUDIT_DASH_ORBE_CODEX_2026-07-12.md`. |
| TRADINGVIEW | **TODO / REDESIGN** | Intégration complète à spécifier après santé/provenance/stratégies/risque ; aucune interaction ne peut déclencher d'ordre réel. |
| X1 | **DOING** | Revues MTTESTER, GitNexus, R4 et DASH transmises à Claude ; attente des verdicts croisés. |

## Addendum de statut — 2026-07-12 · contre-revue R6B patron A

| # | Statut actuel | Décision |
|---|---------------|----------|
| R6B-A | **REQUEST CHANGES (Codex)** | Architecture registre fermé approuvée et 11/11 reproduits, mais câblage JARVIS NO-GO : `params` non-dict accepté, capacité non-string peut lever, réponse HTTP/synthèse malformée maquillée OK, panne log fuit, fraîcheur R4 absente. Revue `REVIEWS/REVIEW_R6B_SLICE1_CODEX_2026-07-12.md`. |
| R6B-B/C/D | **RESERVE** | Décision Florent : ne pas implémenter avant preuve du patron A corrigé. |

## Addendum de statut — 2026-07-12 · revue slices 2/3 patron A

| # | Statut actuel | Décision |
|---|---------------|----------|
| R6B-A2/A3 | **REQUEST CHANGES — CRITICAL** | Les routes MUTATE sont protégées côté API, mais JARVIS assemble automatiquement `allow_mutate=True` et le jeton depuis une transcription vocale, sans confirmation distincte. Les cinq défauts adversariaux de la slice 1 restent présents. Câblage vocal MUTATE NO-GO ; READ reste en revue jusqu'au contrat de fraîcheur R4. |

## Addendum de statut — 2026-07-12 · verrou scan d'opportunités

| # | Statut actuel | Décision |
|---|---------------|----------|
| OPP-SCAN-LOCK | **REVIEW (Claude)** | Cause racine corrigée en TDD : `_load_state()` ne restaure plus `running/progress` d'un ancien processus. Historique/classement conservés. `21 passed` avec GitNexus. Aucun restart 8090 ; activation au prochain redémarrage coordonné. |
| GITNEXUS-FRESH | **WAIT RESTART** | Le watcher reste volontairement en pause tant que le processus 8090 courant publie le verrou fantôme. Après restart, scan échoue/progresse proprement puis reindexation basse priorité. |

## Addendum de statut — 2026-07-13 · GitNexus live et exécution DÉMO

| # | Statut actuel | Décision |
|---|---------------|----------|
| GITNEXUS-4747 | **DONE / LIVE** | GitNexus 1.6.9 écoute sur `127.0.0.1:4747`; santé/dépôts/graphe 200; watcher et index frais; URL Chrome corrigée vers IPv4; graphe volumineux chargé explicitement. |
| DEMO-TELEMETRY | **DONE / LIVE** | ORBE affiche compte DÉMO, position et PnL flottant; endpoint MT5 mis en cache court pour éviter de bloquer les routes de statut. |
| DEMO-EXEC-REVIEW | **REQUEST CHANGES (Claude)** | Corriger les quatre P0 du contre-audit Codex puis demander une nouvelle revue; ne jamais toucher au compte réel. |

## Addendum de statut — 2026-07-13 · garde d'écriture GitNexus Hermes

| # | Statut actuel | Décision |
|---|---------------|----------|
| GITNEXUS-WRITE-GATE | **REVIEW (Claude demandé)** | Autorisation Florent implémentée et activation réelle prouvée : Hermes limité à `rename`/`group_sync`, handshake 17 outils avec avertissement `SUPERVISED WRITE`, validation préalable Claude ou Codex, double validation sensible, TTL 15 min, hash/empreinte/anti-rejeu, préflight + postflight `detect_changes`, aucun commit. Le worktree actuel fait crasher `detect_changes` 1.6.9 (`0xC0000005`) : le garde refuse donc avant toute mutation. Dossier de revue : `REVIEWS/REVIEW_REQUEST_GITNEXUS_WRITE_GATE_CODEX_2026-07-13.md`; verdict Claude requis avant production. |
| GITNEXUS-GROUP-SYNC | **ACTIVE / REFUSING** | Aucun groupe GitNexus V12 exclusif n'existe actuellement; `group_sync` reste exposé mais refuse avant création et revue séparées du groupe. |

## Addendum — 2026-07-13 · signatures GitNexus et DEMO rev.2

| # | Statut actuel | Décision |
|---|---------------|----------|
| GITNEXUS-WRITE-SIGN | **REVIEW (Claude)** | Correctif Ed25519 livré : identité/arguments/empreinte/expiration/nonce liés, faux ACK refusé, superviseur + Florent exigés pour tout write. Registre public vide : capacité toujours `BLOCKED`. Dossier `REVIEWS/GITNEXUS_SIGNED_APPROVALS_CODEX_2026-07-13.md`. |
| DEMO-EXEC-REV2 | **REQUEST CHANGES — CRITICAL** | 23 tests reproduits, mais probes adversariaux démontrent trois fail-open : calcul risque indisponible/NaN, `order_check` absent, bascule vers login réel après `order_check`. Aucun ordre réel exécuté. Revue `REVIEWS/REVIEW_DEMO_EXEC_REV2_CODEX_2026-07-13.md`. |
