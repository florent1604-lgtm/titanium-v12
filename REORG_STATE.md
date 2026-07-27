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
| 1.1 — `core/state.py` (SystemState) | ✅ FAIT (sanity-import OK) | (ce commit) |
| 1.2 — `core/journal.py` (journal unifié + refus/contrefactuel) | 🔜 EN COURS | — |
| 1.3 — `core/config.py` (pydantic-settings) | ⬜ | — |
| 1.4 — refactor pôles → lisent/écrivent state+journal | ⬜ | — |
| 1.5 — déplacement arbo N0→N5 (**bot arrêté**) | ⬜ | — |
| 1b — RiskGate unique (**revue Florent + paper**) | ⬜ | — |
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
Créer `core/journal.py` : journal append-only LOCAL (SQLite ou Parquet) où chaque niveau écrit
avec le `correlation_id` — état complet au signal, décision RiskGate (ALLOW/REDUCE/DENY + motif +
taille), résultat (fill, MAE/MFE, R, frais/slippage réels). **Point critique** : journaliser AUSSI
les signaux REFUSÉS + suivre leur trajectoire post-refus (trade fantôme) = dataset non censuré.
Fichier NEUF, importé par personne au départ → zéro risque pour le bot. Puis sanity-import.

## Journal des écarts / blocages
- (rien pour l'instant)
