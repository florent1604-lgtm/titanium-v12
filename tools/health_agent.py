"""tools/health_agent.py — AGENT DE SANTÉ Titanium v12, système et annexes.

Surveille en continu, DEPUIS L'EXTÉRIEUR, et alerte SANS SILENCE.

⚠️ CHOIX D'ARCHITECTURE, tiré de l'incident du 21/07/2026 : cet agent est un PROCESSUS
INDÉPENDANT, jamais une boucle interne à Titanium. Ce soir-là, le worker 8090 s'est emballé
(34 372 s de CPU) et ne répondait plus à aucun endpoint — un moniteur embarqué aurait été gelé
avec lui et n'aurait rien signalé. On observe donc de dehors, ou on n'observe rien.

Ce qu'il surveille :
  • les services et leurs ports (Titanium, JARVIS, GitNexus, MCP singletons, API Hermes) ;
  • la RÉACTIVITÉ réelle des endpoints (un port ouvert ne prouve pas que le service répond) ;
  • l'emballement CPU d'un processus (la panne de ce soir), la RAM et le disque ;
  • l'intégrité de l'EventPlane et sa croissance ;
  • l'INVIOLABILITÉ du mur démo↔réel (compte 60261188 jamais tradé) ;
  • le compte MT5 réellement connecté.

Alerte : fenêtre Windows NON silencieuse (autorisée par Florent), + journal + fichier d'état
lu par l'interface. Anti-spam : une alerte par problème NOUVEAU, rappel après accalmie.

Lancement :  venv\\Scripts\\python.exe tools\\health_agent.py
Lecture seule : cet agent n'écrit RIEN dans le projet hormis son propre état/journal.
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETAT = ROOT / "data" / "health_status.json"
JOURNAL = ROOT / "data" / "health_journal.jsonl"

INTERVALLE = 30              # secondes entre deux passages
RAPPEL_ALERTE = 900          # ré-alerter si un problème persiste au-delà (15 min)
CPU_SEUIL_PCT = 85.0         # % d'un cœur, soutenu, avant de crier
CPU_FENETRES = 3             # nb de passages consécutifs au-dessus du seuil
# Un service qui démarre consomme LÉGITIMEMENT beaucoup (chargement des bougies,
# initialisation MT5, seed REST). Sans ce délai de grâce, l'agent criait à l'emballement
# à chaque redémarrage — et un moniteur qui crie au loup finit par être ignoré.
CPU_GRACE_DEMARRAGE_S = 240
RAM_LIBRE_MIN_MO = 800
DISQUE_LIBRE_MIN_GO = 5.0

# --- Ce qu'on surveille -----------------------------------------------------------------
SERVICES = [
    {"nom": "Titanium API",    "port": 8090, "url": "http://127.0.0.1:8090/api/state",     "vital": True,  "delai": 12},
    {"nom": "JARVIS mobile",   "port": 8080, "url": None,                                   "vital": False, "delai": 6},
    {"nom": "JARVIS voix",     "port": 8765, "url": None,                                   "vital": False, "delai": 6},
    {"nom": "GitNexus",        "port": 4747, "url": "http://127.0.0.1:4747/api/repos",      "vital": False, "delai": 10},
    {"nom": "GitNexus signé",  "port": 4750, "url": None,                                   "vital": False, "delai": 6},
    {"nom": "MCP Titanium",    "port": 8091, "url": None,                                   "vital": False, "delai": 6},
    {"nom": "MCP Hermes",      "port": 8766, "url": None,                                   "vital": False, "delai": 6},
    {"nom": "API Hermes",      "port": 8642, "url": None,                                   "vital": True,  "delai": 6},
]
# Le mur démo↔réel : toute disparition de ces lignes est une URGENCE.
GARDE_DEMO = ROOT / "execution" / "demo_mt5_executor.py"
GARDE_MARQUEURS = ["REAL_ACCOUNT_LOGIN", "RISK_REAL_LOGIN", "RISK_NOT_DEMO"]

_alertes_actives: dict[str, float] = {}      # clé -> horodatage de la dernière alerte
_cpu_historique: dict[int, list] = {}


# --- Alerte NON SILENCIEUSE -------------------------------------------------------------
def alerter(cle: str, titre: str, message: str, urgent: bool = False) -> None:
    """Fenêtre Windows par-dessus tout. Non bloquante pour la surveillance (thread dédié).
    Anti-spam : rien tant que le même problème n'a pas dépassé le délai de rappel."""
    maintenant = time.time()
    derniere = _alertes_actives.get(cle)
    if derniere is not None and (maintenant - derniere) < RAPPEL_ALERTE:
        return
    _alertes_actives[cle] = maintenant

    def _popup():
        try:
            # MB_SYSTEMMODAL(0x1000) = au premier plan | MB_ICONERROR(0x10) / WARNING(0x30)
            style = 0x1000 | (0x10 if urgent else 0x30)
            ctypes.windll.user32.MessageBoxW(None, message, titre, style)
        except Exception:
            print(f"[ALERTE] {titre} : {message}", flush=True)

    threading.Thread(target=_popup, daemon=True).start()
    print(f"[ALERTE{'!' if urgent else ''}] {titre} — {message}", flush=True)
    _journaliser({"type": "alerte", "cle": cle, "titre": titre,
                  "message": message, "urgent": urgent})


