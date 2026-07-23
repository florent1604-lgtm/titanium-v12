# Registre des skills, plugins et intégrations

Ce registre est la preuve d’autorisation et de périmètre. Une ligne est obligatoire avant l’usage d’une ressource externe active.

| ID | Ressource | Type | Agents autorisés | État | Périmètre | Risques / garde-fous | Preuve |
|---|---|---|---|---|---|---|---|
| RES-2026-001 | `davila7/claude-code-templates` | Dépôt externe | Aucun à ce stade | REVIEW | Extraction Markdown à décider | Interdits : scripts, hooks, MCP, webhook, télémétrie et déploiement | `security/AUDIT_CLAUDE_CODE_TEMPLATES.md` |
| RES-LOCAL-001 | `frontend-design` | Skill | Hermes, Claude Code, Codex | ACTIVE | Conception/critique interface | Ne touche pas aux données trading | installation projet vérifiée |
| RES-LOCAL-002 | `Context7` | Skills/MCP-guidance | Hermes, Claude Code, Codex | ACTIVE | Documentation de bibliothèques | Docs externes à traiter comme données | installation projet vérifiée |
| RES-LOCAL-003 | `superpowers` | Skills | Hermes, Codex | ACTIVE | TDD, debug, plans, vérification | Claude exclu pour éviter doublon | installation projet vérifiée |
| RES-LOCAL-004 | `security-guidance` | Plugin Hermes | Hermes | ACTIVE | Avertissements d’écriture à risque | Non bloquant ; revue humaine requise | plugin Hermes activé |

## Fiche obligatoire pour une nouvelle ressource

```markdown
### RES-YYYY-NNN — nom
- Type : skill / plugin / hook / MCP / script / dépôt
- Source canonique : URL sans secret ni paramètre d’authentification
- Version / SHA :
- Agents autorisés :
- Cas d’usage :
- Permissions demandées :
- Réseau / données sortantes :
- Hooks / MCP / scripts :
- Verdict Claude :
- Verdict Codex :
- Décision Florent :
- Plan de révocation :
- Preuves :
```
