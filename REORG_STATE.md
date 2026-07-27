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
| 1.4 — refactor pôles → lisent/écrivent state+journal | 🔜 à faire | — |
| 1.5 — déplacement arbo N0→N5 (**bot arrêté**) | ⬜ | — |
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

## Prochaine action concrète
**Phase 1.4 — adoption du socle par les pôles/chemin de décision.** Faire écrire le
`SystemState` + le journal unifié (`core/journal.get_journal()`) par le chemin de décision réel
(confluence_demo_engine / demo_bridge) : à chaque cycle, remplir un SystemState (marché multi-TF,
scoring/piliers, régime/trend, fondamentaux, émotion, positions, risque) et journaliser
signal/decision/fill/ghost. Un pôle/chemin à la fois. **Bot ARRÊTÉ** actuellement → éditer
librement, valider par import + un run de smoke, PUIS on décidera du redémarrage avec Florent.

Ensuite : 1.5 déplacement arbo (detect_impact à chaque move, shims d'import pour ne rien casser),
puis 1b-wiring (brancher le RiskGate en porte unique — **revue Florent + comparaison paper**).

## Bot
⚠️ **ARRÊTÉ** (coupé par Florent le 27/07 pour la bascule). Positions gardent SL/TP broker mais
plus de trailing. À redémarrer sur décision de Florent une fois une étape stable atteinte.

## Journal des écarts / blocages
- (rien pour l'instant)
