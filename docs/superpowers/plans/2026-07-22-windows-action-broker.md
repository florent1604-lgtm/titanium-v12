# Windows Action Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fournir preview, validation Florent, sauvegarde, mutation allowlistée et audit pour fichiers locaux et Registre Windows.

**Architecture:** Une bibliothèque .NET sans UI évalue des requêtes typées contre une policy fermée. La WPF demande confirmation ; un exécuteur séparé applique seulement le digest prévisualisé. Les zones L4 autorisées passent par un helper minimal distinct, élevé par UAC, qui revérifie le digest et le nonce avant tout effet.

**Tech Stack:** .NET 8, Microsoft.Win32.Registry, System.Security.Cryptography, MSTest.

## Global Constraints

- Hermes ne reçoit aucune interface broker.
- Aucune opération arbitraire, récursive, shell ou ligne de commande libre.
- Preview et digest obligatoires ; expiration 15 minutes ; nonce consommé une fois.
- Sauvegarde Registre avant mutation ; aucun rollback automatique.

---

### Task 1: Contrats et policy fermée

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Broker/Titanium.CommandDeck.Broker.csproj`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/Contracts.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/BrokerPolicy.cs`
- Create: `command_deck/tests/Titanium.CommandDeck.Broker.Tests/Titanium.CommandDeck.Broker.Tests.csproj`
- Create: `command_deck/tests/Titanium.CommandDeck.Broker.Tests/BrokerPolicyTests.cs`

**Interfaces:**
- Produces: `ActionRequest`, `ActionPreview`, `ActionApproval`, `ActionResult`, `BrokerPolicy.Evaluate(ActionRequest)`.

- [ ] **Step 1: Créer les projets et les rattacher à la solution**

```powershell
dotnet new classlib -n Titanium.CommandDeck.Broker -f net8.0 -o command_deck/src/Titanium.CommandDeck.Broker
dotnet new mstest -n Titanium.CommandDeck.Broker.Tests -f net8.0 -o command_deck/tests/Titanium.CommandDeck.Broker.Tests
dotnet sln command_deck/CommandDeck.sln add command_deck/src/Titanium.CommandDeck.Broker command_deck/tests/Titanium.CommandDeck.Broker.Tests
dotnet add command_deck/tests/Titanium.CommandDeck.Broker.Tests reference command_deck/src/Titanium.CommandDeck.Broker
```

- [ ] **Step 2: Écrire tests rouges**

```csharp
[DataTestMethod]
[DataRow("HKLM\\SYSTEM\\CurrentControlSet\\Services\\TitaniumDemo")]
public void AllowlistedCriticalRegistryRootsRequireElevation(string key) =>
  Assert.AreEqual(Decision.RequiresElevation, policy.Evaluate(RegistrySet(key)).Decision);

[DataTestMethod]
[DataRow("HKLM\\SAM")]
[DataRow("HKLM\\SECURITY")]
public void CredentialStoresAreAlwaysDenied(string key) =>
  Assert.AreEqual(Decision.Denied, policy.Evaluate(RegistrySet(key)).Decision);
```

- [ ] **Step 3: Implémenter enum et policy**

Types exacts : `OpenPath`, `StartManagedService`, `RegistrySetValue`,
`FileReplace`. Toute valeur inconnue retourne `DeniedUnknownCapability`.

- [ ] **Step 4: Vérifier et commit**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Broker.Tests -c Release`
Expected: PASS.

### Task 2: Canonicalisation fichiers et Registre

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Broker/PathGuard.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/RegistryGuard.cs`
- Test: `command_deck/tests/Titanium.CommandDeck.Broker.Tests/GuardTests.cs`

**Interfaces:**
- Produces: `PathGuard.ResolveInsideAllowedRoot`, `RegistryGuard.NormalizeKey`.

- [ ] **Step 1: Tester traversal, junction et alias de hive**

```csharp
[TestMethod]
public void RejectsTraversalOutsideApprovedRoot() =>
  Assert.ThrowsException<PolicyDenied>(() => guard.ResolveInsideAllowedRoot(root, @"..\secret"));
```

- [ ] **Step 2: Implémenter résolution finale**

Comparer les chemins normalisés avec `StringComparison.OrdinalIgnoreCase`, ouvrir
les handles sans suivre un reparse point hors racine et normaliser HKCU/HKEY_CURRENT_USER.

- [ ] **Step 3: Vérifier et commit ciblé**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Broker.Tests -c Release`.

### Task 3: Preview, approbation et anti-rejeu

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Broker/PreviewService.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/ApprovalLedger.cs`
- Test: `command_deck/tests/Titanium.CommandDeck.Broker.Tests/ApprovalTests.cs`

**Interfaces:**
- Produces: `PreviewService.Build`, `ApprovalLedger.Approve`, `Consume`.

- [ ] **Step 1: Tester digest, TTL et nonce**

Le test modifie une valeur après preview et attend `DigestMismatch`, consomme
deux fois le nonce et attend `ReplayRejected`, puis avance 901 s et attend `Expired`.

- [ ] **Step 2: Implémenter JSON canonique SHA-256**

Le digest couvre capability, cible canonique, ancienne/nouvelle valeur, SID,
timestamp d'expiration et nonce. Le ledger SQLite ne stocke aucun contenu secret.

