# Titanium v12 × Antigravity — MCP Setup

## 1. Trouver le bon chemin mcp_config.json sous Windows

Antigravity stocke sa config MCP dans le globalStorage de l'extension principale.
Le chemin exact est :

```
%APPDATA%\Antigravity\User\globalStorage\antigravity.antigravity\mcp_config.json
```

En PowerShell :
```powershell
$path = "$env:APPDATA\Antigravity\User\globalStorage\antigravity.antigravity"
New-Item -ItemType Directory -Path $path -Force
```

## 2. Copier le fichier de config

```powershell
Copy-Item "C:\Users\flore\Desktop\v12\antigravity_config\mcp_config.json" `
  "$env:APPDATA\Antigravity\User\globalStorage\antigravity.antigravity\mcp_config.json"
```

## 3. Recharger les serveurs MCP sans redémarrer Antigravity

Ouvre la palette de commandes (`Ctrl+Shift+P`) et tape :
```
Developer: Reload Window
```

Ou redémarre Antigravity entièrement.

## 4. Vérifier que Cascade voit les ressources Titanium

1. Ouvre le panneau **Cascade** dans Antigravity
2. Clique sur l'icône **Context** (ou `@`)
3. Tu devrais voir `titanium-v12` listé comme source MCP
4. Les ressources disponibles :
   - `titanium://signals/latest` — Signaux SMC en temps réel
   - `titanium://positions/open` — Positions paper ouvertes
   - `titanium://market/context` — Funding, OI, delta volume
   - `titanium://dashboard/status` — État général du bot

## 5. Prérequis

- **Titanium v12 doit tourner** sur `http://localhost:8090`
- Le venv Python est à `C:\Users\flore\Desktop\v12\venv\Scripts\python.exe`
- Si Titanium est arrêté, les ressources retournent `{"status": "offline", ...}`

## 6. Test manuel du serveur MCP

```powershell
cd C:\Users\flore\Desktop\v12
venv\Scripts\python.exe mcp_server.py --test
```

Sortie attendue quand Titanium tourne :
```
[Resource] titanium://signals/latest
{"BTC/USDT": {"score": 7, "side": "ACHAT", ...}, ...}

[Resource] titanium://dashboard/status
{"version": "v12", "active_signals": 1, "equity": 1024.50, ...}
```

## 7. Utilisation avec Cascade

Une fois connecté, tu peux demander à Cascade :
- *"Quels sont les signaux actifs sur Titanium ?"*
- *"Analyse le code signal_engine.py en tenant compte du contexte live"*
- *"Mon drawdown est à -12%, qu'est-ce qui pourrait causer ça dans le code ?"*
