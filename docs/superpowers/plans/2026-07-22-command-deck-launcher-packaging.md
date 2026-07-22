# Command Deck Launcher and Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produire un exécutable Bureau idempotent qui démarre CollabHub, ouvre le Command Deck, VS Code, Claude et Codex, sans démarrer Titanium.

**Architecture:** Un orchestrateur .NET résout les exécutables par adaptateurs, inspecte les listeners gérés, puis démarre seulement les composants absents. L'installation PowerShell publie un build framework-dependent mono-fichier, calcule son SHA-256 et crée le raccourci Bureau.

**Tech Stack:** .NET 8, WPF launcher, HttpClient, System.Diagnostics, PowerShell, MSTest.

## Global Constraints

- Ne jamais tuer un PID non géré ni forcer un port.
- Ne jamais démarrer `main.py`, Titanium ou MT5.
- Aucun `--dangerously-skip-permissions`, secret, token IDE ou auto-approbation.
- Les terminaux démarrent dans V12 et chargent les instructions projet.

---

### Task 1: Résolution des chemins et santé

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/Titanium.CommandDeck.Launcher.csproj`
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/LaunchPaths.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/ServiceHealth.cs`
- Create: `command_deck/tests/Titanium.CommandDeck.Launcher.Tests/Titanium.CommandDeck.Launcher.Tests.csproj`
- Create: `command_deck/tests/Titanium.CommandDeck.Launcher.Tests/LaunchPathsTests.cs`

**Interfaces:**
- Produces: `LaunchPaths.Resolve(repoRoot)`, `ServiceHealth.ProbeAsync(uri, timeout)`.

- [ ] **Step 1: Créer les projets et les rattacher à la solution**

```powershell
dotnet new wpf -n Titanium.CommandDeck.Launcher -f net8.0 -o command_deck/src/Titanium.CommandDeck.Launcher
dotnet new mstest -n Titanium.CommandDeck.Launcher.Tests -f net8.0 -o command_deck/tests/Titanium.CommandDeck.Launcher.Tests
dotnet sln command_deck/CommandDeck.sln add command_deck/src/Titanium.CommandDeck.Launcher command_deck/tests/Titanium.CommandDeck.Launcher.Tests
dotnet add command_deck/tests/Titanium.CommandDeck.Launcher.Tests reference command_deck/src/Titanium.CommandDeck.Launcher
```

Définir `<AssemblyName>Lancer CollabHub</AssemblyName>` dans le projet launcher.

- [ ] **Step 2: Écrire tests rouges de chemin canonique**

```csharp
[TestMethod]
public void RejectsRepoRootWithoutAgentsFile() =>
  Assert.ThrowsException<LaunchConfigurationException>(() => LaunchPaths.Resolve(emptyDir));
```

- [ ] **Step 3: Implémenter résolveurs**

Exiger `AGENTS.md`, `.mcp.json`, `tools/mcp_singletons.ps1`, VS Code `code.cmd`,
le dernier Claude Code natif sous `.vscode/extensions/anthropic.claude-code-*`, et
une installation Codex contenant `codex-code-mode-host.exe`.

- [ ] **Step 4: Vérifier et commit**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Launcher.Tests -c Release`.

### Task 2: Orchestrateur idempotent

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/LaunchOrchestrator.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/IProcessBackend.cs`
- Test: `command_deck/tests/Titanium.CommandDeck.Launcher.Tests/LaunchOrchestratorTests.cs`

**Interfaces:**
- Produces: `LaunchOrchestrator.RunAsync(LaunchOptions, CancellationToken) -> LaunchReport`.

- [ ] **Step 1: Tester processus déjà actifs et port étranger**

```csharp
[TestMethod]
public async Task ForeignListenerBlocksWithoutKill() {
  var report = await orchestrator.RunAsync(options, default);
  Assert.AreEqual("FOREIGN_LISTENER", report.CollabHub.Code);
  Assert.AreEqual(0, processes.KillCalls);
}
```

- [ ] **Step 2: Implémenter séquence bornée**

Appeler `powershell.exe -NoProfile -File tools/mcp_singletons.ps1 start`, attendre
`/health` au plus 15 s, puis ouvrir WPF, `code -r <root>` et deux onglets Windows
Terminal. Réutiliser la fenêtre si son mutex global existe.

- [ ] **Step 3: Définir les commandes agent sans bypass**

Claude : binaire découvert, `--ide --continue`, cwd V12. Codex : binaire complet,
mode interactif, cwd V12. Aucun prompt automatique ne lance une mutation ; le
Command Deck publie le handoff de contexte que les agents lisent via MCP.

