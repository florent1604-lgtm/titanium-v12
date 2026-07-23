# Contexte Titanium v12 pour Hermes — mise à niveau complète

*Briefing rédigé par Claude Code (gouverneur technique) pour Hermes Agent, le
2026-07-10. Source de vérité vivante : `collab/` (PLAN.md, TASKS.md, LOG.md).*

## Qui fait quoi (équipe à 3 agents + Florent)

- **Hermes** — cerveau / orchestrateur central et mémoire de référence. Conserve le
  contexte de Florent (Telegram), coordonne, et pilotera Titanium de façon
  **adaptative** — **sous la gouverne technique de Claude** et l'arbitrage de Florent.
- **Claude Code** (Opus) — gouverneur technique + architecte + implémenteur. Garantit
  la cohérence, la sécurité et le respect des garde-fous ; code et revoit.
- **Codex** (gpt-5.6) — exécutant + auditeur/red-team. Fort en rigueur et revue critique.
- **Florent** — arbitre humain final. Valide chaque `REVIEW → DONE` et tout cutover.

## Le projet en clair

**Titanium v12** : bot de trading algorithmique, `C:\Users\flore\Desktop\v12`, API
FastAPI port **8090** (bindée 127.0.0.1). **Paper only, MT5 = données seulement,
AUCUN ordre réel.** Direction produit NON négociable de Florent :
- **multi-stratégie** conservée : crypto (Binance) + forex/or (MT5-Axi) + swing indices ;
- **veille sur les 141 actifs MT5** conservée et centrale (scan d'opportunités quotidien
  à l'ouverture asiatique + filtre de persistance 3 jours) ;
- pas de swing-only : on **sépare proprement** les stratégies (portefeuille/risque/preuves
  par stratégie), on ne supprime aucune source d'alpha.

## Architecture (survol)
- Moteurs paper : `core/signal_engine.py` (crypto, scoring SMC /16), `core/forex_engine.py`
  (V3 H1), `core/swing_engine.py` (indices H4, panier validé tester natif MT5), pilotés par
  `data/asset_configs.json`.
- Veille : `core/opportunity_scan.py` (141 actifs, cron quotidien, persistance).
- Optimiseur inversé : `tools/asset_optimizer.py` (walk-forward par actif).
- Temps réel : WS `/ws/realtime` (ticks MT5 ms + carnet L2 Binance).
- MT5 : `data/mt5_provider.py` (données seulement, `mt5_lock` sérialise les accès).
- JARVIS : assistant vocal séparé (`C:\Program Files\JARVIS`), cerveau hybride
  Gemini + Ollama local ; **R6 = migrer ce cerveau vers Hermes** (progressif, voir plus bas).

## L'audit (ChatGPT) et les priorités
Un audit externe a fixé le cap : **sécurité → correctness → méthodologie**. Conclusion
partagée : **ne pas présenter V12 comme rentable ni passer en réel** dans l'état.

## Ce qui a été LIVRÉ et TESTÉ (10/07/2026)
- **P0 sécurité** ✅ : API bindée 127.0.0.1 ; **auth fail-closed** (`api/auth.py`, jeton
  `ADMIN_TOKEN`) sur TOUTES les mutations (Claude + balayage S3 de Codex : 19 routes) →
  403 sans token, 200 avec ; webhook fail-closed ; push Git retiré de l'UI.
- **M1** ✅ : `domain/strategy.py` — fonction de stratégie **pure/déterministe**
  (données ≤ t → intention t+1, data-gate rigoureux, coûts explicites). Tests verts.
- **M2** ✅ : `validation/harness.py` — 3 segments, block bootstrap, PBO, Deflated Sharpe,
  statuts INSUFFICIENT_EVIDENCE / OBSERVATION / VALIDATED_FOR_FORWARD_PAPER.
- **R1** ✅ : dédoublonnage par barre (swing+forex) + **verrou de scan** (race corrigée,
  revue Codex) — `tests/test_bar_dedup.py` (dont test concurrent).
- **R2** ✅ : écritures d'état **atomiques** (`utils/atomic_state.py`) — `tests/test_atomic_state.py`.
- **R3** ✅ : **risque portefeuille** (`core/portfolio_risk.py`) — plafonds par stratégie /
  cluster corrélé / gross, consultés AVANT ouverture ; bloque la concentration US_INDICES
  de l'audit — `tests/test_portfolio_risk.py`.
- **S1** ✅ (Codex) : fix démarrage WinError 10048.

## En cours / à venir
- **R4** (délégué à Codex) : contrat de données JARVIS `TitaniumSnapshot v1`
  (realized_pnl/winrate, score /16, source_ts/stale_after).
- **Adaptateur `execution → decide_strategy`** (Claude) : brancher les moteurs sur la
  fonction pure M1 → fin de la divergence backtest↔live.
- **P2 méthodologie** (Codex) : corpus canonique M1B (tests de non-divergence).
- **R6** (ce chantier) : Hermes cerveau/orchestrateur de JARVIS et de Titanium.

## Garde-fous NON négociables (à respecter par TOUS, Hermes inclus)
1. **Paper only. Aucun ordre réel.** MT5 = données seulement. Le passage à l'écriture réelle
   est une séquence gated (forward paper → démo → micro-lots) sur décision explicite de Florent.
2. **Aucun changement de logique de trading sans validation** (protocole M2, statuts).
   « Adaptatif » ne veut PAS dire muter l'exécution en silence.
3. **Florent arbitre** tout `REVIEW → DONE` et tout cutover de cerveau.
4. **Sécurité** : API locale + auth fail-closed maintenues ; jamais de secret/authToken dans
   les messages, logs ou le bus.
5. **Traçabilité** : décisions durables dans `collab/LOG.md`, tâches dans `collab/TASKS.md`.

## Comment Hermes opère dans ce projet
- Orchestre, conseille, coordonne Claude + Codex ; parle à Florent (Telegram) ; garde la mémoire.
- Reçoit les livraisons/revues via le bus (`collab/messages/`) et `collab/LOG.md`.
- Peut demander à Claude (architecture/impl/gouvernance) et à Codex (exécution/audit) des lots.
- Ne contourne jamais les garde-fous ci-dessus. En cas de doute → arbitrage Florent.

Bienvenue Hermes. Tu es à niveau. On construit Titanium ensemble, proprement et prouvé.
