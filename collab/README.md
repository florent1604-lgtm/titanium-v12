# Espace de collaboration Claude Code ⇄ Codex

Ce dossier est la **source de vérité unique** de la collaboration entre les deux
agents IA sur Titanium v12, arbitrée par Florent.

> Navigation structurée : [`INDEX.md`](INDEX.md). Il référence les règles de
> gouvernance, audits de ressources, registre des skills/plugins et reporting manuel.

## Rôles

- **Hermes Agent** — cerveau principal / superviseur : conserve le contexte de Florent,
  arbitre l'orchestration et reçoit les handoffs via le pont MCP projet.
- **Codex** (gpt-5.6-terra, local) — auditeur / red-team + exécutant de tâches isolées.
  Fort en revue critique. Tourne dans ce repo (sandbox workspace-write).
- **Claude Code** (Opus) — architecte / implémenteur + pédagogue. Conçoit, code, explique.
- **Florent** — arbitre final : tranche les décisions, valide les diffs et les merges.

## Principe

Pas de bavardage IA↔IA en boucle. On travaille par **tâches** (voir `TASKS.md`),
chacune assignée à un agent, avec un livrable vérifiable et une revue croisée.
Décisions et échanges tracés dans `LOG.md`.

## Canaux techniques

- **Claude/Codex → Hermes** : serveur projet `hermes` dans `.mcp.json` et
  `.codex/config.toml`, lancé par `hermes mcp serve`. Procédure complète et
  garde-fous : [`HERMES_BRIDGE.md`](HERMES_BRIDGE.md).
- **Claude → Codex** : `tools/codex.ps1 "message ou brief"` (wrappe `codex exec`).
  La réponse est capturée dans `collab/LOG.md`.
- **Codex → Claude** : Codex écrit ses réponses/diffs dans le repo ; Claude les lit
  (git diff / fichiers) et les relaie à Florent.
- **Revue croisée** : `codex review` (revue non-interactive) ; `codex apply`
  (appliquer un diff proposé par Codex).
- **Contexte live** : les deux peuvent interroger l'API Titanium (port 8090) et,
  en option, le serveur MCP `titanium` (mcp_server.py).

## Workflow d'une tâche

1. La tâche est décrite dans `TASKS.md` (owner, objectif, critère de « fait »).
2. L'agent owner produit le livrable (code + note).
3. L'autre agent le **revoit** (revue croisée obligatoire pour tout code de trading).
4. Florent valide → la tâche passe `DONE`. Sinon retour en `REVIEW`.

Garde-fou permanent : **rien ne passe en réel**. MT5 = données seulement, paper only.