- [ ] **Step 4: Vérifier et commit ciblé**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Launcher.Tests -c Release`.

### Task 3: UI launcher et diagnostic partiel

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/App.xaml`
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/App.xaml.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Launcher/LaunchStatusWindow.xaml`
- Test: `command_deck/tests/Titanium.CommandDeck.Launcher.Tests/LaunchReportTests.cs`

**Interfaces:**
- Consumes: `LaunchReport`.
- Produces: fenêtre de progression et diagnostic, bouton `Réessayer` explicite.

- [ ] **Step 1: Tester que l'échec CollabHub empêche agents mais pas diagnostic**

Le report doit marquer WPF/VS Code/agents `SKIPPED_DEPENDENCY`, ne démarrer aucun
composant aval et conserver l'application de diagnostic ouverte.

- [ ] **Step 2: Implémenter fenêtre et mutex**

Nom du mutex : `Local\Titanium.CollabHub.CommandDeck.Launcher.v1`. Une seconde
instance focalise la première et quitte avec code 0.

- [ ] **Step 3: Vérifier et commit**

Run: `dotnet test command_deck/CommandDeck.sln -c Release`.

### Task 4: Publication et installation Bureau

**Files:**
- Create: `command_deck/Directory.Build.props`
- Create: `tools/publish_command_deck.ps1`
- Create: `tools/install_command_deck.ps1`
- Test: `tests/test_command_deck_packaging.py`

**Interfaces:**
- Produces: `dist/command-deck/Lancer CollabHub.exe`, `manifest.json`, raccourci Bureau.

- [ ] **Step 1: Écrire test rouge du script**

```python
def test_installer_supports_dry_run_and_never_requests_admin():
    source = Path('tools/install_command_deck.ps1').read_text('utf-8')
    assert 'SupportsShouldProcess' in source
    assert 'runas' not in source.lower()
```

- [ ] **Step 2: Implémenter publication reproductible**

Commandes exactes :

```powershell
dotnet publish command_deck/src/Titanium.CommandDeck/Titanium.CommandDeck.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o dist/command-deck/app
dotnet publish command_deck/src/Titanium.CommandDeck.Launcher/Titanium.CommandDeck.Launcher.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o dist/command-deck
```

Vérifier que `dist/command-deck/Lancer CollabHub.exe` lance explicitement
`dist/command-deck/app/Titanium.CommandDeck.exe`. Calculer SHA-256 de chaque
exécutable, écrire version/commit/runtime dans `manifest.json`, signer avec
`signtool` seulement si `COMMAND_DECK_CERT_THUMBPRINT` est défini.

- [ ] **Step 3: Installer sans privilège**

Copier les artefacts dans `%LOCALAPPDATA%\Titanium\CommandDeck`, créer un `.lnk`
`Lancer CollabHub` sur `[Environment]::GetFolderPath('Desktop')` et ne remplacer
qu'un raccourci dont la cible appartient à ce dossier.

- [ ] **Step 4: Vérifier et commit ciblé**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_command_deck_packaging.py -q`
Run: `powershell -NoProfile -File tools/install_command_deck.ps1 -WhatIf`
Expected: aucun fichier créé en `-WhatIf`.

### Task 5: E2E Windows et livraison

**Files:**
- Create: `tests/manual/command_deck_e2e.md`
- Modify: `collab/LOG.md`
- Modify: `collab/REVIEWS.md`

**Interfaces:**
- Produces: preuves de lancement, hash et verdict final.

- [ ] **Step 1: Exécuter toutes les suites**

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_*.py tests/test_collab_ui_routes.py tests/test_command_deck_packaging.py -q
node --test tests/js/collab_ui_*.test.mjs
dotnet test command_deck/CommandDeck.sln -c Release
```

- [ ] **Step 2: Installer et double-cliquer**

Vérifier 100/125/150 %, listeners déjà actifs, reconnexion, historique, message
Florent, échec suivi, retry manuel, VS Code et deux terminaux. Confirmer que
Titanium n'est pas démarré par le lanceur.

- [ ] **Step 3: Vérifier le périmètre GitNexus**

Run: `node .gitnexus/run.cjs detect-changes -s compare -b master -r titanium-v12 -l 200`
Documenter tout HIGH/CRITICAL avant livraison.

- [ ] **Step 4: Consigner et commit final ciblé**

Ajouter uniquement preuves, manifeste et documentation ; ne pas versionner les
binaires `dist/`. Publier le SHA-256 dans CollabHub et `collab/LOG.md`.
