# Gouvernance des ressources externes

## Politique de quarantaine

Une ressource externe (repo, skill, plugin, hook, MCP, script ou marketplace) est **non fiable par défaut**. Son installation ne vaut pas autorisation d’exécution.

| État | Signification | Action autorisée |
|---|---|---|
| `QUARANTINED` | Clone/lecture isolée uniquement | Audit statique et revue humaine/agents |
| `REVIEW` | Analyse publiée, risques identifiés | Aucune exécution automatique |
| `APPROVED-LIMITED` | Florent a approuvé un sous-ensemble précis | Installation ciblée, sans hooks/MCP actifs par défaut |
| `ACTIVE` | Utilisation validée et documentée | Usage dans le périmètre approuvé |
| `REVOKED` | Retirée après incident ou changement | Désactivation et retrait contrôlé |

## Contrôles minimaux

- Provenance : URL canonique, commit SHA, licence, date d’audit.
- Analyse : scripts, hooks, MCP, accès réseau, permissions, secrets, suppressions et CI.
- Intégration : sélectionner des fichiers précis ; ne jamais copier un dépôt entier dans Titanium.
- Permissions : pas de `--yolo`, pas de hook de notification, pas de webhook, pas d’upload sans décision explicite.
- Secrets : aucune variable sensible dans un template, un agent, un bus, une skill ou une documentation.
- Révocation : nom, version et chemins installés doivent être enregistrés pour retrait rapide.

## Ressource en cours d’analyse

| ID | Ressource | État | Périmètre demandé |
|---|---|---|---|
| RES-2026-001 | `davila7/claude-code-templates` | `REVIEW` | Extraction manuelle de Markdown sélectionné pour Hermes, Claude Code et Codex |

Audit terminé : [`AUDIT_CLAUDE_CODE_TEMPLATES.md`](AUDIT_CLAUDE_CODE_TEMPLATES.md).

Aucune installation active de cette ressource n’est autorisée avant choix explicite des fichiers, revue croisée et validation de Florent.