- [ ] **Step 3: Vérifier et commit ciblé**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Broker.Tests -c Release`.

### Task 4: Exécution avec backends injectables

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Broker/IRegistryBackend.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/IFileBackend.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/ActionExecutor.cs`
- Test: `command_deck/tests/Titanium.CommandDeck.Broker.Tests/ActionExecutorTests.cs`

**Interfaces:**
- Produces: `ActionExecutor.ExecuteAsync(ActionApproval, CancellationToken)`.

- [ ] **Step 1: Tester backup avant écriture et résultat UNKNOWN**

```csharp
[TestMethod]
public async Task RegistryBackupPrecedesMutation() {
  await executor.ExecuteAsync(approval, default);
  CollectionAssert.AreEqual(new[]{"backup","set","verify","audit"}, backend.Calls);
}
```

- [ ] **Step 2: Implémenter transaction logique**

Refuser si preview/état courant divergent. Après écriture, relire et comparer ;
une interruption après effet retourne `UnknownEffect` et exige vérification.

- [ ] **Step 3: Vérifier et commit ciblé**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Broker.Tests -c Release`.

### Task 5: Helper élevé UAC, digest exact et anti-rejeu

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck.Broker.Elevated/Titanium.CommandDeck.Broker.Elevated.csproj`
- Create: `command_deck/src/Titanium.CommandDeck.Broker.Elevated/app.manifest`
- Create: `command_deck/src/Titanium.CommandDeck.Broker.Elevated/Program.cs`
- Create: `command_deck/src/Titanium.CommandDeck.Broker/ElevationClient.cs`
- Create: `command_deck/tests/Titanium.CommandDeck.Broker.Tests/ElevationProtocolTests.cs`

**Interfaces:**
- Produces: `ElevationClient.ExecuteAsync(ActionApproval, CancellationToken)` et un helper `requireAdministrator` sans interface de commande libre.

- [ ] **Step 1: Créer le projet helper et l'ajouter à la solution**

```powershell
dotnet new console -n Titanium.CommandDeck.Broker.Elevated -f net8.0 -o command_deck/src/Titanium.CommandDeck.Broker.Elevated
dotnet sln command_deck/CommandDeck.sln add command_deck/src/Titanium.CommandDeck.Broker.Elevated
dotnet add command_deck/src/Titanium.CommandDeck.Broker.Elevated reference command_deck/src/Titanium.CommandDeck.Broker
```

- [ ] **Step 2: Tester le protocole fermé**

Les tests doivent rejeter un digest absent ou modifié, un nonce expiré/réutilisé,
un SID différent et toute capability non L4 allowlistée. Aucun chemin, clé ou
nouvelle valeur n'est accepté séparément du payload canonique approuvé.

- [ ] **Step 3: Implémenter l'élévation distincte**

Lancer le helper avec `UseShellExecute=true` et `Verb=runas`. Transmettre le
payload canonique par un named pipe local ACLé au SID Florent ; passer sur la
ligne de commande uniquement un identifiant opaque à usage unique. Le helper
revérifie SID, digest, TTL, nonce et état courant, écrit la sauvegarde, applique,
relit, audite puis ferme. Annuler l'UAC retourne `DeniedByUser`, sans repli.

- [ ] **Step 4: Vérifier automatiquement puis manuellement l'UAC**

Run: `dotnet test command_deck/tests/Titanium.CommandDeck.Broker.Tests -c Release`
Expected: PASS. Vérification manuelle : un seul prompt UAC séparé, refus sans
effet, approbation limitée au digest affiché, aucune console élevée persistante.

### Task 6: Confirmation WPF et intégration

**Files:**
- Create: `command_deck/src/Titanium.CommandDeck/Views/ActionConfirmation.xaml`
- Create: `command_deck/src/Titanium.CommandDeck/Views/ActionConfirmation.xaml.cs`
- Modify: `command_deck/src/Titanium.CommandDeck/Services/CollabHostBridge.cs`
- Test: `command_deck/tests/Titanium.CommandDeck.Tests/ActionConfirmationTests.cs`

**Interfaces:**
- Consumes: `ActionPreview`, `ActionExecutor`.
- Produces: une confirmation visible, jamais un bool implicite.

- [ ] **Step 1: Tester fermeture/timeout/refus**

Fermer la fenêtre, laisser expirer ou changer de session doit retourner `Denied`
et ne jamais appeler `ExecuteAsync`.

- [ ] **Step 2: Référencer le broker depuis la coque et ses tests**

```powershell
dotnet add command_deck/src/Titanium.CommandDeck reference command_deck/src/Titanium.CommandDeck.Broker
dotnet add command_deck/tests/Titanium.CommandDeck.Tests reference command_deck/src/Titanium.CommandDeck.Broker
```

- [ ] **Step 3: Implémenter le dialogue**

Afficher cible, ancien/nouveau, niveau, impact, sauvegarde et digest court. Une
action L4 affiche d'abord cette confirmation puis déclenche le prompt UAC séparé ;
un refus à l'une des deux étapes est définitif pour ce nonce.

- [ ] **Step 4: Suite et commit**

Run: `dotnet test command_deck/CommandDeck.sln -c Release`
Expected: PASS, aucune référence broker dans `collab_ui`.
