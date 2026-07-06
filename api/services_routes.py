# api/services_routes.py -- Controle des services externes via dashboard.
#
# GET  /services/status          Etat de tous les services
# POST /services/titan/start     Activer Titan
# POST /services/titan/stop      Desactiver Titan
# POST /services/ollama/start    Demarrer Ollama (subprocess)
# POST /services/ollama/stop     Arreter Ollama
# POST /services/gitnexus/start  Demarrer gitnexus server
# POST /services/gitnexus/stop   Arreter gitnexus server

from __future__ import annotations
import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/services", tags=["services"])

# Processus externes geres par cette route
_procs: dict[str, Optional[subprocess.Popen]] = {
    "ollama":   None,
    "gitnexus": None,
}

BASE_DIR = Path(__file__).resolve().parent.parent


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
    """Verifie si gitnexus server repond (port 3000 par defaut)."""
    for port in (3000, 3001, 4000):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://localhost:{port}/health",
                                 timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status < 500:
                        return True, port
        except Exception:
            pass
    return False, 0


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
    gn_symbols = "?"
    if gn_ok:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://localhost:{gn_port}/api/graph/stats",
                                 timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        data = await r.json()
                        gn_symbols = data.get("symbols", "?")
        except Exception:
            pass

    gitnexus_info = {
        "running": gn_ok,
        "port":    gn_port,
        "symbols": gn_symbols,
        "proc":    _proc_running("gitnexus"),
    }

    return JSONResponse({
        "titan":    titan_info,
        "ollama":   ollama_info,
        "gitnexus": gitnexus_info,
    })


# ── Titan start/stop ─────────────────────────────────────────────────────────

@router.post("/titan/start")
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


@router.post("/titan/stop")
async def titan_stop():
    """Desactive Titan a chaud (ecoute + avatar)."""
    try:
        from assistant.titan_core import stop_titan
        await stop_titan()
        return JSONResponse({"status": "stopped", "message": "Titan arrete"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ── Ollama start/stop ─────────────────────────────────────────────────────────

@router.post("/ollama/start")
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


@router.post("/ollama/stop")
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

@router.post("/gitnexus/start")
async def gitnexus_start():
    """Demarre le serveur GitNexus (npx gitnexus server)."""
    if (await _gitnexus_responding())[0]:
        return JSONResponse({"status": "already_running", "message": "GitNexus deja actif"})

    try:
        import shutil
        npx = shutil.which("npx") or "npx"
        p = subprocess.Popen(
            [npx, "gitnexus", "server"],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _procs["gitnexus"] = p
        # Attendre que le serveur soit pret (max 10s)
        for _ in range(10):
            await asyncio.sleep(1)
            ok, port = await _gitnexus_responding()
            if ok:
                return JSONResponse({
                    "status": "started",
                    "message": f"GitNexus demarre sur port {port} (PID {p.pid})"
                })
        return JSONResponse({"status": "starting", "message": "GitNexus demarre, attendre quelques secondes..."})
    except FileNotFoundError:
        return JSONResponse({
            "status": "error",
            "message": "npx non trouve. Installer Node.js : https://nodejs.org"
        }, status_code=500)
    except Exception as e:
        logger.error("[SVC] gitnexus start: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/gitnexus/stop")
async def gitnexus_stop():
    """Arrete GitNexus (seulement si lance par ce dashboard)."""
    p = _procs.get("gitnexus")
    if p and p.poll() is None:
        p.terminate()
        _procs["gitnexus"] = None
        return JSONResponse({"status": "stopped", "message": "GitNexus arrete"})
    return JSONResponse({"status": "not_managed",
                         "message": "GitNexus non gere par ce dashboard"})


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


@router.post("/github/push")
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
