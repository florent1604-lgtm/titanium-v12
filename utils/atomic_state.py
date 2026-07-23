"""utils/atomic_state.py — Écriture d'état JSON atomique + écrivain sérialisé.

R2 (revue Codex 10/07/2026) :
  - `temp + os.replace` : aucun lecteur ne voit jamais un fichier partiel ou
    corrompu (os.replace est atomique sur le même système de fichiers) ;
  - un verrou par chemin sérialise les écrivains DANS le process (les boucles
    async forex/swing/paper ne se marchent pas dessus) ;
  - le *lost update* entre PROCESS distincts est évité en amont en n'exécutant
    qu'une seule instance du bot (single_instance_guard ci-dessous).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_locks: dict[str, threading.RLock] = {}
_registry_lock = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _registry_lock:
        lk = _locks.get(key)
        if lk is None:
            lk = _locks[key] = threading.RLock()
        return lk


def save_json_atomic(path: os.PathLike | str, data: Any, *, indent: int = 1) -> None:
    """Écrit `data` en JSON de façon atomique et sérialisée par chemin."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=indent)
    with _lock_for(p):
        fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            # os.replace est atomique, MAIS sur Windows il échoue (WinError 5) si
            # la cible est momentanément ouverte par un lecteur → retry court.
            for attempt in range(40):
                try:
                    os.replace(tmp, p)
                    break
                except PermissionError:
                    if attempt == 39:
                        raise
                    time.sleep(0.01)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
