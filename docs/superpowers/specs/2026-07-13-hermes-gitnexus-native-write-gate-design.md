# Garde d'écriture native GitNexus pour Hermes

Date : 2026-07-13  
Décideur : Florent  
Statut : design validé verbalement, spécification à relire avant implémentation

## Objectif

Autoriser Hermes à exécuter les deux mutations natives GitNexus `rename` et
`group_sync` dans le dépôt Titanium V12, sous validation préalable et contrôle
d'un seul superviseur disponible : Claude ou Codex.

Cette autorisation améliore la capacité d'Hermes à orienter l'équipe à partir du
graphe de code, sans lui donner un droit général de modification, d'intégration ou
de déploiement.

## Périmètre autorisé

- Racine unique : `C:\Users\flore\Desktop\v12`.
- Dépôt GitNexus unique : `titanium-v12`.
- Outils d'écriture autorisés : `rename` et `group_sync`.
- Superviseur requis : Claude **ou** Codex, selon disponibilité.
- Canal d'autorisation : bus append-only `collab/messages/`.
- Preuves durables : demande, approbation, résultat et revue consignés dans le
  bus et synthétisés dans `collab/LOG.md`.

## Hors périmètre

Cette décision n'autorise pas Hermes à :

- utiliser un autre outil pour écrire du code ou contourner le garde ;
- écrire hors de `C:\Users\flore\Desktop\v12`, notamment dans JARVIS ;
- modifier `.env`, des secrets, des identifiants ou des configurations broker ;
- supprimer des fichiers, réinitialiser Git ou effectuer un remplacement global ;
- committer, pousser, fusionner ou publier ;
- approuver une permission sensible ;
- envoyer, modifier ou fermer un ordre de trading ;
- étendre lui-même son allowlist d'outils ou son périmètre de fichiers.

## Protocole avant mutation

Hermes doit produire une proposition immuable contenant :

1. un identifiant de demande unique ;
2. l'outil demandé (`rename` ou `group_sync`) ;
3. les arguments exacts et le dépôt ciblé ;
4. l'objectif et le critère de réussite ;
5. la fraîcheur de l'index obtenue par `list_repos` ;
6. le résultat de `context` ou `query` ;
7. le résultat de `impact upstream`, avec risque et flux affectés ;
8. les fichiers et symboles attendus ;
9. l'empreinte des fichiers et symboles directement visés ;
10. les tests prévus ;
11. le plan de retour arrière sans commande destructive.

Hermes publie cette proposition sur le bus à destination de `claude,codex`. La
première réponse explicite d'un superviseur disponible fait foi.

## Décision du superviseur

Une approbation valide doit :

- référencer l'identifiant exact de la demande ;
- reprendre l'outil et les arguments autorisés ;
- porter le verdict `APPROVED` ;
- expirer après 15 minutes ou dès qu'un argument, un fichier ou un symbole visé
  change ;
- ne couvrir qu'une seule exécution.

Tout silence, réponse ambiguë, approbation expirée, modification des arguments ou
indisponibilité du bus entraîne un refus fail-closed.

Un résultat `HIGH` ou `CRITICAL`, une cible dans `core/`, `execution/`, `domain/`,
`api/`, un utilitaire écrivant de l'état, ou un changement lié au trading exige en
plus un arbitrage explicite de Florent. Claude ou Codex ne peut pas lever seul ce
palier.

## Exécution contrôlée

Après approbation, Hermes vérifie de nouveau :

- que la racine résolue reste sous `C:\Users\flore\Desktop\v12` ;
- que le dépôt est toujours `titanium-v12` ;
- que l'index est frais et que l'empreinte des fichiers/symboles visés n'a pas
  changé depuis la proposition ; les changements sans rapport dans le worktree
  n'annulent pas l'approbation ;
- que l'outil et les arguments correspondent exactement à l'approbation ;
- que le jeton d'approbation n'a pas déjà été consommé.

Il exécute ensuite une seule fois `rename` ou `group_sync`. Aucun enchaînement
d'outils d'écriture n'est implicite.

## Contrôle après mutation

Hermes exécute immédiatement :

1. `detect_changes` sur le worktree ;
2. les tests approuvés ;
3. une comparaison entre fichiers/symboles attendus et réellement affectés ;
4. une publication du résultat sur le bus.

Le superviseur initial, ou l'autre superviseur s'il devient disponible, produit
un verdict `ACCEPTED`, `REQUEST_CHANGES` ou `ROLLBACK_REQUIRED`. Le lot ne devient
jamais `DONE` automatiquement et aucun commit n'est créé.

## Gestion des erreurs

- Échec GitNexus, index stale ou MCP indisponible : aucune écriture.
- Diff plus large que prévu : arrêt, `ROLLBACK_REQUIRED`, arbitrage humain.
- Tests absents ou rouges : `REQUEST_CHANGES`, jamais `ACCEPTED`.
- Approbation concurrente contradictoire : Hermes bloque et Florent tranche.
- Tentative hors racine ou hors allowlist : refus, journalisation et alerte aux
  deux superviseurs.

Le retour arrière est préparé avant l'exécution et reste manuel/contrôlé. Les
commandes destructives telles que `git reset --hard` ou `git checkout --` ne sont
jamais automatiques.

## Composants à implémenter

1. Un registre de demandes/approbations append-only dans `collab/messages/`.
2. Un validateur fail-closed des demandes, arguments, TTL et racine.
3. Un wrapper d'exécution limité à `rename` et `group_sync`.
4. Une consommation unique de l'approbation pour empêcher le rejeu.
5. Une publication standardisée des preuves avant/après.
6. Des tests unitaires et d'intégration sans mutation du compte de trading.

## Tests d'acceptation

- `rename` approuvé par Claude : exécuté une seule fois dans V12.
- `group_sync` approuvé par Codex : exécuté une seule fois dans V12.
- Aucun superviseur : refus.
- Approbation ambiguë, expirée ou rejouée : refus.
- Arguments modifiés après approbation : refus.
- Cible hors V12 ou dépôt autre que `titanium-v12` : refus.
- Outil autre que `rename`/`group_sync` : refus.
- Impact `HIGH/CRITICAL` sans décision Florent : refus.
- Cible sensible sans décision Florent : refus.
- `detect_changes` ou tests en échec : lot non accepté.
- Aucun chemin ne peut committer, pousser, manipuler un secret ou toucher au
  compte réel.

## Critère de mise en service

Le garde peut être déclaré actif uniquement lorsque les tests ci-dessus sont
verts, qu'une simulation complète demande → approbation → mutation de fixture →
contrôle est reproductible, et que Claude ou Codex a relu l'implémentation.
