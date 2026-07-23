# GitNexus Common Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire de GitNexus la cartographie locale, fraîche et commune de Titanium et JARVIS, accessible à Florent par `/nexus` et aux trois agents par MCP, sans perturber le bot paper 24/7.

**Architecture:** Le dépôt v12 reste l’index canonique. Un runtime Python testable synchronise une vue JARVIS strictement assainie dans `%LOCALAPPDATA%\Titanium\gitnexus\jarvis-runtime`, pilote l’analyse incrémentale basse priorité et suspend les analyses durant `opportunity_scan`. GitNexus `serve` expose le registre multi-dépôts sur `4747`; Titanium ajoute `/nexus` et aligne son panneau Services, tandis que `/orbe` reste sous responsabilité Claude et consomme déjà le graphe GitNexus.

**Tech Stack:** Python 3.12 stdlib, FastAPI/aiohttp existants, PowerShell/VS Code Tasks, GitNexus CLI/MCP via `npx.cmd gitnexus@latest`, pytest.

## Global Constraints

- PAPER ONLY permanent ; aucune route GitNexus n’autorise une mutation de trading.
- GitNexus reste lié à localhost et ne reçoit aucun secret.
- Ne jamais copier `.env`, credentials, conversations, mémoires, `knowledge/`, venv, caches, backups ou audio JARVIS.
- Watcher en priorité basse, une analyse à la fois, pause lorsque `/opportunities/status.running=true`.
- `data/*.json` ne déclenche aucune réindexation.
- Impact GitNexus obligatoire pour `core/`, `execution/`, `domain/`, `api/` et modules d’état `utils/`; fallback local si MCP indisponible.
- `titanium_orbe.html`, `titanium_orbe_v1.html` et `tools/gen_neural_map.py` sont réservés Claude et interdits dans ce plan.
- `/orbe` reste l’orbe ; GitNexus utilise `/nexus`.
- Start/stop restent protégés par `require_admin`; statut et `/nexus` sont en lecture seule.
- Aucun commit, push ou reset dans l’arbre partagé sans nouvelle autorisation Florent.

---

### Task 1: Politique d’assainissement et miroir JARVIS

**Files:**
- Create: `tools/gitnexus_runtime.py`
- Create: `tests/test_gitnexus_runtime.py`

**Interfaces:**
- Produces: `is_jarvis_source_allowed(relative_path: PurePath) -> bool`
- Produces: `sync_jarvis_mirror(source: Path, destination: Path) -> MirrorReport`
- Produces: `MirrorReport(copied: int, unchanged: int, removed: int, rejected: int, manifest_path: Path)`

- [ ] **Step 1: Écrire le test rouge de whitelist et de refus des secrets**

Créer des fixtures temporaires contenant `main2.py`, `frontend/app.js`, `.env`,
`credentials_LISEZ_MOI.txt`, `jarvis_conversations.json`, `jarvis_memoire.json`,
`knowledge/private.md`, `main2.py.bak-cutover`, `voice.mp3` et `venv/x.py`.

```python
def test_sync_jarvis_mirror_copies_sources_and_rejects_sensitive_paths(tmp_path):
    source = tmp_path / "jarvis"
    mirror = tmp_path / "mirror"
    write_tree(source, {
        "main2.py": "print('ok')",
        "frontend/app.js": "export const ok = true",
        ".env": "SECRET=x",
        "credentials_LISEZ_MOI.txt": "secret",
        "jarvis_conversations.json": "[]",
        "jarvis_memoire.json": "{}",
        "knowledge/private.md": "private",
        "main2.py.bak-cutover": "old",
        "voice.mp3": "audio",
        "venv/x.py": "third party",
    })
    report = sync_jarvis_mirror(source, mirror)
    assert (mirror / "main2.py").exists()
    assert (mirror / "frontend/app.js").exists()
    for forbidden in (
        ".env", "credentials_LISEZ_MOI.txt", "jarvis_conversations.json",
        "jarvis_memoire.json", "knowledge/private.md",
        "main2.py.bak-cutover", "voice.mp3", "venv/x.py",
    ):
        assert not (mirror / forbidden).exists()
    assert report.rejected == 8
```

