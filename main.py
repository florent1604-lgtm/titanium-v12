"""main.py — Point d'entrée unique Titanium v12.

Usage:
    cd C:\\Users\\flore\\Desktop\\TITANIUM\\Titanium\\v12
    python main.py
"""
from __future__ import annotations
import sys
import os
import socket
import subprocess
import time

# Ajouter le répertoire v12 au PYTHONPATH
sys.path.insert(0, os.path.dirname(__file__))


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _kill_zombie_port(port: int) -> None:
    """Libère le port si un processus zombie le bloque (Windows).

    Résout l'erreur [Errno 10048] qui empêche le redémarrage.
    Ne matche que la colonne adresse LOCALE (une connexion sortante
    VERS ce port ne doit pas déclencher de kill), puis vérifie
    réellement que le port est libéré avant de continuer.
    """
    if _port_is_free(port):
        return
    if sys.platform != "win32":
        print(f"[STARTUP] ATTENTION : port {port} occupé — libérez-le manuellement")
        return
    try:
        result = subprocess.run(
            ["netstat", "-aon", "-p", "TCP"],
            capture_output=True, timeout=5,
        )
        out = result.stdout.decode("utf-8", "ignore") if result.stdout else ""
        for line in out.splitlines():
            parts = line.split()
            # Format: Proto | Adresse locale | Adresse distante | État | PID
            if len(parts) < 5 or not parts[1].endswith(f":{port}"):
                continue
            if "LISTEN" not in parts[3].upper():
                continue
            pid = parts[-1]
            if pid.isdigit() and int(pid) != os.getpid():
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True, timeout=5,
                )
                print(f"[STARTUP] Port {port} : instance zombie PID {pid} terminée")
    except Exception as e:
        print(f"[STARTUP] Vérification port {port}: {e}")

    # Vérifier que le port est réellement libre (le kill peut prendre ~1s)
    for _ in range(10):
        if _port_is_free(port):
            print(f"[STARTUP] Port {port} libre — démarrage")
            return
        time.sleep(0.5)
    print(f"[STARTUP] ERREUR : port {port} toujours occupé après tentative de "
          f"libération. Fermez l'application qui l'utilise ou changez UVICORN_PORT.")
    sys.exit(1)


if __name__ == "__main__":
    from utils.config import UVICORN_PORT
    _kill_zombie_port(UVICORN_PORT)
    from api.api_server import run
    run()
