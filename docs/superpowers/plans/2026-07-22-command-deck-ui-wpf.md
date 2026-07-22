# Command Deck Shared UI and WPF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le Command Deck A comme interface web partagée, puis l'héberger dans une fenêtre WPF WebView2.

**Architecture:** Le module `collab_ui` ne connaît que `HostBridge` et les API de lecture CollabHub. La coque WPF atteste Florent, porte les confirmations natives et transmet les intents ; Titanium pourra fournir un second HostBridge sans modifier les composants.

**Tech Stack:** HTML/CSS/ES2022 modules, Node 24 `node:test`, Python static routes, .NET 8 WPF, Microsoft.Web.WebView2 1.0.4078.44, MSTest template.

## Global Constraints

- Aucun framework frontend ni pipeline npm de production ; assets statiques audités.
- Aucun jeton dans URL, localStorage ou logs.
- Accessibilité clavier, DPI 100/125/150 %, responsive à 1024 px.
- Aucune primitive de trading, Registre ou processus dans `collab_ui`.

---

### Task 1: État UI pur et filtres

**Files:**
- Create: `collab_ui/index.html`
- Create: `collab_ui/styles.css`
- Create: `collab_ui/state.mjs`
- Test: `tests/js/collab_ui_state.test.mjs`

**Interfaces:**
- Produces: `createState()`, `reduce(state, event)`, `selectMessages(state, filter)`, `selectFailures(state, filter)` avec recherche texte locale normalisée.

- [ ] **Step 1: Écrire les tests Node rouges**

```javascript
test('filters by agent and keeps global offset order', () => {
  const state = reduce(createState(), {type:'messages.loaded', messages:[m(3,'codex'),m(1,'claude')]});
  assert.deepEqual(selectMessages(state,{principal:'codex'}).map(x=>x.global_offset), [3]);
});
```

- [ ] **Step 2: Vérifier l'échec**

Run: `node --test tests/js/collab_ui_state.test.mjs`
Expected: FAIL module absent.

- [ ] **Step 3: Implémenter reducer immuable et sélecteurs**

Dédupliquer par `message_id`, trier par `global_offset`, conserver
`UNKNOWN` comme état distinct et ne jamais muter l'entrée. La recherche combine
texte, agent, tâche, type, période et n'altère jamais le journal source.

- [ ] **Step 4: Vérifier puis commit**

```powershell
node --test tests/js/collab_ui_state.test.mjs
git add collab_ui/index.html collab_ui/styles.css collab_ui/state.mjs tests/js/collab_ui_state.test.mjs
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(command-deck): add shared UI state and shell"
```

### Task 2: Client temps réel et HostBridge

**Files:**
- Create: `collab_ui/api.mjs`
- Create: `collab_ui/host_bridge.mjs`
- Create: `collab_ui/app.mjs`
- Test: `tests/js/collab_ui_api.test.mjs`

**Interfaces:**
- Produces: `CollabClient.replay(afterOffset)`, `loadOlder(beforeOffset)`, `connect(onMessage)`, `HostBridge.postIntent(intent)`, `createWebViewBridge(chrome.webview)`.

- [ ] **Step 1: Tester replay puis reconnexion**

```javascript
test('replays after the last confirmed offset before reconnecting', async () => {
  const calls=[]; const client=new CollabClient({fetch: fakeFetch(calls), socketFactory: fakeSocket});
  await client.start(340);
  assert.equal(calls[0], '/v1/messages?after_offset=340&limit=500');
});
```

- [ ] **Step 2: Lancer rouge, implémenter, relancer vert**

Run: `node --test tests/js/collab_ui_api.test.mjs`
Expected final: PASS, backoff borné 1/2/5/10 s et replay avant socket.
Tester aussi la pagination antérieure sans doublon jusqu'au début du journal.

- [ ] **Step 3: Interdire les effets directs**

`HostBridge.postIntent` accepte uniquement `chat.publish`, `task.create`,
`task.retry.request`, `action.preview`, `host.open_vscode` et rejette toute autre valeur.

- [ ] **Step 4: Commit ciblé**

```powershell
git add collab_ui/api.mjs collab_ui/host_bridge.mjs collab_ui/app.mjs tests/js/collab_ui_api.test.mjs
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(command-deck): add realtime client and host intents"
```

### Task 3: Conversation, dock et échecs à suivre

**Files:**
- Create: `collab_ui/components/messages.mjs`
- Create: `collab_ui/components/agents.mjs`
- Create: `collab_ui/components/actions.mjs`
- Create: `collab_ui/components/failures.mjs`
- Modify: `collab_ui/index.html`
- Modify: `collab_ui/styles.css`
- Test: `tests/js/collab_ui_components.test.mjs`
- Test: `tests/test_collab_ui_static.py`

**Interfaces:**
- Produces: rendu DOM sûr via `textContent`, onglets `Conversation` et `Échecs à suivre`, dock avec états de capacité.

- [ ] **Step 1: Écrire tests de view-model et retry manuel**

```javascript
test('failure loading never creates a retry intent', () => {
  const state = reduce(createState(), {type:'failures.loaded', failures:[failure()]});
  assert.equal(state.pendingIntents.length, 0);
  assert.deepEqual(retryIntent(failure()), {type:'task.retry.request', task_id:'task-1'});
});
```

- [ ] **Step 2: Implémenter les quatre composants**