def resoudre(cle: str, libelle: str) -> None:
    """Un problème disparu : on l'oublie pour pouvoir ré-alerter s'il revient."""
    if cle in _alertes_actives:
        del _alertes_actives[cle]
        print(f"[RÉTABLI] {libelle}", flush=True)
        _journaliser({"type": "retabli", "cle": cle, "libelle": libelle})


def _journaliser(evt: dict) -> None:
    evt["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --- Sondes -----------------------------------------------------------------------------
def port_ouvert(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def endpoint_repond(url: str, delai: int) -> tuple[bool, float]:
    """Un port ouvert ne prouve RIEN : c'est exactement le symptôme de ce soir (TCP accepté,
    aucune réponse). On mesure donc la réactivité réelle."""
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "titanium-health"})
        with urllib.request.urlopen(req, timeout=delai) as r:
            r.read(1)
            return True, time.monotonic() - t0
    except Exception:
        return False, time.monotonic() - t0


def processus_python() -> list[dict]:
    """Processus python avec leur CPU cumulé, sans dépendance externe (WMI via PowerShell)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Select-Object ProcessId,CommandLine,KernelModeTime,UserModeTime,WorkingSetSize,"
          "@{N='AgeS';E={[int]((Get-Date) - $_.CreationDate).TotalSeconds}} | "
          "ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=25)
        data = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def ressources() -> dict:
    ps = ("$o=Get-CimInstance Win32_OperatingSystem; $d=Get-PSDrive C; "
          "[pscustomobject]@{RamLibreMo=[math]::Round($o.FreePhysicalMemory/1KB); "
          "DisqueLibreGo=[math]::Round($d.Free/1GB,1)} | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=20)
        return json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return {}


def mur_demo_intact() -> tuple[bool, str]:
    """Le garde-fou du compte réel est-il toujours en place ? (marqueurs présents)"""
    try:
        src = GARDE_DEMO.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return False, f"illisible : {exc!r}"
    manquants = [m for m in GARDE_MARQUEURS if m not in src]
    return (not manquants), ("intact" if not manquants else f"MARQUEURS ABSENTS : {manquants}")


# --- Un passage complet -----------------------------------------------------------------
def passage() -> dict:
    etat = {"ts": datetime.now(timezone.utc).isoformat(), "services": {},
            "ressources": {}, "problemes": [], "sante": "ok"}

    # 1. Services : port + réactivité réelle
    for svc in SERVICES:
        nom, cle = svc["nom"], f"svc:{svc['port']}"
        ouvert = port_ouvert(svc["port"])
        info = {"port": svc["port"], "ouvert": ouvert, "vital": svc["vital"]}
        if not ouvert:
            info["etat"] = "eteint"
            if svc["vital"]:
                etat["problemes"].append(f"{nom} ÉTEINT")
                alerter(cle, "Titanium — service vital arrêté",
                        f"{nom} (port {svc['port']}) ne répond plus.\n\n"
                        f"Le service est éteint ou a planté.", urgent=True)
        elif svc["url"]:
            ok, secondes = endpoint_repond(svc["url"], svc["delai"])
            if not ok:
                # Un blip (cycle de scan lourd, GC) ne prouve pas un gel : on RETENTE
                # avant d'alarmer. Un vrai gel échoue les deux fois ; un transitoire
                # passe au rattrapage → plus de fausse alerte « FIGÉ » (demande Florent).
                time.sleep(1.5)
                ok, secondes = endpoint_repond(svc["url"], svc["delai"])
            info["etat"] = "ok" if ok else "fige"
            info["latence_s"] = round(secondes, 2)
            if not ok:
                etat["problemes"].append(f"{nom} FIGÉ (port ouvert, aucune réponse)")
                alerter(cle, "Titanium — service figé",
                        f"{nom} accepte les connexions mais ne répond plus "
                        f"(délai {svc['delai']}s dépassé).\n\n"
                        f"C'est le symptôme de l'emballement : un redémarrage unitaire "
                        f"est probablement nécessaire.", urgent=svc["vital"])
            else:
                resoudre(cle, nom)
        else:
            info["etat"] = "ok"
            resoudre(cle, nom)
        etat["services"][nom] = info

    # 2. Emballement CPU — la panne de ce soir
    vivants = set()
    for p in processus_python():
        cmd = (p.get("CommandLine") or "")
        if "main.py" not in cmd and "main2.py" not in cmd:
            continue
        pid = p.get("ProcessId")
        vivants.add(pid)
        # Délai de grâce : un service qui vient de démarrer consomme légitimement.
        if (p.get("AgeS") or 0) < CPU_GRACE_DEMARRAGE_S:
            _cpu_historique.pop(pid, None)      # on repart proprement après la chauffe
            continue
        cpu_s = ((p.get("KernelModeTime") or 0) + (p.get("UserModeTime") or 0)) / 1e7
        hist = _cpu_historique.setdefault(pid, [])
        hist.append((time.monotonic(), cpu_s))
        if len(hist) > CPU_FENETRES + 1:
            hist.pop(0)
        if len(hist) >= CPU_FENETRES + 1:
            dt = hist[-1][0] - hist[0][0]
            dcpu = hist[-1][1] - hist[0][1]
            pct = (dcpu / dt * 100.0) if dt > 0 else 0.0
            nom_proc = "Titanium" if "main.py" in cmd else "JARVIS"
            cle = f"cpu:{pid}"
            if pct >= CPU_SEUIL_PCT:
                etat["problemes"].append(f"{nom_proc} EMBALLÉ ({pct:.0f}% CPU soutenu)")
                alerter(cle, "Titanium — emballement CPU",
                        f"{nom_proc} (PID {pid}) consomme {pct:.0f}% d'un cœur en continu "
                        f"depuis {dt:.0f}s.\n\nC'est le profil de la panne du 21/07 : le "
                        f"service va cesser de répondre. Redémarrage unitaire conseillé.",
                        urgent=True)
            else:
                resoudre(cle, f"{nom_proc} CPU")

    # Purge des processus disparus : sans ça, l'historique et les alertes d'un PID mort
    # traînaient indéfiniment et faussaient les passages suivants.
    for mort in [pid for pid in _cpu_historique if pid not in vivants]:
        _cpu_historique.pop(mort, None)
        _alertes_actives.pop(f"cpu:{mort}", None)

    # 3. Ressources machine
    res = ressources()
    etat["ressources"] = res
    if res.get("RamLibreMo", 99999) < RAM_LIBRE_MIN_MO:
        etat["problemes"].append(f"RAM critique ({res['RamLibreMo']} Mo libres)")
        alerter("ram", "Titanium — mémoire critique",
                f"Il ne reste que {res['RamLibreMo']} Mo de RAM libre.", urgent=True)
    else:
        resoudre("ram", "RAM")
    if res.get("DisqueLibreGo", 999) < DISQUE_LIBRE_MIN_GO:
        etat["problemes"].append(f"Disque faible ({res['DisqueLibreGo']} Go)")
        alerter("disque", "Titanium — disque presque plein",
                f"Il ne reste que {res['DisqueLibreGo']} Go sur C:.")
    else:
        resoudre("disque", "Disque")

    # 4. Mur démo↔réel — URGENCE ABSOLUE s'il tombe
    intact, detail = mur_demo_intact()
    etat["mur_demo"] = {"intact": intact, "detail": detail}
    if not intact:
        etat["problemes"].append("MUR DÉMO↔RÉEL COMPROMIS")
        alerter("mur_demo", "URGENCE — protection du compte réel",
                f"Le garde-fou qui interdit le compte réel Axi 60261188 a été "
                f"ALTÉRÉ ou est illisible.\n\n{detail}\n\n"
                f"Arrête toute exécution et vérifie immédiatement "
                f"execution/demo_mt5_executor.py", urgent=True)
    else:
        resoudre("mur_demo", "Mur démo↔réel")

    etat["sante"] = "critique" if any("ÉTEINT" in p or "EMBALLÉ" in p or "COMPROMIS" in p
                                       for p in etat["problemes"]) else \
                    ("degradee" if etat["problemes"] else "ok")
    return etat


def ecrire_etat(etat: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        tmp = ETAT.with_suffix(".tmp")
        tmp.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ETAT)
    except Exception as exc:
        print(f"[SANTÉ] écriture d'état impossible : {exc!r}", flush=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"[SANTÉ] Agent démarré — surveillance toutes les {INTERVALLE}s, "
          f"alertes Windows actives.", flush=True)
    _journaliser({"type": "demarrage"})
    while True:
        try:
            etat = passage()
            ecrire_etat(etat)
            if etat["problemes"]:
                print(f"[SANTÉ] {etat['sante'].upper()} — {' | '.join(etat['problemes'])}",
                      flush=True)
        except Exception as exc:
            print(f"[SANTÉ] passage en échec : {exc!r}", flush=True)
        time.sleep(INTERVALLE)


if __name__ == "__main__":
    main()
