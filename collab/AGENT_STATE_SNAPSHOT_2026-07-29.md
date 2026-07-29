# État consolidé des agents et sous-chantiers — 2026-07-29

Cet instantané est destiné aux reviewers externes, notamment Kimi 3. Il décrit
l'état utile du collectif sans exposer les credentials ou caches de session.

## Équipe

| Acteur | Rôle | État au snapshot | Dernière contribution pertinente |
|---|---|---|---|
| Florent | propriétaire et arbitre final | actif | demande de publication intégrale du code hors secrets |
| Claude Code | architecte / implémenteur principal | quota indisponible selon Florent | correctifs Cloe et réorganisation pyramidale avant handoff |
| Codex | audit indépendant / red-team / implémentation contrôlée | actif | commits `3decd8a` puis `d64e252`, validations et publication |
| Hermes | orchestrateur local / centre de collaboration | configuré localement | contexte et handoffs via le pont MCP et le bus commun |
| Cloe | analyste locale Ollama / veto additif | intégrée au chemin démo | contexte canonique, missing-context fail-open, timeout borné |
| Copilot | contributeur historique ponctuel | aucune tâche active attestée ici | lots shadow observer et normalisation de tickers dans le bus |

Il n'y a **aucun sous-agent Codex actif** au moment de cet instantané. Le travail
d'un ancien chantier isolé reste matérialisé par le worktree et la branche
`feature/command-deck`; sa présence ne vaut pas approbation de fusion.

## Branches et sous-chantiers

| Branche | Rôle | État |
|---|---|---|
| `reorg/phase1` | état courant complet de Titanium | branche de référence Kimi |
| `master` | socle principal antérieur | 9 commits locaux devant l'ancien GitHub lors de la préparation |
| `feature/command-deck` | client Windows CollabHub | 18 commits propres par rapport à son point de divergence ; sources WPF et tests publiés séparément |

Le Command Deck est volontairement conservé hors du noyau tant que sa revue
fonctionnelle et sa validation visuelle ne sont pas terminées.

## Derniers lots contrôlés

### Cloe / macro — `3decd8a`

- contexte de veto canonique complété ;
- contexte manquant : aucune décision `STOP` fondée sur l'absence de données ;
- requête locale bornée à 2 secondes et sortie de la boucle async ;
- plancher de sévérité macro pour les événements réellement extrêmes ;
- 48 tests ciblés réussis au moment du lot.

### Connecteurs MT5 / MCP — `d64e252`

- sélection de symbole MT5 atomique sous le verrou existant ;
- résultat de `symbol_select` vérifié ;
- reconnexion proactive avec backoff non bloquant ;
- contrat public `Optional` conservé pour éviter une rupture massive ;
- client HTTP MCP persistant et fermeture propre ;
- retry limité aux GET idempotents, jamais aux POST ambigus ;
- health check au démarrage et classification timeout/offline/error ;
- 57 tests ciblés réussis.

L'analyse d'impact GitNexus de ce lot a été classée **CRITICAL** :
22 symboles et 24 flux affectés. Cela impose une relecture renforcée avant toute
évolution supplémentaire des connecteurs.

## Validation globale connue

Dernière exécution globale documentée :

```text
844 passed
1 skipped
26 failed (baseline connue, hors fichiers du lot MT5/MCP)
```

Familles d'échecs connues :

- attentes historiques du `brain_gate` permissif ;
- cache du `decision_kernel` ;
- assertions de spread dans l'exécuteur démo ;
- manifeste d'accès GitNexus ;
- prix, sizing et reset du paper trading.

Cette branche est publiable comme **état de développement auditable**, mais ne
doit pas être présentée comme une release entièrement verte.

## État des organes

- FastAPI Titanium : port local attendu `8090`.
- Open WebUI : port local attendu `3000`.
- Ollama : port local attendu `11434`.
- GitNexus UI : port local attendu `4747`.
- MT5 : compte de démonstration uniquement pour `order_send`.

Les ports sont des conventions locales et non des services publics du dépôt.
Leur présence doit être revérifiée après chaque démarrage.

## Cartographie GitNexus

Le fichier `AGENTS.md` annonce l'index `titanium-v12` avec :

- 26 633 symboles ;
- 69 089 relations ;
- 300 flux d'exécution.

L'index généré n'est pas versionné. Après clone :

```powershell
node .gitnexus/run.cjs analyze
```

ou, si le runner local n'existe pas :

```powershell
npx gitnexus analyze
```

Une analyse d'impact est obligatoire avant toute modification de symbole runtime
dans `core/`, `execution/`, `domain/`, `api/` ou un utilitaire qui écrit l'état.

## Contraintes de revue

1. PAPER ONLY sur le compte réel.
2. Mur démo/réel fail-closed avant chaque `order_send`.
3. Aucun changement de stratégie sans M2 et preuves hors échantillon.
4. Aucun secret dans Git, les logs, le bus ou les rapports.
5. Les états générés ne sont jamais une source de vérité du code.
6. Toute conclusion de rentabilité doit inclure coûts, fréquence, PBO et DSR.

## Sources de vérité

- `AGENTS.md` : règles opératoires actuelles ;
- `collab/ETAT_ACTUEL.md` : historique consolidé ;
- `collab/messages/stream.ndjson` : faits et handoffs append-only ;
- `collab/REVIEWS.md` : revues croisées ;
- `collab/TASKS.md` : registre historique, dont certaines lignes anciennes sont
  supplantées par les addenda plus récents ;
- Git : preuve immuable des changements réellement commités.
