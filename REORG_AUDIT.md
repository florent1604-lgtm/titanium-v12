# REORG_AUDIT — Findings Phase 0 + plan de migration (27/07/2026)

Phase 0 = **lecture seule**. Aucun code runtime modifié. Le bot démo tournait pendant l'audit.

---

## 1. Findings

### 1.1 État git (bloquant à traiter AVANT Phase 1)
- Dépôt sur `master`, **working tree SALE** : nos features récentes (filtre tendance, gestion
  dynamique SL, analytique, raffinement M5/M1) sont **non commitées**, mêlées aux fichiers
  d'état runtime (`data/*.json`, `paper_journal`, `signal_history`) qui **changent en continu
  car le bot tourne**. Une worktree `.worktrees/command-deck/` existe aussi.
- **Conséquence** : impossible de brancher proprement pour la réorg sans d'abord (a) commiter/
  stabiliser le travail en cours, (b) sortir les fichiers d'état runtime du suivi git (ils
  polluent chaque diff). → **Première action de Phase 1**, sous revue de Florent.

### 1.2 Variables d'état — dispersées, pas de SystemState
Aujourd'hui l'état circule via des dicts ad hoc + fichiers JSON par moteur : `data/paper_state.json`,
`forex_paper_state.json`, `swing_paper_state.json`, `opportunities.json`, `entry_adaptation.json`,
`demo_pos_state.json`, `LAST_DECISION` (in-mem confluence), `consensus LAST_RESULTS`, etc.
**Aucun `SystemState` typé unique** → c'est le cœur de la Phase 1.

### 1.3 Les contrôles de risque — DISPERSÉS (bien plus que « 4 »)
| Contrôle | Où | Appelé par |
|---|---|---|
| Validation pré-entrée paper | `execution/paper_trading.py`, `executor.py` | moteurs paper |
| Veto fondamentaux | `fundamentals/signal_modulator.py::modulate` | signal_engine |
| Circuit breaker | `paper_trading.py` + `engine/learning_engine.py` + route reset | boucle CB |
| Sizing / SL-TP | `execution/risk_manager.py` | executor |
| Caps portefeuille (fail-closed) | `core/portfolio_risk.py` | swing/forex/crypto |
| Porte neuronale (consensus) | `core/brain_gate.py` | confluence_demo_engine |
| Garde démo (spread, min-lot, kill-switch) | `execution/demo_mt5_executor.py::DemoGuards` | demo_bridge |
| **Filtre tendance anti-fade** (26/07) | `confluence_demo_engine::_counter_trend_block` | confluence_demo_engine |
| Gestion dynamique SL (breakeven/trailing) | `execution/demo_position_manager.py` | boucle dédiée |

→ **7+ contrôles sur 3 chemins différents.** La Phase 1b (RiskGate unique) est **justifiée et
prioritaire** : c'est le vrai gain structurel. Chantier délicat (touche l'exécution/risque →
règle 4 : comparaison paper avant/après + revue Florent obligatoire).

### 1.4 Chemins d'exécution — multiples (invariant #3 violé aujourd'hui)
- Paper : `signal_engine → executor/paper_trading`.
- Démo MT5 : `confluence_demo_engine.run_once → demo_bridge.place_demo_async → demo_mt5_executor`.
- Swing/forex : `swing_engine/forex_engine → demo_bridge`.
- Webhook TradingView : `api/webhook_routes.py`.
→ **Pas de fonction d'exécution unique.** Objectif Phase 1b/1c : tout passe par `RiskGate → ExecutionPort`.

### 1.5 Timeframes
- Confluence : M15 (LTF) / H4 (HTF), chaîne de fraîcheur M15→H1→H4, raffinement M5/M1 (26/07).
- Swing H4, forex H1. TF **codés en dur** via `.env` (`CONFLUENCE_DEMO_LTF/HTF`).
- **Pas de sélecteur de TF dynamique** (cycle dominant / régime) → cible Phase 6.2.
- Sizing = `risque / distance_SL` déjà en place (demo executor) → le piège mécanique 6.3 est réel.

### 1.6 MT5 & simulateur paper
- **MT5 intégré** : `data/mt5_provider.py` (données only) + `demo_mt5_executor` (order_send sur
  compte **démo 50061786, mode HEDGING**). Lots/points gérés dans l'exécuteur. Univers via
  `tools/asset_optimizer.list_universe`. → Phase 1c en partie DÉJÀ FAITE ; manque l'abstraction
  `ExecutionPort` (adaptateurs MT5/Sim/Binance).
- **Simulateur paper** (`paper_trading.py`) : sim complète (slippage/fees/funding), `paper_state.json`,
  circuit breaker. **Aujourd'hui c'est un arbitre** (utilisé par forex/swing/signal). → Phase 1c :
  le rétrograder à (a) contrefactuel des refus, (b) rejeu historique. À faire sous revue.

### 1.7 Modules « incertains » — TOUS LOCALISÉS (rien à créer)
- **geometrix** → `core/geometric_plane.py` + `core/spectral_bridge.py` + `indicators/spectral.py`.
  Déjà câblé à `brain_gate` (observateur de régime, sizing-only). Phase 5 = l'intégrer proprement
  comme pôle N2, **pas** le créer.
- **émotion** → `emotion/{emotion_engine,market_context}.py`. **Read-only**, alimente la conviction
  de `brain_gate` → `size_factor` (MODULE le sizing, ne déclenche pas). Conforme à la cible 6b.3.