- [ ] **Step 2: Exécuter le test et vérifier le rouge**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_runtime.py::test_sync_jarvis_mirror_copies_sources_and_rejects_sensitive_paths -q -p no:cacheprovider`

Expected: FAIL à l’import de `tools.gitnexus_runtime`.

- [ ] **Step 3: Implémenter la politique minimale**

Le module définit des tuples immuables :

```python
ALLOWED_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
                    ".vue", ".html", ".css", ".scss", ".json", ".yaml",
                    ".yml", ".toml", ".md", ".ps1", ".bat", ".cmd"}
ALLOWED_EXACT_FILES = {"requirements.txt"}
DENIED_DIRS = {"venv", ".venv", "__pycache__", "node_modules", "knowledge",
               "data", "cache", "audio_cache", "logs", "backups"}
DENIED_NAMES = {".env", "jarvis_conversations.json", "jarvis_memoire.json",
                "auth.json", "secrets.json"}
DENIED_SUFFIXES = {".mp3", ".wav", ".ogg", ".flac", ".key"}
```

Refuser aussi tout nom contenant `credential`, `secret`, `token`, `.bak-` ou
`.bak.`. Résoudre chaque destination et vérifier qu’elle reste sous le miroir.
Écrire `mirror_manifest.json` avec source canonique, timestamp UTC, hashes SHA-256,
fichiers copiés et fichiers rejetés par catégorie, sans contenu source.

- [ ] **Step 4: Ajouter le test de suppression des fichiers devenus obsolètes**

```python
def test_sync_removes_stale_mirrored_source(tmp_path):
    source, mirror = tmp_path / "src", tmp_path / "mirror"
    write_tree(source, {"old.py": "x=1"})
    sync_jarvis_mirror(source, mirror)
    (source / "old.py").unlink()
    report = sync_jarvis_mirror(source, mirror)
    assert not (mirror / "old.py").exists()
    assert report.removed == 1
```

- [ ] **Step 5: Exécuter les tests miroir**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_runtime.py -q -p no:cacheprovider`

Expected: tous les tests Task 1 PASS.

### Task 2: Détection de changements, debounce et pause opportunity scan

**Files:**
- Modify: `tools/gitnexus_runtime.py`
- Modify: `tests/test_gitnexus_runtime.py`

**Interfaces:**
- Produces: `is_index_relevant(relative_path: PurePath) -> bool`
- Produces: `ChangeDebouncer(debounce_seconds: float, max_delay_seconds: float)`
- Produces: `opportunity_scan_running(url: str, timeout: float = 2.0) -> bool`
- Produces: `spawn_low_priority(argv: Sequence[str], cwd: Path) -> subprocess.Popen`

- [ ] **Step 1: Écrire les tests rouges anti-churn et debounce**

```python
@pytest.mark.parametrize("path", [
    "data/paper_state.json", "data/swing_paper_state.json",
    "data/opportunities.json", "signal_history.json", "titanium_v12.log",
])
def test_runtime_data_does_not_trigger_index(path):
    assert not is_index_relevant(PurePath(path))

@pytest.mark.parametrize("path", [
    "core/swing_engine.py", "execution/paper_trading.py",
    "api/services_routes.py", "tests/test_guards.py", "docs/STRATEGY_CONTRACT.md",
])
def test_sources_trigger_index(path):
    assert is_index_relevant(PurePath(path))
```

- [ ] **Step 2: Vérifier le rouge ciblé**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_runtime.py -k "trigger_index or runtime_data" -q -p no:cacheprovider`

Expected: FAIL fonctions absentes.

- [ ] **Step 3: Implémenter le filtre et le debounce déterministe**

`ChangeDebouncer.note_change(now)` fixe le début et la dernière modification.
`ready(now)` devient vrai après 5 secondes sans changement ou 15 secondes depuis
le premier changement. `reset()` réinitialise l’état après analyse.

- [ ] **Step 4: Ajouter les tests de pause et priorité basse**

Monkeypatcher `urllib.request.urlopen` pour réponses `{"running": true}` et
`{"running": false}`. Sous Windows, monkeypatcher `subprocess.Popen` et vérifier
que `creationflags` contient `BELOW_NORMAL_PRIORITY_CLASS` et
`CREATE_NO_WINDOW`.

- [ ] **Step 5: Implémenter la pause et le spawn**

`opportunity_scan_running` est fail-safe pour la charge CPU : erreur HTTP ou JSON
invalide retourne `True`, donc aucune analyse lourde n’est lancée lorsque l’état du
scan ne peut être connu. Le serveur `serve`, léger, peut rester actif.

- [ ] **Step 6: Rejouer les tests runtime**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_runtime.py -q -p no:cacheprovider`

