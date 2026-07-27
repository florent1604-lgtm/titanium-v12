# REORG_STATE — état de reprise du chantier (lire EN PREMIER)

> Toute session qui démarre lit ce fichier d'abord et reprend à « prochaine action ».
> Mis à jour après CHAQUE étape (pas seulement en fin de phase). Idempotent : relancer ne casse rien.

- **Session id** : `titanium-reorg`
- **Branche** : `reorg/phase1` (master reste au dernier commit stable `aefded3`)
- **Bot démo** : ⚠️ **EN COURS D'EXÉCUTION** (port 8090). À arrêter proprement AVANT le
  déplacement d'arborescence (Phase 1.5). Les positions gardent leur SL/TP broker si arrêté.
- **Règle d'écart assumée** : on s'arrête pour revue Florend avant d'ACTIVER tout changement
  N4/N5 (RiskGate/exécution) — comparaison paper avant/après obligatoire (règle 4 du prompt).

## Avancement

| Phase | État | Commit |
|---|---|---|
| 0 — cartographie (INDEX + AUDIT) | ✅ FAIT | 56b0c7f |
| checkpoint git pré-réorg | ✅ FAIT | 56b0c7f |
| 1.1 — `core/state.py` (SystemState) | ✅ FAIT | 226cd16 |
| 1.2 — `core/journal.py` (journal unifié + refus/contrefactuel) | ✅ FAIT | 2eed157 |
| 1.3 — `core/config.py` (pydantic-settings) | ✅ FAIT | 2a96fb3 |
| 1b — RiskGate `risk/riskgate.py` (**SHADOW, non câblé, smoke OK**) | ✅ CONSTRUIT | (ce commit) |
| 1.4 — refactor pôles → lisent/écrivent state+journal | ✅ FAIT | 280541b |
| 1.5 — déplacement arbo N0→N5 (**bot arrêté**) | ✅ FAIT (0 régression) | 7d77189…(fix mt5) |
| &nbsp;&nbsp;• engine → feedback (N6) | ✅ | 7d77189 |
| &nbsp;&nbsp;• vision/emotion/fundamentals → poles (N2 feuilles) | ✅ | ad003af |
| &nbsp;&nbsp;• core/{scoring,smc,signal} → poles/smc | ✅ | (commit smc) |
| &nbsp;&nbsp;• core/{geometric_plane,spectral_bridge}+indicators/spectral → poles/spectral | ✅ | (commit spectral) |
| &nbsp;&nbsp;• core/{confluence*,consensus,cortex,lead_lag} → fusion (brain_gate reste core/) | ✅ | (commit fusion) |
| &nbsp;&nbsp;• data feeds → ingestion/market (mt5_lock partagé vérifié) | ✅ | (commit ingestion) |
| &nbsp;&nbsp;• fix test mt5_account_snapshot (chemin post-move) | ✅ | (fix mt5) |
| 1b-wiring — brancher RiskGate porte unique (**revue Florent + paper avant/après**) | ⬜ | — |
| 1c — ExecutionPort (MT5/Sim/Binance) | ⬜ | — |
| 2 — observabilité /health + structlog | ⬜ | — |
| 3 — extraction JARVIS (**Tailscale/dépôt = Florent**) | ⬜ | — |
| 4 — noyau LLM-indépendant + voix locale | ⬜ | — |
| 5 — geometrix pôle N2 (existe déjà) | ⬜ | — |
| 6 / 6b — multi-TF + émotion | ⬜ | — |
| 7 — TimesFM Oracle (**infra = Florent**) | ⬜ | — |
| 8 — Cloe (**biométrie/HALT = Florent**) | ⬜ | — |
| 9 — historique tick MT5 + backtest | ⬜ | — |

## ⚠️ LEÇON 1.5 (patron de déplacement sûr — à appliquer à chaque lot)
1. `git mv` module → nouvelle place ; shim `sys.modules` à l'ancien chemin (compat totale
   publics+privés, from-import ET import-as). Voir shims existants pour le modèle.
2. **Déplacer AUSSI les fichiers de DONNÉES module-local** (`*.json`, `*.md`) lus via
   `Path(__file__).parent/...` — sinon FileNotFound silencieux (ex. keywords.json).
3. **Corriger les chemins RACINE** : un module descendu d'un niveau casse `parent.parent`
   visant la racine → utiliser `parents[N+1]` (ex. signal_modulator → `parents[2]`).
4. Valider APRÈS chaque lot : import `api.api_server`, imports ancien+nouveau identiques,
   tests réels des modules touchés. Commit par lot (rollback trivial).
5. ⚠️ Les prochains lots (core/, data/) sont à HAUT fan-out + risque de landmines de chemin
   (param_registry.json, scoring_weights.json, etc.) — grep `__file__` dans chaque module avant.

## Prochaine action concrète
**Phase 1 TERMINÉE** (socle N0 + RiskGate shadow + adoption + déplacement pyramide, 0 régression).
Structure obtenue : `ingestion/market` (N1), `poles/{smc,spectral,fundamentals,emotion,vision}` (N2),
`fusion/` (N3), `risk/riskgate` (N4 shadow), `feedback/` (N6). Anciens chemins préservés par shims.

**Prochaine étape = 1b-wiring** : brancher le RiskGate comme porte unique d'exécution — **STOP
pour revue Florent + comparaison paper avant/après (règle 4)**. Alternative recommandée : redémarrer
le bot d'abord (le journal non censuré capture du RÉEL via les shims), observer, PUIS câbler.
Ensuite : 1c ExecutionPort, phases 2-9. Nettoyage des shims = tout à la fin, quand les imports
auront migré vers les nouveaux chemins.

⚠️ Échecs de suite complète = TOUS pré-existants (vérif worktree 56b0c7f) : paper_trading (5,
flaky/isolation OK), decision_kernel (3), gitnexus (1-2), brain_gate (3 = flag BRAIN_GATE_PERMISSIVE=1,
pas les moves). Aucune régression due au déplacement.

## Bot
⚠️ **ARRÊTÉ** (coupé par Florent le 27/07 pour la bascule). Positions gardent SL/TP broker mais
plus de trailing. À redémarrer sur décision de Florent une fois une étape stable atteinte.

## Journal des écarts / blocages
- (rien pour l'instant)