Utiliser exclusivement `createElement`/`textContent`, focus visible, labels ARIA,
compteur d'échecs non clos et états `Disponible/Validation/Double signature/Bloquée/Indisponible`.
Ajouter recherche plein texte, filtres agent/type/période et chargement explicite
des messages antérieurs.
Le test Python statique interdit `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
`eval` et toute temporisation qui appelle `retryIntent`.

- [ ] **Step 3: Vérifier**

Run: `node --test tests/js/collab_ui_*.test.mjs`
Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_ui_static.py -q`
Expected: PASS et aucune temporisation de retry dans le code.

- [ ] **Step 4: Commit ciblé**

```powershell
git add collab_ui tests/js
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(command-deck): render chat actions and failed tasks"
```

### Task 4: Route statique partagée

**Files:**
- Create: `collab_hub/ui_routes.py`
- Modify: `collab_hub/app.py`
- Test: `tests/test_collab_ui_routes.py`

**Interfaces:**
- Produces: `GET /ui/`, assets à type MIME exact, CSP locale stricte.

- [ ] **Step 1: Impact `create_app` puis test rouge**

Run: `node .gitnexus/run.cjs impact create_app -r titanium-v12 -d upstream`

```python
def test_ui_has_local_only_csp(client):
    response = client.get('/ui/')
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers['content-security-policy']
```

- [ ] **Step 2: Implémenter `create_ui_routes(root: Path) -> list[BaseRoute]`**

Refuser traversal, symlinks hors `collab_ui`, fichiers cachés et extensions non
allowlistées `.html/.css/.mjs/.svg/.woff2`.

- [ ] **Step 3: Vérifier et commit**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_ui_routes.py tests/test_collab_hub_api.py -q`
Expected: PASS.

### Task 5: Coque WPF et identité Windows

**Files:**
- Create: `command_deck/CommandDeck.sln`
- Create: `command_deck/src/Titanium.CommandDeck/Titanium.CommandDeck.csproj`
- Create: `command_deck/src/Titanium.CommandDeck/App.xaml`
- Create: `command_deck/src/Titanium.CommandDeck/MainWindow.xaml`
- Create: `command_deck/src/Titanium.CommandDeck/MainWindow.xaml.cs`
- Create: `command_deck/src/Titanium.CommandDeck/Services/WindowsIdentityService.cs`
- Create: `command_deck/src/Titanium.CommandDeck/Services/DpapiBootstrapKeyStore.cs`
- Create: `command_deck/src/Titanium.CommandDeck/Services/CollabSessionClient.cs`
- Create: `command_deck/src/Titanium.CommandDeck/Services/CollabHostBridge.cs`
- Create: `command_deck/tests/Titanium.CommandDeck.Tests/HostBridgeTests.cs`
- Create: `command_deck/tests/Titanium.CommandDeck.Tests/CollabSessionClientTests.cs`

**Interfaces:**
- Produces: `IWindowsIdentityService.CurrentSid`, `CollabSessionClient.OpenAsync`, `CollabHostBridge.HandleAsync(HostIntent, CancellationToken)`.

- [ ] **Step 1: Créer solution/projets et ajouter WebView2 épinglé**

```powershell
dotnet new sln -n CommandDeck -o command_deck
dotnet new wpf -n Titanium.CommandDeck -f net8.0 -o command_deck/src/Titanium.CommandDeck
dotnet new mstest -n Titanium.CommandDeck.Tests -f net8.0 -o command_deck/tests/Titanium.CommandDeck.Tests
dotnet add command_deck/src/Titanium.CommandDeck package Microsoft.Web.WebView2 --version 1.0.4078.44
dotnet sln command_deck/CommandDeck.sln add command_deck/src/Titanium.CommandDeck command_deck/tests/Titanium.CommandDeck.Tests
dotnet add command_deck/tests/Titanium.CommandDeck.Tests reference command_deck/src/Titanium.CommandDeck
```

- [ ] **Step 2: Écrire le test rouge du HostBridge**

```csharp
[TestMethod]
public async Task RejectsUnknownIntent() =>
  await Assert.ThrowsExceptionAsync<InvalidOperationException>(() =>
    bridge.HandleAsync(new HostIntent("registry.write.raw", "{}"), default));
```

- [ ] **Step 3: Implémenter la session Windows locale**

`CollabSessionClient.OpenAsync` obtient un nonce par `POST /v1/session/challenge`,
charge la clé bootstrap avec `DpapiBootstrapKeyStore`, calcule la preuve
HMAC-SHA256 liée au SID de `WindowsIdentityService.CurrentSid`, puis appelle
`POST /v1/session/windows`. Conserver le bearer token uniquement en mémoire du
processus WPF, l'ajouter aux appels HTTP/WebSocket, ne jamais le placer dans
l'URL, le DOM, le stockage WebView2 ou les logs et le détruire à la fermeture.
Tester challenge, preuve, expiration et refus d'un SID non attendu via un
`HttpMessageHandler` et un key store injectés.

- [ ] **Step 4: Implémenter WebView2 et bridge allowlisté**

Naviguer vers `http://127.0.0.1:8770/ui/`, vérifier l'origine de chaque
`WebMessageReceived`, désérialiser avec limite de taille 64 KiB et transmettre
les confirmations à la fenêtre native. Restreindre les requêtes à l'origine
CollabHub exacte et désactiver menus contextuels/outils développeur en build Release.

- [ ] **Step 5: Vérifier build/tests**

Run: `dotnet test command_deck/CommandDeck.sln -c Release`
Expected: PASS et build WPF net8.0-windows.

- [ ] **Step 6: Commit ciblé**

```powershell
git add command_deck
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(command-deck): host shared UI in native WPF"
```