Expected: PASS.

### Task 3: CLI session/watch, registre local et autostart VS Code

**Files:**
- Modify: `tools/gitnexus_runtime.py`
- Create: `tools/start_gitnexus.ps1`
- Create: `.vscode/tasks.json`
- Modify: `.gitignore`
- Create: `.gitnexusignore`
- Modify: `tests/test_gitnexus_runtime.py`

**Interfaces:**
- Produces CLI: `python tools/gitnexus_runtime.py session [--open-browser] [--no-watch]`
- Produces CLI: `python tools/gitnexus_runtime.py watch`
- Produces CLI: `python tools/gitnexus_runtime.py sync-jarvis`
- Produces CLI: `python tools/gitnexus_runtime.py status --json`

- [ ] **Step 1: Écrire le test rouge de plan de session idempotent**

Injecter clients health/repos et vérifier : serveur sain + deux dépôts frais ne
produit aucune commande de démarrage/analyse ; dépôt absent produit sync+analyze ;
serveur absent produit `serve` une seule fois.

- [ ] **Step 2: Implémenter `GitNexusRuntime`**

Constantes :

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
JARVIS_SOURCE = Path(r"C:\Program Files\JARVIS")
RUNTIME_ROOT = Path(os.environ["LOCALAPPDATA"]) / "Titanium" / "gitnexus"
JARVIS_MIRROR = RUNTIME_ROOT / "jarvis-runtime"
GITNEXUS_BASE_URL = "http://localhost:4747"
```

Initialiser le miroir comme dépôt Git local sans remote. Créer un snapshot local
uniquement si le manifeste change. Pour v12, utiliser
`node .gitnexus/run.cjs analyze --pdg`; pour le premier index miroir utiliser
`cmd /d /s /c npx -y gitnexus@latest analyze --pdg`.

- [ ] **Step 3: Implémenter le watcher mono-instance**

Utiliser un fichier PID sous `RUNTIME_ROOT`. Vérifier que le PID vit avant de
refuser une seconde instance. Polling toutes les 2 secondes, filtre Task 2,
debounce 5/15 secondes, pause opportunity scan, une analyse à la fois et nouvelle
passe si le snapshot a changé pendant l’analyse.

- [ ] **Step 4: Créer le lanceur PowerShell**

`tools/start_gitnexus.ps1` résout le Python du venv v12 et lance :

```powershell
& $python "$PSScriptRoot\gitnexus_runtime.py" session --open-browser
```

Le script accepte `-NoBrowser` pour les sessions agents.

- [ ] **Step 5: Créer la tâche VS Code**

`.vscode/tasks.json` contient une tâche `Titanium: GitNexus session` avec
`runOptions.runOn = "folderOpen"`, type `process`, commande PowerShell et le
lanceur projet. Modifier `.gitignore` pour suivre uniquement `.vscode/tasks.json`.

- [ ] **Step 6: Créer `.gitnexusignore`**

Exclure explicitement `.gitnexus/`, venv, caches, logs, backups, fichiers paper
state/journal, `data/opt_cache/`, images générées, `signal_history.json` et tout
secret. Ne pas exclure les sources, tests, contrats ni configurations validées.

- [ ] **Step 7: Vérifier les tests et le mode status**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_runtime.py -q -p no:cacheprovider`

Run: `venv\Scripts\python.exe tools\gitnexus_runtime.py status --json`

Expected: tests PASS ; JSON sans secret contenant santé, dépôts et fraîcheur.

### Task 4: Configurer le MCP commun Claude, Codex et Hermes

**Files:**
- Modify: `.mcp.json`
- Create: `tools/configure_gitnexus_mcp.ps1`
- Create: `tests/test_gitnexus_mcp_config.py`
- Modify: `collab/HERMES_BRIDGE.md`

