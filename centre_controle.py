"""centre_controle.py — Centre de Contrôle Titanium v12 (fenêtre bureau pywebview).

Fenêtre unique qui centralise TOUS les outils locaux du bot + leurs URLs, avec :
  · statut live (bot 8090 / terminal MT5 / JARVIS 8765 / Ollama 11434) ;
  · cartes cliquables ouvrant chaque surface dans le navigateur ;
  · actions : lancer/redémarrer le bot, ouvrir MT5, lancer JARVIS.

Lancement : `venv\\Scripts\\pythonw.exe centre_controle.py`
            (ou le raccourci Bureau LANCER_CENTRE_CONTROLE.bat).

Sûr par construction : aucune action ne touche au trading ni au compte réel — le
bouton « Redémarrer » relance simplement `main.py` (qui libère lui-même le port).
"""
from __future__ import annotations

import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"

# ── Catalogue des surfaces locales (titre, url, description, catégorie) ──────────
LIENS = [
    # Titanium (port 8090)
    ("Dashboard",     "http://127.0.0.1:8090/",              "Tableau de bord principal", "TITANIUM"),
    ("Cockpit Orbe",  "http://127.0.0.1:8090/orbe",          "HUD unifié + régime géométrique", "TITANIUM"),
    ("Dashboard v13", "http://127.0.0.1:8090/v13",           "Vue une-page", "TITANIUM"),
    ("Confluence",    "http://127.0.0.1:8090/confluence",    "Méthode manuelle encodée (démo)", "TITANIUM"),
    ("Géométrie",     "http://127.0.0.1:8090/geometry/all",  "Régimes géométriques (26 actifs)", "TITANIUM"),
    ("API Docs",      "http://127.0.0.1:8090/docs",          "Swagger — toutes les routes", "TITANIUM"),
    ("Santé système", "http://127.0.0.1:8090/health/system", "État de l'agent santé", "TITANIUM"),
    # Agents & services
    ("JARVIS mobile", "http://127.0.0.1:8080",               "Interface vocale (serveur mobile)", "AGENTS"),
    ("GitNexus",      "http://127.0.0.1:4747",               "Graphe de code (registre)", "AGENTS"),
    ("Ollama",        "http://127.0.0.1:11434",              "Serveur LLM local", "AGENTS"),
    ("MCP Titanium",  "http://127.0.0.1:8091/mcp",           "Serveur MCP Titanium", "AGENTS"),
    ("MCP Hermes",    "http://127.0.0.1:8766/mcp",           "Cerveau orchestrateur (MCP)", "AGENTS"),
    ("CollabHub",     "http://127.0.0.1:8770/mcp",           "Bus temps réel 3 agents", "AGENTS"),
]

# Sondes de statut : (clé, hôte, port)
SONDES = [("bot", 8090), ("jarvis", 8765), ("ollama", 11434), ("mcp_hermes", 8766)]


