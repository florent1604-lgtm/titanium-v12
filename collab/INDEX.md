# Index de collaboration Titanium V12

Ce fichier est le point d’entrée unique du travail commun entre **Hermes**, **Claude Code**, **Codex** et **Florent**. Il indexe les documents de décision ; il ne remplace ni Git, ni le journal append-only.

## Règles d’autorité

1. Florent est l’arbitre final : seul lui fait passer une tâche de `REVIEW` à `DONE`.
2. **PAPER ONLY** : aucun ordre réel, aucun accès broker en écriture.
3. `TASKS.md` porte le statut de travail ; `LOG.md` porte les décisions et preuves ; `REVIEWS.md` porte les verdicts d’audit.
4. Une ressource externe reste en quarantaine jusqu’à analyse de sécurité, revue croisée et validation explicite de Florent.
5. Aucun secret, token, URL d’authentification, identifiant broker ou donnée personnelle dans les documents `collab/`.

## Navigation

| Catégorie | Fichier de référence | Rôle |
|---|---|---|
| Pilotage | [TASKS.md](TASKS.md) | Tâches, owner, statut, critère de fait |
| Décisions | [LOG.md](LOG.md) | Journal append-only des choix et preuves |
| Revues | [REVIEWS.md](REVIEWS.md) | Audits Claude/Codex et verdicts |
| Architecture | [PLAN.md](PLAN.md) | Roadmap et dépendances fonctionnelles |
| Pont agents | [HERMES_BRIDGE.md](HERMES_BRIDGE.md) | MCP, bus, responsabilités et garde-fous |
| Gouvernance | [governance/OPERATING_MODEL.md](governance/OPERATING_MODEL.md) | Workflow multi-agent et escalade |
| Ressources externes | [security/EXTERNAL_RESOURCES.md](security/EXTERNAL_RESOURCES.md) | Quarantaine, analyse, approbation, révocation |
| Registre skills/plugins | [registry/RESOURCES.md](registry/RESOURCES.md) | Ressources autorisées, propriétaires et usages |
| Reporting manuel | [reporting/ON_DEMAND.md](reporting/ON_DEMAND.md) | Contrat de la commande `/repoting` |

## États normalisés

`IDEA` → `DESIGN` → `TODO` → `DOING` → `REVIEW` → `DONE`

États spéciaux : `BLOCKED`, `QUARANTINED`, `REJECTED`, `REVOKED`.

## Convention de nommage

- Tâches : `S*` sécurité, `R*` fiabilité, `M*` méthodologie, `C*` collaboration, `X*` revue croisée.
- Ressources : `RES-YYYY-NNN`.
- Décisions : `DEC-YYYY-NNN`.
- Revues : `REV-YYYY-NNN`.

Toute nouvelle sous-catégorie doit être ajoutée à cet index avant usage.