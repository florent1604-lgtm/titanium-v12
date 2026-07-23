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


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """Return True only when the exact Uvicorn bind would succeed.

    ``SO_REUSEADDR`` must not be enabled for this preflight on Windows: it can
    report an already-listening port as available, then Uvicorn fails later
    with WinError 10048 after the application lifespan has already started.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _kill_zombie_port(port: int, host: str = "127.0.0.1") -> None:
    """Libère le port si un processus zombie le bloque (Windows).

    Résout l'erreur [Errno 10048] qui empêche le redémarrage.
    Ne matche que la colonne adresse LOCALE (une connexion sortante
    VERS ce port ne doit pas déclencher de kill), puis vérifie
    réellement que le port est libéré avant de continuer.
    """
    if _port_is_free(port, host):
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
                killed = subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", pid],
                    capture_output=True, timeout=5,
                )
                if killed.returncode == 0:
                    print(f"[STARTUP] Port {port} : instance précédente PID {pid} terminée")
                else:
                    detail = killed.stderr.decode("utf-8", "ignore").strip()
                    print(f"[STARTUP] Échec arrêt PID {pid}: {detail or 'taskkill refusé'}")
    except Exception as e:
        print(f"[STARTUP] Vérification port {port}: {e}")

    # Vérifier que le port est réellement libre (le kill peut prendre ~1s)
    for _ in range(10):
        if _port_is_free(port, host):
            print(f"[STARTUP] Port {port} libre — démarrage")
            return
        time.sleep(0.5)
    print(f"[STARTUP] ERREUR : port {port} toujours occupé après tentative de "
          f"libération. Fermez l'application qui l'utilise ou changez UVICORN_PORT.")
    sys.exit(1)


if __name__ == "__main__":
    from utils.config import UVICORN_HOST, UVICORN_PORT
    # R2 : la protection « un seul écrivain » repose sur le contrôle de port
    # ci-dessous (deux serveurs ne peuvent pas binder 8090) + les écritures
    # atomiques de utils.atomic_state. (Un verrou PID dédié s'est révélé fragile
    # face aux force-kills et redondant avec le contrôle de port — écarté.)
    _kill_zombie_port(UVICORN_PORT, UVICORN_HOST)
    from api.api_server import run
    run()
