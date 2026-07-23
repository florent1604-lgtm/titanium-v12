# Audit de sécurité — RES-2026-001

## Objet

- **Ressource :** `davila7/claude-code-templates`
- **Source canonique :** `https://github.com/davila7/claude-code-templates`
- **Révision auditée :** `6c324cc20cb27a8d8f093e49c003362d69d55e74`
- **Méthode :** clone en quarantaine, lecture statique, sans installation de dépendance, sans exécution de script ni activation de MCP/hook.
- **Verdict :** `AUTORISER PARTIELLEMENT` — extraction manuelle de Markdown, revue fichier par fichier.

## Décision de sécurité

**Interdit à l’intégration directe :** CLI, marketplace, `.mcp.json`, hooks, loops, settings, workflows CI/CD, scripts, workers, installateurs, fichiers de support exécutables et tout composant appelant `npx`, `uvx`, `pip`, `curl` ou un endpoint distant.

**Candidats texte uniquement, à sélectionner ultérieurement :**

| Chemin source | Valeur possible | Conditions |
|---|---|---|
| `skills/development/async-python-patterns/SKILL.md` | Async, timeouts, backpressure | Retirer toute commande/installateur |
| `skills/development/python-testing-patterns/SKILL.md` | Tests Python, mocks et async | Adapter aux outils Titanium |
| `skills/development/code-review-checklist/SKILL.md` | Revue de code | Faire valider par Codex |
| `skills/development/cc-skill-security-review/SKILL.md` | Audit secrets/API | Conserver uniquement les principes |
| `skills/security/security-threat-model/SKILL.md` | Threat modelling | Ajouter les risques trading PAPER ONLY |
| `agents/finance/quant-analyst.md` | Prompt de rôle | Sans outils ni action de marché |
| `agents/finance/risk-manager.md` | Prompt de rôle | PAPER ONLY obligatoire |

## Risques prouvés

| Niveau | Élément | Preuve / conséquence |
|---|---|---|
| Critique | Traçage LangSmith | Hook qui sérialise transcriptions, appels/outils et résultats vers un service externe |
| Critique | Déploiement automatique | Hooks et workflows Vercel/Cloudflare pouvant publier hors bac à sable |
| Élevé | Télémétrie opt-out | CLI qui envoie par défaut des métadonnées de composants, chemins et sessions |
| Élevé | Chaîne d’approvisionnement | Exécution via `npx`, `uvx`, `pip` et branche distante mutable |
| Élevé | Écriture Git automatique | Hooks `git add` après modification, incompatible avec une revue/staging financier strict |
| Élevé | MCP trading | Template Alpaca susceptible de couvrir des opérations d’ordre ; hors périmètre Titanium |

## Validation requise avant intégration

1. Florent choisit les fichiers Markdown précis à adapter.
2. Claude prépare une version locale minimalisée dans une branche dédiée.
3. Codex réalise une revue indépendante : secrets, injections, réseau, permissions et contradiction PAPER ONLY.
4. Hermes inscrit la version, le SHA source, les agents autorisés et le plan de révocation dans `registry/RESOURCES.md`.
5. Florent approuve explicitement le diff ; aucun hook/MCP/plugin ne sera activé par cette approbation.

## Règle permanente

> Une analyse de sécurité favorable ne transforme jamais une ressource externe en composant exécutable approuvé.