- **fondamentaux** → `fundamentals/` (risk_scorer 0-100, signal_modulator). Distinct de l'émotion
  (faits vs état psychologique). Recouvrement à vérifier finement en 6b, mais séparation déjà nette.
- **Titan** → `assistant/titan_agent.py` + `titan_core.py` + `titan_memory.json`. Agent LLM (couche
  assistant). **Décision : extraire avec JARVIS** (Phase 3), pas dans le noyau.
- **JARVIS** → `assistant/` + `mcp_server.py` + appli séparée `C:\Program Files\JARVIS` qui *poll*
  l'API 8090. **Titanium n'importe PAS JARVIS** (couplage déjà inversé) → extraction Phase 3
  surtout mécanique (déplacer `assistant/`+`mcp` + formaliser la frontière API).
- **LLM hors chemin critique** : le noyau (confluence + consensus + risque) est déjà déterministe ;
  le LLM (Titan/Hermes/Ollama) est consultatif. Test du fil débranché à formaliser en Phase 4.

### 1.8 Code mort / archive évidents (à déplacer en `_archive/`, pas supprimer)
`Sans titre/`, `codex_pytest_tmp_20260717/`, `codex_pytest_tmp_20260718/`, `pytest-tmp-codex-*/`,
`conception UI titanium modeles/`, `PATHFINDER-*`, `DESIGN-IS-2026-07-12/`, `__pycache__/`,
backups HTML `titanium_v12_dashboard.backup-*`. (Confirmer via GitNexus qu'aucun n'est importé.)

---

## 2. Plan de migration par phases (adapté au réel)

| Phase | Contenu | Autonome ? | Risque |
|---|---|---|---|
| **0** | Cartographie (ce doc + INDEX) | ✅ fait | nul (lecture seule) |
| **1** | SystemState + journal unifié + config + réorg dossiers N0→N5 | ⚠️ oui MAIS restructure le système VIVANT | **ÉLEVÉ** — checkpoint + go Florent |
| **1b** | RiskGate unique (consolide 7+ contrôles) | ⚠️ touche exécution/risque | **ÉLEVÉ** — paper avant/après + revue |
| **1c** | ExecutionPort (MT5/Sim/Binance) + rétrograder le sim | ⚠️ partiellement fait | MOYEN |
| **2** | structlog + /health + auto-diagnostic (propose, n'applique pas) | ✅ | FAIBLE |
| **3** | Extraction JARVIS → dépôt séparé + contrôle distant | ⚠️ **Tailscale + nouveau dépôt = TOI** | MOYEN |
| **4** | Noyau LLM-indépendant + voix locale (STT/TTS) | ✅ (téléchargement modèles) | FAIBLE |
| **5** | Intégrer geometrix comme pôle N2 | ✅ (existe déjà) | FAIBLE |
| **6** | Auto-adaptation multi-TF (sélecteur TF, sizing, filtre coût, A/B, adapt()) | ✅ gros chantier | MOYEN |
| **6b** | Pôle émotion (séparation fondamentaux, courbe paramétrable) | ✅ | FAIBLE |
| **7** | TimesFM sur **Oracle Cloud** | ❌ **déploiement infra = TOI** | dépend infra |
| **8** | « Cloe » (Ollama, HALT, biométrie) | ⚠️ **Windows Hello/voix/clé = TOI** | MOYEN |
| **9** | Historique tick MT5 + backtest via RiskGate | ✅ | MOYEN |

## 3. Ce qui NÉCESSITE Florent (non automatisable)
1. **Feu vert Phase 1** (restructure le système vivant) — et gestion de l'arrêt/redémarrage du bot pendant la bascule.
2. **Oracle Cloud** (Phase 7) : création instance, credentials, réseau.
3. **Tailscale** + nouveau dépôt `jarvis` distant (Phase 3).
4. **Biométrie** Windows Hello / enrôlement voix / clé de sécurité physique (Phase 8.6).
5. **Boucle auto-resume `bypassPermissions`** (section Reprise) : je fournis le script, tu l'armes.
6. **Revue paper avant/après** pour tout changement N4/N5 (ta règle 4).

## 4. Réserves honnêtes
- Chantier **pluri-semaines**, pas une session. `REORG_STATE.md` + commits/branche par phase = indispensables.
- **Écart démo/réel** (Phase 1c) : le démo remplit mieux que le réel, aucun impact marché → « validé démo » ≠ « validé réel ».
- **CPU mobile 15 W** : throttling thermique en charge 24/7 ; le vrai plafond reste les rate-limits API. À mesurer dans `/health` avant d'élargir les symboles.
- Le travail des jours derniers (filtre tendance, stop dynamique, analytique) sera **archivé/réintégré** dans la nouvelle structure, jamais perdu.

## 5. Décision requise pour enchaîner
La règle 1 du prompt dit « enchaîne Phase 1 sans validation ». **Je m'en écarte volontairement sur CE point précis** : la Phase 1 restructure un système de trading VIVANT avec du travail non commité. Je m'arrête ici pour :
1. ton **feu vert Phase 1**, et
2. la **stratégie git** (commiter d'abord le travail en cours + sortir l'état runtime du suivi ?).
Le reste des phases pourra ensuite enchaîner selon leur niveau de risque (les FAIBLE/MOYEN en autonomie, les ÉLEVÉ avec checkpoint).
