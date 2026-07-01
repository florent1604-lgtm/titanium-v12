<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **titanium-v12** (4574 symbols, 7056 relationships, 186 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

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
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Module spectral (analyse de cycles — Phase 0 active)

Titanium V12 intègre une brique d'**analyse spectrale des cycles de prix** — north star **2D → 3D → 4D** :
- **3D** : cycle dominant + puissance cyclique (filtre de régime)
- **4D** : phase instantanée (timing)

Fichiers de référence :
- `indicators/spectral.py` — module clean-room (cycle synthétique 20 barres détecté).
- `docs/TITANIUM_V12_SPECTRAL_ROADMAP.md` — recherche complète (méthodes, pièges, références Ehlers).

**Principe directeur** : pragmatique et incrémental, **local-first**, **paper trading + stop-loss d'abord**,
validation **walk-forward 70/30** obligatoire avant tout signal réel.

### Tâches de déploiement (ordre strict)

**Phase 0 ✅ — Module intégré** : `spectral.py` copié dans `indicators/`, `SPECTRAL_ENABLED=1` dans config,
logging `dominant_cycle / cycle_power / phase_zone` branché dans `core/signal_engine.py` (sans toucher au score).

**Phase 1 — Filtre de régime dans le scoring /16** :
- `has_cycle == False` → marché trend/range : dépondérer les critères dépendant de cycles.
- `has_cycle == True` → exposer `phase_zone` au moteur de décision (timing).
- Ne pas ajouter de nouveau point au /16 tant que la Phase 1 n'est pas validée walk-forward.

**Phase 2 — Visualisation dashboard** : périodogramme glissant via l'API FastAPI (3D sur le dashboard).

**Phase 3 — 4D multi-actifs** : surface BTC/ETH/SOL × fréquence × temps.

### Garde-fous causalité (NE PAS IGNORER)

- `roofing_filter(..., causal=False)` et `instantaneous_phase()` utilisent des données futures →
  **backtest/visu uniquement**. Pour le **live**, utiliser `causal=True` et implémenter Hilbert bar-par-bar `[TODO]`.
- `phase_zone()` doit être **calibré** sur données réelles par paire avant tout usage signal.
- Bornes de période : `pmin=8`, `pmax=50` par défaut — ajuster par timeframe.
- Config : `SPECTRAL_ENABLED`, `SPECTRAL_TF`, `SPECTRAL_PMIN/PMAX`, `SPECTRAL_POWER_THRESHOLD` dans `utils/config.py`.
