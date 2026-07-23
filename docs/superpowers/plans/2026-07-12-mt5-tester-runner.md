# MT5 Tester Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le script MT5 dangereux par un orchestrateur local fail-closed qui prépare des expériences natives reproductibles sans toucher au terminal Titanium live.

**Architecture:** `tools/mt5_tester_runner.py` reste un CLI autonome et paper-only. Il valide un manifeste JSON, construit un `ValidationPlan`, écrit des artefacts immuables dans `validation/runs/<run_id>/`, génère les INI UTF-16LE sans secret, conserve une machine d'états atomique et ne lance qu'un terminal tester explicitement isolé. Le parsing natif produit des rendements journaliers alignables et délègue PBO/DSR/gates à `validation.harness`.

**Tech Stack:** Python 3.12 stdlib, `validation.harness`, pytest, Windows/MetaTrader 5.

## Global Constraints

- PAPER ONLY permanent ; aucune autorisation d'ordre réel.
- Ne jamais tuer, redémarrer ou reconfigurer le terminal MT5 live.
- Ne jamais prendre `mt5_lock` pendant un backtest.
- Aucun login, mot de passe, serveur broker ou secret dans manifeste, INI, rapports ou logs.
- `UseCloud=0`, terminal tester et data directory isolés obligatoires.
- Le statut maximal est `VALIDATED_FOR_FORWARD_PAPER`.
- Deux agents maximum au premier déploiement en séance ; aucune réactivation automatique des agents par ce lot.

---

### Task 1: Contrat de manifeste et artefacts immuables

**Files:**
- Create: `tests/test_mt5_tester_runner.py`
- Create: `tools/mt5_tester_runner.py`

**Interfaces:**
- Produces: `ExperimentManifest.from_mapping(data)`, `ExperimentManifest.preregistration_hash`, `prepare_run(manifest, runs_root)`.

- [ ] **Step 1: Write failing tests** for paper-only enforcement, secret-key rejection, strict non-overlapping segments, safe identifiers, canonical preregistration hash and immutable run preparation.
- [ ] **Step 2: Run** `python -m pytest tests/test_mt5_tester_runner.py -q -p no:cacheprovider` and verify import failure.
- [ ] **Step 3: Implement minimal frozen dataclasses**, canonical JSON hashing, path neutralisation and exclusive run-directory creation.
- [ ] **Step 4: Re-run the tests** and verify the contract tests pass.

### Task 2: INI generation and atomic state machine

**Files:**
- Modify: `tests/test_mt5_tester_runner.py`
- Modify: `tools/mt5_tester_runner.py`

**Interfaces:**
- Produces: `render_ini(manifest, candidate, segment, report_path) -> str`, `write_ini_utf16le(path, content)`, `RunStateStore.transition(expected, target)`.

- [ ] **Step 1: Write failing tests** proving UTF-16LE BOM, `UseCloud=0`, absence of credential fields, absolute report path, legal transitions and single consumption of `FINAL_LOCKED`.
- [ ] **Step 2: Run the focused tests** and verify expected assertion failures.
- [ ] **Step 3: Implement deterministic INI rendering** and temp-file-plus-`os.replace` state transitions.
- [ ] **Step 4: Re-run the tests** and verify green.

### Task 3: Preflight et exécution isolée à priorité basse

**Files:**
- Modify: `tests/test_mt5_tester_runner.py`
- Modify: `tools/mt5_tester_runner.py`

**Interfaces:**
- Produces: `PreflightResult`, `preflight(manifest, health)`, `launch_isolated_tester(command, timeout_seconds, runner=subprocess.run)`.

- [ ] **Step 1: Write failing tests** for missing isolated terminal/data dir, active opportunity scan, stale MT5 data, excessive agent budget and forbidden `taskkill`/live terminal path.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement fail-closed checks** and low-priority Windows process creation without shell interpolation; timeout returns a terminal state and never kills unrelated processes.
- [ ] **Step 4: Verify GREEN** without launching MT5 in tests.

### Task 4: Parser natif et adaptateur M2

**Files:**
- Modify: `tests/test_mt5_tester_runner.py`
- Modify: `tools/mt5_tester_runner.py`

**Interfaces:**
- Produces: `parse_native_report(path, expected)`, `daily_net_returns(deals)`, `evaluate_native_run(manifest, reports)`.
- Consumes: `validation.harness.ValidationPlan`, `run_validation`, `ValidationStatus`.

- [ ] **Step 1: Write failing tests** with petits rapports XML/HTML déterministes : métadonnées cohérentes, incohérence fail-closed, valeurs locales et rendements journaliers alignés.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement strict parsing** without network access or HTML execution, verify symbol/dates/model/EA/parameters, preserve original native metrics and feed aligned net returns to M2.
- [ ] **Step 4: Verify GREEN** and assert status never exceeds forward-paper.

### Task 5: CLI, documentation and regression gate

**Files:**
- Modify: `tools/mt5_tester_runner.py`
- Modify: `tools/mt5_tester_run.ps1`
- Modify: `collab/TASKS.md`
- Modify: `collab/LOG.md`

**Interfaces:**
- Produces: commands `prepare`, `status`, `parse`; historical PowerShell script exits with a migration message and performs no process mutation.

- [ ] **Step 1: Write failing CLI tests** for dry preparation and refusal to execute without explicit isolated paths/preflight proof.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement CLI and replace the historical destructive script** with a non-destructive wrapper/documentation message.
- [ ] **Step 4: Run** `python -m pytest tests/test_mt5_tester_runner.py tests/test_validation_harness.py -q -p no:cacheprovider`.
- [ ] **Step 5: Search forbidden behavior** with `rg -n "taskkill|terminal64\.exe /F|UseCloud=1|Login=|Password=" tools/mt5_tester_runner.py tools/mt5_tester_run.ps1` and require no executable forbidden path.
- [ ] **Step 6: Record evidence** in the bus and collaboration log; do not start agents or MT5.

## Self-review

- Coverage: manifeste/hash, INI, state machine, preflight, low priority, parsing, M2 and migration of the unsafe script are included.
- Scope: agent firewall/password configuration and LAN probe remain an operator P0; this code cannot prove them and therefore cannot authorize agent reactivation.
- Types: every later task consumes interfaces introduced by earlier tasks; no runtime Titanium symbol is modified.
