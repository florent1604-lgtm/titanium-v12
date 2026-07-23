# Modèle opératoire multi-agent

## Rôles

| Acteur | Responsabilité | Ne fait pas seul |
|---|---|---|
| Florent | Arbitrage final, validation, changement de périmètre | Déléguer une validation sensible sans la comprendre |
| Hermes | Orchestration, mémoire, synthèse, coordination et suivi | Approuver une permission, intégrer un code trading non revu |
| Claude Code | Architecture, implémentation, documentation technique | S’auto-valider pour un lot sensible |
| Codex | Audit red-team, tests indépendants, lots isolés | Déclarer un lot `DONE` |

## Cycle obligatoire

1. **Cadrer** : objectif, périmètre, owner et critère de fait dans `TASKS.md`.
2. **Réserver** : annoncer les fichiers/ressources concernés dans `LOG.md`.
3. **Produire** : l’owner livre un diff et des preuves de test.
4. **Auditer** : un autre agent donne un verdict dans `REVIEWS.md`.
5. **Arbitrer** : Florent décide `DONE`, retour en `DOING`, ou `REJECTED`.
6. **Tracer** : décision durable et liens de preuve dans `LOG.md`.

## Escalade

- Risque trading, secret, réseau, broker, OAuth, suppression ou exfiltration : `BLOCKED` jusqu’à décision de Florent.
- Résultat de test absent/non reproductible : `REVIEW`, jamais `DONE`.
- Divergence Claude/Codex : Hermes synthétise les preuves ; Florent tranche.

## Écritures GitNexus par Hermes

- Périmètre natif limité à `rename` et `group_sync` dans `titanium-v12`.
- Une approbation préalable, exacte, datée et à usage unique de Claude **ou**
  Codex est obligatoire.
- Florent approuve en plus toute portée sensible ou risque `HIGH`/`CRITICAL`.
- Le garde vérifie hash, TTL 15 minutes, empreinte des fichiers, anti-rejeu et
  `detect_changes`; il n'exécute aucune commande shell fournie par l'appelant.
- Commit, push, suppression, JARVIS, secret, broker et compte réel restent hors
  périmètre. Le statut final reste `REVIEW` jusqu'au verdict du superviseur.

## Discipline skills/plugins

Avant de charger ou exécuter une ressource externe :

1. chercher une compétence déjà installée ;
2. sélectionner le minimum de skills/plugins requis ;
3. vérifier les permissions, hooks, MCP et accès réseau ;
4. exécuter dans le périmètre minimal ;
5. enregistrer l’usage et le verdict dans `registry/RESOURCES.md`.