**Interfaces:**
- Claude stdio: `cmd /c npx -y gitnexus@latest mcp`
- Codex global: `codex mcp add gitnexus -- cmd /c npx -y gitnexus@latest mcp`
- Hermes global: `hermes mcp add gitnexus --command cmd --args /c npx -y gitnexus@latest mcp`

- [ ] **Step 1: Écrire le test rouge de configuration projet Claude**

```python
def test_gitnexus_mcp_is_declared_without_secrets():
    cfg = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
    server = cfg["mcpServers"]["gitnexus"]
    assert server == {
        "command": "cmd",
        "args": ["/c", "npx", "-y", "gitnexus@latest", "mcp"],
    }
    assert "env" not in server
```

- [ ] **Step 2: Vérifier le rouge puis modifier `.mcp.json`**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_mcp_config.py -q -p no:cacheprovider`

Expected avant édition: FAIL clé `gitnexus` absente. Après édition: PASS.

- [ ] **Step 3: Créer le configurateur idempotent**

Le script liste d’abord les serveurs Codex et Hermes. Il n’ajoute que si absent ;
si présent, il lance seulement les tests de connexion. Aucun token ni variable
d’environnement n’est transmis.

- [ ] **Step 4: Configurer et tester les deux clients**

Run: `powershell -ExecutionPolicy Bypass -File tools\configure_gitnexus_mcp.ps1`

Run: `hermes mcp test gitnexus`

Run: `codex mcp list`

Expected: GitNexus présent et handshake/outils découverts. Une nouvelle session
Codex/Claude peut être requise pour charger le serveur ; le script le signale sans
redémarrer les applications lui-même.

- [ ] **Step 5: Documenter le même registre**

Mettre à jour `collab/HERMES_BRIDGE.md` avec commandes de test, règle de fraîcheur,
fallback local et interdiction d’utiliser MCP comme autorisation de mutation.

### Task 5: Aligner le panneau Services sur GitNexus 4747

**Files:**
- Modify: `api/services_routes.py`
- Create: `tests/test_gitnexus_services.py`

**Interfaces:**
- Produces: `_gitnexus_status() -> dict`
- `/services/status.gitnexus`: `running`, `port`, `repos`, `nodes`, `edges`, `processes`, `indexed_at`, `proc`

- [ ] **Step 1: Exécuter l’impact analysis**

Utiliser GitNexus `impact` pour `_gitnexus_responding`, `services_status`,
`gitnexus_start` et `gitnexus_stop`. À défaut de MCP après une tentative documentée,
rapporter le blast radius local : route `/services/status` et routes admin start/stop,
aucun chemin de décision ou d’ouverture de position.

- [ ] **Step 2: Écrire les tests rouges API**

Monkeypatcher le client HTTP pour `/api/health` et `/api/repos`. Vérifier port 4747,
sélection du dépôt au chemin exact v12, agrégation des statistiques et état
indisponible explicite. Vérifier aussi que POST start/stop répond 403 sans token.

- [ ] **Step 3: Vérifier le rouge**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_services.py -q -p no:cacheprovider`

Expected: FAIL car anciens ports/routes.

- [ ] **Step 4: Implémenter le statut 4747**

Remplacer les sondes multiples par `http://localhost:4747/api/health`, puis
`/api/repos`. Retourner les statistiques du dépôt exact et la liste résumée des
dépôts. Aucun état manquant ne doit devenir un faux zéro rassurant.

- [ ] **Step 5: Corriger la commande de démarrage**

Utiliser la commande actuelle `serve` via `cmd /d /s /c npx -y gitnexus@latest serve`.
Conserver `_ADMIN` sur start/stop et ne jamais tuer un processus non géré par Titanium.

- [ ] **Step 6: Rejouer les tests Services et auth**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_services.py tests\test_mutation_auth.py -q -p no:cacheprovider`

Expected: PASS.

### Task 6: Ajouter la route lecture seule `/nexus`

**Files:**
- Modify: `api/api_server.py`
- Create: `tests/test_nexus_route.py`

**Interfaces:**
- Produces: `GET /nexus` → redirect 307 vers `http://localhost:4747/` si sain, sinon HTML 503 fail-visible.

- [ ] **Step 1: Exécuter l’impact analysis de la route API**

Analyser `dashboard_orbe` et la zone des routes dashboard pour confirmer que `/nexus`
est additive et ne modifie ni `/`, ni `/orbe`, ni `/orbe/map`.

