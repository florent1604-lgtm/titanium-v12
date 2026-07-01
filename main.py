"""main.py — Point d'entrée unique Titanium v12.

Usage:
    cd C:\\Users\\flore\\Desktop\\TITANIUM\\Titanium\\v12
    python main.py
"""
from __future__ import annotations
import sys
import os
import subprocess
import re

# Ajouter le répertoire v12 au PYTHONPATH
sys.path.insert(0, os.path.dirname(__file__))


def _kill_zombie_port(port: int) -> None:
    """Libère le port si un processus zombie le bloque (Windows).

    Résout l'erreur [Errno 10048] qui empêche le redémarrage.
    """
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-aon"],
            capture_output=True, timeout=5,
        )
        out = result.stdout.decode("utf-8", "ignore") if result.stdout else ""
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5,
                    )
                    print(f"[STARTUP] Port {port} libéré (PID {pid} terminé)")
    except Exception as e:
        print(f"[STARTUP] Vérification port {port}: {e}")


if __name__ == "__main__":
    from utils.config import UVICORN_PORT
    _kill_zombie_port(UVICORN_PORT)
    from api.api_server import run
    run()
