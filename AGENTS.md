<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **titanium-v12** (26633 symbols, 69089 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user. For unified PDG impact, add `mode: "pdg"` with optional `line: <N>` — it returns statement-level `affectedStatements` over CDG + REACHING_DEF and inter-procedural symbols in `interproceduralByDepth`/`byDepth`; no-layer/degraded PDG results are UNKNOWN-risk notes (`--pdg` layer).
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "master"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).
- For control/data dependence, `pdg_query({mode: "controls", target: "fileOrSymbol"})` answers "under what condition does X run?" (CDG, incl. guard clauses) and `pdg_query({mode: "flows", target, variable})` traces "where does variable Y flow?" (REACHING_DEF). `--pdg` layer.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/titanium-v12/context` | Codebase overview, check index freshness |
| `gitnexus://repo/titanium-v12/clusters` | All functional areas |
| `gitnexus://repo/titanium-v12/processes` | All execution flows |
| `gitnexus://repo/titanium-v12/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Périmètre du garde GitNexus

- Impact/fraîcheur obligatoires avant modification de symboles dans `core/`,
  `execution/`, `domain/`, `api/` et les utilitaires qui écrivent de l'état.
- Contrôle facultatif pour documentation, HTML/CSS et tests sans mutation du
  runtime.
- Une panne MCP ne bloque pas le travail : signaler le mode dégradé, puis utiliser
  le graphe/API/CLI local ou le fallback statique Read/Search avec blast radius
  explicite. Ne jamais prétendre qu'une requête GitNexus a réussi si elle n'a pas
  été exécutée.

## Collaboration Hermes / Claude / Codex

- Le serveur MCP projet `hermes` est défini dans `.mcp.json` (Claude Code) et
  `.codex/config.toml` (Codex CLI) avec `hermes mcp serve`.
- Lire `collab/HERMES_BRIDGE.md` avant d'utiliser ce pont.
- Le pont sert aux handoffs, à la lecture du contexte et à l'arbitrage avec
  Florent. Ne jamais approuver une permission sensible via
  `permissions_respond` sans demande explicite de Florent.
- Garde-fou permanent : PAPER ONLY ; aucun ordre réel.

<!-- titanium:start -->
# Titanium — collaboration & état (Codex)

**À LIRE EN PREMIER : `collab/ETAT_ACTUEL.md`** (briefing compact : projet,
garde-fous, équipe, état des chantiers, décisions). Puis le tail du bus :
`node tools/collab_bus.mjs tail`.

Rôle Codex = auditeur / red-team indépendant. Garde-fous NON négociables :
PAPER ONLY sur le compte réel (60261188) ; démo (50061786) sous mur fail-closed ;
aucun changement de logique de trading sans protocole M2 ; jamais de secret dans
bus/logs. Livraisons/revues : bus (`collab_bus.mjs send`) + `collab/LOG.md` +
`collab/REVIEWS.md`. Décisions durables dans `collab/`.

En cours (voir ETAT_ACTUEL) : segment émotion (revue red-team des signaux
bienvenue), exécution démo rev.3 (re-revue), garde écriture GitNexus signé
(bloqué par crash detect_changes(all) 0xC0000005 — piste de fix attendue).
<!-- titanium:end -->
