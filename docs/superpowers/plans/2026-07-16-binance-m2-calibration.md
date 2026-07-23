# Binance M2 Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un driver Binance Spot data-only qui compare TAKER et MAKER avec le même harnais M2/DSR que Titanium.

**Architecture:** Un nouveau driver frère consomme `get_klines`, prépare une fenêtre commune M15/H1/H4, construit des coûts aller-retour explicites puis réutilise `_calibrate_style`. Aucun moteur runtime ni exécuteur n'est modifié.

**Tech Stack:** Python 3.11, pandas, pytest, Binance REST public, harnais `validation` Titanium.

## Global Constraints

- PAPER/data-only ; aucun ordre Binance ou MT5.
- Aucun secret ni clé API.
- TAKER = 20 bps RT ; MAKER = 15 bps RT.
- Spread 1 bps × 1,25 et slippage 1 bps par défaut.
- Spot : swap/funding = 0 et hypothèse enregistrée.
- Minimum 730 jours communs ; split M2 50/20/30 inchangé.
- Sorties uniquement sous `data/calibration_binance_2026-07-16`.
- Aucun commit sans demande explicite de Florent.

---

### Task 1: Contrat de coûts Binance

**Files:**
- Create: `tests/test_binance_optimizer_m2.py`
- Create: `tools/binance_optimizer_m2.py`

**Interfaces:**
- Consumes: `tools.binance_history.binance_cost_model(mode: str) -> dict`
- Produces: `build_cost_context(mode: str, spread_multiplier: float, reference_balance: float) -> tuple[CostModel, dict[str, object]]`

- [ ] **Step 1: Écrire les tests rouges** vérifiant TAKER=20 bps RT,
  MAKER=15 bps RT, coûts totaux 22,25/17,25 bps, funding nul et rejet d'un
  scénario inconnu.
- [ ] **Step 2: Exécuter**
  `venv\Scripts\python.exe -m pytest tests\test_binance_optimizer_m2.py -q`
  et constater un échec dû au module absent.
- [ ] **Step 3: Implémenter** `build_cost_context` avec conversion explicite
  `commission_bps = 2 * commission_per_side_bps` et `CostModel` sans swap.
- [ ] **Step 4: Réexécuter le test ciblé** et obtenir zéro échec.

### Task 2: Données multi-timeframes sans lookahead

**Files:**
- Modify: `tests/test_binance_optimizer_m2.py`
- Modify: `tools/binance_optimizer_m2.py`

**Interfaces:**
- Produces: `load_binance_frames(symbol, years, cache_root, fetcher, now) -> dict[str, pd.DataFrame]`

- [ ] **Step 1: Ajouter des tests rouges** avec un fetcher local : trois
  timeframes, suppression de la bougie non fermée, cache réutilisé, erreur
  explicite si une série contient moins de 600 bougies.
- [ ] **Step 2: Vérifier RED** avec la commande pytest ciblée.
- [ ] **Step 3: Implémenter** le chargement M15/H1/H4, `add_indicators`, le
  filtrage `index + durée <= now` et le cache pickle isolé.
- [ ] **Step 4: Vérifier GREEN** avec la commande pytest ciblée.

### Task 3: Calibration M2 par scénario

**Files:**
- Modify: `tests/test_binance_optimizer_m2.py`
- Modify: `tools/binance_optimizer_m2.py`

**Interfaces:**
- Produces: `calibrate_binance_asset(symbol, scenario, frames, requested_start, requested_end, spread_multiplier, bootstrap_replications, risk_pct, reference_balance) -> dict[str, object]`

- [ ] **Step 1: Ajouter des tests rouges** vérifiant fenêtre commune ≥730
  jours, appel des trois styles, provenance Binance, scénario et proposition
  uniquement quand `fastest_validated_style` passe.
- [ ] **Step 2: Vérifier RED**.
- [ ] **Step 3: Implémenter** la fenêtre commune, `split_calibration_window`,
  les trois appels `_calibrate_style` et la construction du résultat.
- [ ] **Step 4: Vérifier GREEN**.

### Task 4: CLI et persistance isolée

**Files:**
- Modify: `tests/test_binance_optimizer_m2.py`
- Modify: `tools/binance_optimizer_m2.py`

**Interfaces:**
- Produces: `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Ajouter des tests rouges** pour les 10 symboles par défaut,
  les scénarios `taker,maker`, les validations d'arguments et les fichiers
  `assets/<symbol>.<scenario>.json`, `summary.json`,
  `asset_configs.proposal.json`.
- [ ] **Step 2: Vérifier RED**.
- [ ] **Step 3: Implémenter** la CLI, `--resume`, les écritures atomiques et
  un résumé imbriqué par symbole/scénario sans `demo_login`.
- [ ] **Step 4: Vérifier GREEN**.

### Task 5: Vérification et handoff Claude

**Files:**
- Modify: `collab/ETAT_ACTUEL.md`
- Modify: `collab/LOG.md`
- Modify: `collab/REVIEWS.md`

- [ ] **Step 1: Exécuter** les tests Binance puis les suites calibration,
  validation et MetaTester.
- [ ] **Step 2: Exécuter** `py_compile` sur les deux modules Binance.
- [ ] **Step 3: Exécuter** GitNexus `detect_changes` ; documenter honnêtement
  tout mode dégradé ou risque global du worktree.
- [ ] **Step 4: Envoyer à Claude** la commande réseau exacte sur les 10 actifs,
  4 ans, 2 000 bootstraps, deux scénarios et sortie isolée.
- [ ] **Step 5: Ne déclarer aucun verdict** avant réception et contrôle du
  `summary.json` produit par le run extérieur.