- [ ] **Step 2: Écrire les tests rouges**

```python
def test_nexus_redirects_when_gitnexus_is_healthy(client, monkeypatch):
    monkeypatch.setattr("api.api_server._gitnexus_ui_available", async_true)
    r = client.get("/nexus", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "http://localhost:4747/"

def test_nexus_is_fail_visible_when_down(client, monkeypatch):
    monkeypatch.setattr("api.api_server._gitnexus_ui_available", async_false)
    r = client.get("/nexus")
    assert r.status_code == 503
    assert "GitNexus indisponible" in r.text
```

- [ ] **Step 3: Implémenter la route minimale**

Utiliser `RedirectResponse`. Le HTML 503 indique `/services/status` et le lanceur
local, sans bouton de mutation ni token. Ne toucher à aucun fichier orbe réservé.

- [ ] **Step 4: Rejouer les tests route/import**

Run: `venv\Scripts\python.exe -m pytest tests\test_nexus_route.py tests\test_main_startup.py -q -p no:cacheprovider`

Expected: PASS et import API sans nouvelle route mutante.

### Task 7: Réindexation, mesures et revue avant production

**Files:**
- Modify: `collab/TASKS.md`
- Modify: `collab/LOG.md`
- Modify: `collab/REVIEWS.md`

**Interfaces:**
- Consumes tous les livrables Tasks 1–6.

- [ ] **Step 1: Lancer la suite ciblée complète**

Run: `venv\Scripts\python.exe -m pytest tests\test_gitnexus_runtime.py tests\test_gitnexus_mcp_config.py tests\test_gitnexus_services.py tests\test_nexus_route.py tests\test_mutation_auth.py tests\test_main_startup.py -q -p no:cacheprovider`

Expected: 0 échec, 0 warning nouveau.

- [ ] **Step 2: Tester l’assainissement réel sans afficher de secret**

Lancer `sync-jarvis`, puis vérifier uniquement chemins/hashes du manifeste. Rechercher
les noms interdits dans le miroir et exiger zéro résultat. Ne jamais afficher le
contenu d’un fichier refusé.

- [ ] **Step 3: Mesurer charge et fraîcheur**

Déclencher une modification contrôlée dans une fixture surveillée, mesurer délai
jusqu’au nouvel `indexedAt`, CPU/durée du processus basse priorité, puis prouver que
`data/paper_state.json` ne déclenche rien et que `running=true` suspend l’analyse.

- [ ] **Step 4: Démarrer GitNexus sans navigateur pour vérification**

Run: `powershell -ExecutionPolicy Bypass -File tools\start_gitnexus.ps1 -NoBrowser`

Vérifier `4747/api/health`, `4747/api/repos`, présence `titanium-v12` et
`jarvis-runtime`, chemins exacts et statistiques non nulles.

- [ ] **Step 5: Demander revue Claude et Hermes**

Envoyer sur le bus : fichiers, résultats tests, manifeste assaini, budget CPU,
fraîcheur, handshakes MCP et limites. Exiger verdict avant production.

- [ ] **Step 6: Appliquer les retours bloquants et rejouer les preuves**

Tout P0/P1 valide retourne au cycle test rouge/vert correspondant. Ne pas passer en
production sur simple accusé de réception.

- [ ] **Step 7: Relancer en mode session utilisateur après approbation**

Arrêter uniquement l’ancienne instance GitNexus identifiée, lancer
`tools/start_gitnexus.ps1`, ouvrir une fois `4747`, vérifier `/nexus`, `/orbe`,
`/services/status`, puis consigner PID, ports, dépôts et verdicts dans LOG/TASKS.

## Self-Review

- Couverture spec : miroir, secrets, freshness, CPU/pause, MCP quatre participants,
  autostart, `/nexus`, Services 4747, auth, anti-churn, rollback et revues sont mappés.
- Réservations Claude : aucun fichier orbe/neural map dans les tâches Codex.
- Types/interfaces : les fonctions produites dans Tasks 1–3 sont réutilisées par
  les CLI et tests ; Services/API restent indépendants du watcher.
- Placeholders : aucun TBD/TODO ou étape « tester ensuite » sans commande attendue.
- Gouvernance : pas de commit/push, pas de production avant double revue.
