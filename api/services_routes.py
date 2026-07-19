# api/services_routes.py -- Controle des services externes via dashboard.
#
# GET  /services/status          Etat de tous les services
# POST /services/titan/start     Activer Titan
# POST /services/titan/stop      Desactiver Titan
# POST /services/ollama/start    Demarrer Ollama (subprocess)
# POST /services/ollama/stop     Arreter Ollama
# POST /services/gitnexus/start  Demarrer gitnexus serve
# POST /services/gitnexus/stop   Arreter l'instance geree par ce routeur

from __future__ import annotations
import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import aiohttp
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.auth import require_admin
from tools.claude_gitnexus_identity import read_attestation as read_claude_attestation
from tools.gitnexus_runtime import (
    GITNEXUS_BASE_URL,
    start_gitnexus_server,
    stop_gitnexus_server,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/services", tags=["services"])

# Toutes les mutations de ce routeur exigent le jeton admin (fail-closed).
_ADMIN = [Depends(require_admin)]

# Processus externes geres par cette route
_procs: dict[str, Optional[subprocess.Popen]] = {
    "ollama":   None,
    "gitnexus": None,
}

BASE_DIR = Path(__file__).resolve().parent.parent
GITNEXUS_PORT = 4747


# ── Helpers ───────────────────────────────────────────────────────────────────

def _proc_running(key: str) -> bool:
    p = _procs.get(key)
    return p is not None and p.poll() is None


async def _ollama_responding() -> bool:
    """Verifie si Ollama repond sur son port."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://localhost:11434/api/tags",
                             timeout=aiohttp.ClientTimeout(total=2)) as r:
                return r.status == 200
    except Exception:
        return False


async def _gitnexus_responding() -> tuple[bool, int]:
    """Verifie le contrat courant GitNexus, strictement sur localhost:4747."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GITNEXUS_BASE_URL}/api/health",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as response:
                return response.status == 200, GITNEXUS_PORT if response.status == 200 else 0
    except Exception:
        return False, 0


async def _gitnexus_repositories() -> list[dict]:
    """Retourne les depots indexes sans inventer de schema en cas d'erreur."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GITNEXUS_BASE_URL}/api/repos",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as response:
                if response.status != 200:
                    return []
                payload = await response.json()
    except Exception:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        repos = payload.get(
            "repos", payload.get("repositories", payload.get("value", []))
        )
        if isinstance(repos, list):
            return [item for item in repos if isinstance(item, dict)]
    return []


def _public_gitnexus_repositories(repositories: list[dict]) -> list[dict]:
    """Retire les chemins locaux et tout champ non prevu de la reponse API."""
    public: list[dict] = []
    allowed_stats = (
        "files",
        "nodes",
        "edges",
        "communities",
        "processes",
        "embeddings",
    )
    for repository in repositories:
        name = repository.get("name")
        if not isinstance(name, str) or not name:
            continue
        stats = repository.get("stats", {})
        safe_stats = {
            key: int(stats[key])
            for key in allowed_stats
            if isinstance(stats, dict) and isinstance(stats.get(key), (int, float))
        }
        public.append({"name": name, "stats": safe_stats})
    return public


# ── GET /services/status ──────────────────────────────────────────────────────

@router.get("/status")
async def services_status():
    """Retourne l'etat de tous les services."""

    # ── Titan ────────────────────────────────────────────────────────────────
    titan_info: dict = {"enabled": False, "running": False, "speaking": False, "ws_clients": 0}
    try:
        from assistant.config import TITAN_ENABLED
        from assistant.popup_manager import get_popup_manager
        from assistant.avatar_renderer import _titan_ws_clients
        titan_info["enabled"]    = TITAN_ENABLED
        titan_info["running"]    = TITAN_ENABLED
        titan_info["speaking"]   = get_popup_manager().is_speaking
        titan_info["ws_clients"] = len(_titan_ws_clients)
    except Exception:
        pass

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_ok = await _ollama_responding()
    ollama_model = ""
    if ollama_ok:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("http://localhost:11434/api/tags",
                                 timeout=aiohttp.ClientTimeout(total=2)) as r:
                    data = await r.json()
                    models = [m["name"] for m in data.get("models", [])]
                    ollama_model = models[0] if models else "?"
        except Exception:
            ollama_model = "?"

    ollama_info = {
        "running": ollama_ok,
        "model":   ollama_model,
        "proc":    _proc_running("ollama"),
    }

    # ── GitNexus ──────────────────────────────────────────────────────────────
    gn_ok, gn_port = await _gitnexus_responding()
    gn_repos = await _gitnexus_repositories() if gn_ok else []
    gn_symbols = 0
    for repo in gn_repos:
        stats = repo.get("stats", {}) if isinstance(repo.get("stats"), dict) else {}
        value = stats.get("nodes", stats.get("symbols", repo.get("symbols", 0)))
        if isinstance(value, (int, float)):
            gn_symbols += int(value)

    gitnexus_info = {
        "running": gn_ok,
        "port":    gn_port,
        "symbols": gn_symbols,
        "repos":    _public_gitnexus_repositories(gn_repos),
        "url":      "/nexus",
        "proc":    _proc_running("gitnexus"),
        "clients": {"claude": read_claude_attestation()},
    }

    return JSONResponse({
        "titan":    titan_info,
        "ollama":   ollama_info,
        "gitnexus": gitnexus_info,
    })


# ── Titan start/stop ─────────────────────────────────────────────────────────

@router.post("/titan/start", dependencies=_ADMIN)
async def titan_start():
    """Active Titan (necessite TITAN_ENABLED=1 dans .env et redemarrage complet).
    Sans redemarrage, active la parole et l'ecoute a chaud.
    """
    try:
        from assistant.titan_core import start_titan
        await start_titan()
        return JSONResponse({"status": "started", "message": "Titan demarre"})
    except Exception as e:
        logger.error("[SVC] titan start: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/titan/stop", dependencies=_ADMIN)
async def titan_stop():
    """Desactive Titan a chaud (ecoute + avatar)."""
    try:
        from assistant.titan_core import stop_titan
        await stop_titan()
        return JSONResponse({"status": "stopped", "message": "Titan arrete"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ── Ollama start/stop ─────────────────────────────────────────────────────────

@router.post("/ollama/start", dependencies=_ADMIN)
async def ollama_start():
    """Demarre le service Ollama en arriere-plan."""
    if await _ollama_responding():
        return JSONResponse({"status": "already_running", "message": "Ollama deja actif"})

    if _proc_running("ollama"):
        return JSONResponse({"status": "starting", "message": "Demarrage en cours..."})

    try:
        import shutil
        ollama_bin = shutil.which("ollama") or "ollama"
        p = subprocess.Popen(
            [ollama_bin, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _procs["ollama"] = p
        # Attendre que le service soit pret (max 8s)
        for _ in range(8):
            await asyncio.sleep(1)
            if await _ollama_responding():
                return JSONResponse({"status": "started", "message": "Ollama demarre (PID %d)" % p.pid})
        return JSONResponse({"status": "starting", "message": "Ollama demarre, attendre quelques secondes..."})
    except Exception as e:
        logger.error("[SVC] ollama start: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/ollama/stop", dependencies=_ADMIN)
async def ollama_stop():
    """Arrete Ollama (seulement si lance par ce dashboard)."""
    p = _procs.get("ollama")
    if p and p.poll() is None:
        p.terminate()
        _procs["ollama"] = None
        return JSONResponse({"status": "stopped", "message": "Ollama arrete"})
    return JSONResponse({"status": "not_managed",
                         "message": "Ollama non gere par ce dashboard (arreter manuellement)"})


# ── GitNexus start/stop ───────────────────────────────────────────────────────

@router.post("/gitnexus/start", dependencies=_ADMIN)
async def gitnexus_start():
    """Demarre l'instance GitNexus geree et authentifiable du projet."""
    if (await _gitnexus_responding())[0]:
        return JSONResponse({"status": "already_running", "message": "GitNexus deja actif"})
    process = await asyncio.to_thread(start_gitnexus_server)
    for _ in range(20):
        await asyncio.sleep(0.5)
        ok, port = await _gitnexus_responding()
        if ok:
            if process is not None:
                _procs["gitnexus"] = process
            pid = getattr(process, "pid", None)
            return JSONResponse({
                "status": "started",
                "message": f"GitNexus demarre sur port {port}",
                "pid": pid,
            })
    return JSONResponse(
        {"status": "error", "message": "GitNexus non sain apres demarrage"},
        status_code=503,
    )


@router.post("/gitnexus/stop", dependencies=_ADMIN)
async def gitnexus_stop():
    """Arrete uniquement l'instance enregistree, via shutdown authentifie."""
    stopped = await asyncio.to_thread(stop_gitnexus_server)
    if not stopped:
        return JSONResponse(
            {"status": "not_managed", "message": "Aucune instance geree arretee"},
            status_code=409,
        )
    _procs["gitnexus"] = None
    return JSONResponse({"status": "stopped", "message": "GitNexus arrete proprement"})


# ── GitHub push ───────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: str = None) -> tuple[int, str]:
    """Executes a git command and returns (returncode, output)."""
    import shutil
    git_bin = shutil.which("git") or "git"
    result = subprocess.run(
        [git_bin] + args,
        capture_output=True,
        text=True,
        cwd=cwd or str(BASE_DIR),
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout + result.stderr).strip()


@router.get("/github/status")
async def github_status():
    """Retourne l'état du dépôt Git local : branche, dernier commit, diff."""
    import asyncio as _asyncio

    def _fetch():
        # Vérifier d'abord si c'est un repo git
        code, _ = _git(["rev-parse", "--git-dir"])
        if code != 0:
            return None, None, None, None  # pas un repo git

        _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        _, remote = _git(["remote", "get-url", "origin"])
        _, last   = _git(["log", "-1", "--format=%h %s (%cr)", "--no-color"])
        _, diff   = _git(["status", "--short"])
        return branch, remote, last, diff

    try:
        loop = _asyncio.get_event_loop()
        branch, remote, last, diff = await loop.run_in_executor(None, _fetch)

        # Pas un repo git
        if branch is None:
            return JSONResponse({
                "branch":  "—",
                "remote":  "",
                "last":    "Aucun dépôt Git initialisé",
                "changes": 0,
                "files":   [],
            })

        changes = [l for l in (diff or "").splitlines() if l.strip()]
        return JSONResponse({
            "branch":  branch or "master",
            "remote":  remote or "",
            "last":    last or "—",
            "changes": len(changes),
            "files":   changes[:12],
        })
    except Exception as e:
        return JSONResponse({
            "branch": "—", "remote": "", "last": f"Erreur: {e}",
            "changes": 0, "files": [],
        })


_BRANCH_RE = __import__("re").compile(r"^[a-zA-Z0-9._\-/]{1,80}$")


def _validate_branch(branch: str) -> str:
    """Valide et nettoie le nom de branche — rejette tout caractère suspect."""
    branch = branch.strip()
    if not _BRANCH_RE.match(branch):
        raise ValueError(f"Nom de branche invalide: {branch!r}")
    # Bloquer les flags git déguisés en noms de branche
    if branch.startswith("-"):
        raise ValueError("La branche ne peut pas commencer par '-'")
    return branch


def _sanitize_commit_message(msg: str) -> str:
    """Supprime les retours à la ligne et caractères de contrôle du message de commit."""
    return msg.replace("\n", " ").replace("\r", " ").replace("\x00", "").strip()[:200]


@router.post("/github/push", dependencies=_ADMIN)
async def github_push(request: Request):
    """git add . → git commit → git push origin <branche>.

    Body JSON (optionnel) :
      { "message": "feat: mon commit", "branch": "master" }
    """
    import asyncio as _asyncio

    try:
        body    = await request.json()
        message = str(body.get("message", "")).strip()
        branch  = str(body.get("branch", "master")).strip() or "master"
    except Exception:
        message = ""
        branch  = "master"

    # Valider la branche (protection injection)
    try:
        branch = _validate_branch(branch)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

    # Nettoyer le message de commit
    if not message:
        from datetime import datetime
        message = f"update: Titanium v12 — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    message = _sanitize_commit_message(message)

    logs: list[str] = []
    loop = _asyncio.get_event_loop()

    # Toutes les opérations git dans run_in_executor — ne bloquent JAMAIS la boucle asyncio
    def _do_push() -> tuple[list[str], str, int]:
        _logs: list[str] = []

        # 1. git add .
        code, out = _git(["add", "."])
        _logs.append(f"git add . → {'OK' if code == 0 else 'ERREUR'}")
        if out:
            _logs.append(out[:200])
        if code != 0:
            return _logs, "add", code

        # 2. Vérifier s'il y a quelque chose à commiter
        _, diff = _git(["diff", "--cached", "--name-only"])
        if not diff.strip():
            return _logs, "nothing", 0

        # 3. git commit
        code, out = _git(["commit", "-m", message])
        _logs.append(f"git commit → {'OK' if code == 0 else 'ERREUR'}")
        if out:
            _logs.append(out[:300])
        if code != 0:
            return _logs, "commit", code

        # 4. git push
        code, out = _git(["push", "origin", branch])
        _logs.append(f"git push origin {branch} → {'OK' if code == 0 else 'ERREUR'}")
        if out:
            _logs.append(out[:400])
        return _logs, "push" if code != 0 else "ok", code

    logs, step, ret = await loop.run_in_executor(None, _do_push)

    if step == "nothing":
        return JSONResponse({
            "status":  "nothing_to_commit",
            "message": "Rien à commiter — le dépôt est déjà à jour.",
            "log":     logs,
        })
    if step != "ok":
        return JSONResponse({
            "status":  "error",
            "step":    step,
            "message": logs[-1] if logs else "Erreur inconnue",
            "log":     logs,
        }, status_code=500)

    return JSONResponse({
        "status":  "pushed",
        "message": f"Push réussi → {branch}",
        "commit":  message,
        "log":     logs,
    })