def _port_ouvert(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            return s.connect_ex((host, port)) == 0
        except OSError:
            return False


def _process_tourne(nom: str) -> bool:
    try:
        # CREATE_NO_WINDOW : sinon tasklist ouvre une console noire clignotante à
        # chaque sonde (la fenêtre tourne sous pythonw, sans console propre) —
        # statut() est appelé toutes les 5 s par le JS.
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {nom}"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return nom.lower() in (out.stdout or "").lower()
    except Exception:
        return False


def _trouver(exe: str, racines: list[str]) -> str | None:
    for base in racines:
        p = Path(base)
        if not p.exists():
            continue
        try:
            hit = next(p.rglob(exe), None)
        except Exception:
            hit = None
        if hit:
            return str(hit)
    return None


class Api:
    """Actions exposées au JS de la fenêtre. Toutes non bloquantes, fail-safe."""

    def ouvrir(self, url: str) -> None:
        webbrowser.open(url)

    def statut(self) -> dict:
        return {
            "bot": _port_ouvert(8090),
            "mt5": _process_tourne("terminal64.exe"),
            "jarvis": _port_ouvert(8765) or _port_ouvert(8080),
            "ollama": _port_ouvert(11434),
            "hermes": _port_ouvert(8766),
        }

    def lancer_bot(self) -> dict:
        """Lance (ou relance) main.py — il libère lui-même le port 8090 au boot."""
        if not VENV_PY.exists():
            return {"ok": False, "msg": f"python venv introuvable: {VENV_PY}"}
        try:
            subprocess.Popen([str(VENV_PY), "main.py"], cwd=str(ROOT),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            return {"ok": True, "msg": "Bot lancé (fenêtre console dédiée) — boot ~6 s."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "msg": f"échec: {exc!r}"}

    def ouvrir_mt5(self) -> dict:
        chemin = _trouver("terminal64.exe", [
            r"C:\Program Files", r"C:\Program Files (x86)",
            str(Path.home() / "AppData" / "Roaming" / "MetaQuotes"),
        ])
        if not chemin:
            return {"ok": False, "msg": "terminal64.exe introuvable — ouvre MT5 manuellement."}
        try:
            subprocess.Popen([chemin])
            return {"ok": True, "msg": "MT5 lancé — connecte-toi au démo 50061786."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "msg": f"échec: {exc!r}"}

    def lancer_jarvis(self) -> dict:
        bat = _trouver("DEMARRER_JARVIS.bat", [
            r"C:\Program Files\JARVIS", str(Path.home() / "Desktop"), str(ROOT),
        ])
        if not bat:
            return {"ok": False, "msg": "DEMARRER_JARVIS.bat introuvable."}
        try:
            subprocess.Popen(["cmd", "/c", "start", "", bat], cwd=str(Path(bat).parent),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            return {"ok": True, "msg": "JARVIS lancé."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "msg": f"échec: {exc!r}"}


def _html() -> str:
    cartes = {"TITANIUM": [], "AGENTS": []}
    for titre, url, desc, cat in LIENS:
        cartes[cat].append(
            f'<button class="carte" onclick="ouvrir(\'{url}\')">'
            f'<span class="t">{titre}</span><span class="d">{desc}</span>'
            f'<span class="u">{url.replace("http://", "")}</span></button>'
        )
    bloc_titanium = "\n".join(cartes["TITANIUM"])
    bloc_agents = "\n".join(cartes["AGENTS"])
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>
  :root {{ --cy:#00e5ff; --bg:#05080d; --pan:#0b131c; --line:#12303a; --dim:#7fa6b3; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:'Courier New',monospace; background:
         radial-gradient(1200px 600px at 70% -10%, #0a1a24 0%, var(--bg) 60%); color:#dff3f8; }}
  header {{ display:flex; align-items:center; justify-content:space-between;
           padding:16px 22px; border-bottom:1px solid var(--line); }}
  h1 {{ font-size:17px; letter-spacing:3px; margin:0; color:var(--cy); text-transform:uppercase; }}
  h1 small {{ color:var(--dim); letter-spacing:1px; font-size:11px; display:block; margin-top:3px; }}
  .statuts {{ display:flex; gap:14px; }}
  .st {{ font-size:11px; color:var(--dim); display:flex; align-items:center; gap:6px; }}
  .dot {{ width:9px; height:9px; border-radius:50%; background:#33424b; box-shadow:0 0 0 0 transparent; }}
  .dot.on {{ background:var(--cy); box-shadow:0 0 9px var(--cy); }}
  .dot.off {{ background:#c0392b; }}
  main {{ padding:20px 22px 30px; }}
  .actions {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:22px; }}
  .act {{ background:var(--pan); border:1px solid var(--line); color:#dff3f8; padding:12px 18px;
         font-family:inherit; font-size:12px; letter-spacing:1px; cursor:pointer; border-radius:8px;
         transition:.15s; }}
  .act:hover {{ border-color:var(--cy); color:var(--cy); box-shadow:0 0 14px rgba(0,229,255,.15); }}
  .act.primary {{ border-color:var(--cy); color:var(--cy); }}
  h2 {{ font-size:12px; letter-spacing:2px; color:var(--dim); border-bottom:1px solid var(--line);
       padding-bottom:6px; margin:22px 0 14px; text-transform:uppercase; }}
  .grille {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:12px; }}
  .carte {{ text-align:left; background:var(--pan); border:1px solid var(--line); border-radius:10px;
           padding:13px 14px; cursor:pointer; font-family:inherit; color:#dff3f8; transition:.15s;
           display:flex; flex-direction:column; gap:5px; }}
  .carte:hover {{ border-color:var(--cy); transform:translateY(-2px);
                 box-shadow:0 6px 20px rgba(0,229,255,.12); }}
  .carte .t {{ color:var(--cy); font-size:14px; letter-spacing:1px; }}
  .carte .d {{ color:var(--dim); font-size:11px; }}
  .carte .u {{ color:#4c6b76; font-size:10px; }}
  #toast {{ position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
           background:#08131a; border:1px solid var(--cy); color:var(--cy); padding:10px 18px;
           border-radius:8px; font-size:12px; opacity:0; transition:.3s; pointer-events:none; }}
  #toast.show {{ opacity:1; }}
</style></head><body>
<header>
  <h1>Titanium — Centre de Contrôle<small>usage local · paper/démo uniquement</small></h1>
  <div class="statuts">
    <div class="st"><span class="dot" id="d-bot"></span>Bot</div>
    <div class="st"><span class="dot" id="d-mt5"></span>MT5</div>
    <div class="st"><span class="dot" id="d-jarvis"></span>JARVIS</div>
    <div class="st"><span class="dot" id="d-ollama"></span>Ollama</div>
    <div class="st"><span class="dot" id="d-hermes"></span>Hermes</div>
  </div>
</header>
<main>
  <div class="actions">
    <button class="act primary" onclick="act('lancer_bot')">▶ Lancer / Redémarrer le bot</button>
    <button class="act" onclick="act('ouvrir_mt5')">⎘ Ouvrir MT5 (démo)</button>
    <button class="act" onclick="act('lancer_jarvis')">◎ Lancer JARVIS</button>
  </div>
  <h2>Titanium · port 8090</h2>
  <div class="grille">{bloc_titanium}</div>
  <h2>Agents &amp; services</h2>
  <div class="grille">{bloc_agents}</div>
</main>
<div id="toast"></div>
<script>
  // pywebview injecte window.pywebview.api de façon ASYNCHRONE : on n'y accède
  // qu'à l'appel (paresseux) et on n'initialise qu'après l'événement pywebviewready.
  function api() {{ return (window.pywebview && window.pywebview.api) || null; }}
  function ouvrir(u) {{ var a = api(); if (a) {{ a.ouvrir(u); toast('Ouverture ' + u.replace('http://','')); }} }}
  function act(fn) {{
    var a = api(); if (!a) {{ toast('interface pas encore prête…', false); return; }}
    a[fn]().then(function(r) {{ toast(r.msg, r.ok); setTimeout(rafraichir, 1500); }})
           .catch(function(e) {{ toast('erreur: ' + e, false); }});
  }}
  var _t;
  function toast(m, ok) {{
    if (ok === undefined) ok = true;
    var el = document.getElementById('toast'); el.textContent = m;
    el.style.borderColor = ok ? 'var(--cy)' : '#c0392b';
    el.style.color = ok ? 'var(--cy)' : '#e57368';
    el.classList.add('show'); clearTimeout(_t); _t = setTimeout(function() {{ el.classList.remove('show'); }}, 3200);
  }}
  function rafraichir() {{
    var a = api(); if (!a) return;
    a.statut().then(function(s) {{
      var map = [['bot','d-bot'],['mt5','d-mt5'],['jarvis','d-jarvis'],['ollama','d-ollama'],['hermes','d-hermes']];
      for (var i = 0; i < map.length; i++) {{
        var d = document.getElementById(map[i][1]);
        if (d) d.className = 'dot ' + (s[map[i][0]] ? 'on' : 'off');
      }}
    }}).catch(function() {{}});
  }}
  window.addEventListener('pywebviewready', function() {{ rafraichir(); setInterval(rafraichir, 5000); }});
</script></body></html>"""


def main() -> int:
    webview.create_window("Titanium — Centre de Contrôle", html=_html(),
                          js_api=Api(), width=1040, height=720, min_size=(760, 560),
                          background_color="#05080d")
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
