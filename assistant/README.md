# Titan — Assistant vocal IA pour Titanium v12

## Installation rapide

```bash
# Depuis le dossier v12/
python assistant/install_titan.py
```

Le script installe automatiquement tout ce qui est téléchargeable et guide pour le reste.

## Installation manuelle (si le script échoue)

### 1. Dépendances Python
```bash
pip install faster-whisper sounddevice webrtcvad-wheels pywebview numpy
pip install phonemizer   # optionnel — améliore le lip-sync
```

### 2. Piper TTS (Windows)
- Télécharger : https://github.com/rhasspy/piper/releases
- Extraire `piper_windows_amd64.zip` → `assistant/piper/piper.exe`

### 3. Modèle voix français
```bash
# Créer le dossier
mkdir assistant/voices

# Télécharger le modèle upmc-medium (≈ 63 MB)
curl -L https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx -o assistant/voices/fr_FR-upmc-medium.onnx
curl -L https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json -o assistant/voices/fr_FR-upmc-medium.onnx.json
```

Autres voix disponibles sur https://huggingface.co/rhasspy/piper-voices (dossier `fr/`)

### 4. Ollama + modèle LLM
```bash
# Installer Ollama : https://ollama.com/download

# Modèle recommandé (3.8B, ≈ 2.3 GB)
ollama pull phi3:mini

# Alternative ultra-légère (1.5B, ≈ 950 MB)
ollama pull qwen2:1.5b
```

### 5. Activation
Dans `.env` :
```
TITAN_ENABLED=1
TITAN_LLM_MODEL=phi3:mini   # ou qwen2:1.5b
```

Redémarrer `main.py`.

---

## Utilisation

### Wake word
Dire **"Titan"** puis votre commande. Exemples :
- *"Titan, quel est le signal BTC ?"*
- *"Titan, fais le rapport du jour"*
- *"Titan, combien j'ai gagné aujourd'hui ?"*
- *"Titan, quel est le risque macro ?"*
- *"Titan, ferme la position ETH"*

### API REST
```bash
# Faire parler Titan directement
curl -X POST http://localhost:8080/titan/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Bonjour, le signal BTC est actif.", "expression": "neutral"}'

# Envoyer une commande textuelle
curl -X POST http://localhost:8080/titan/command \
  -H "Content-Type: application/json" \
  -d '{"command": "quel est le winrate actuel ?", "speak": true}'

# État de l'assistant
curl http://localhost:8080/titan/status

# Effacer l'historique
curl -X POST http://localhost:8080/titan/clear-history
```

### Interface avatar
Ouvrir : http://localhost:8080/assistant/

---

## Architecture des fichiers

```
assistant/
├── config.py           Variables de configuration (.env)
├── voice_engine.py     Wake word + STT (Whisper)
├── titan_agent.py      Agent LLM (Ollama + contexte trading)
├── tts_engine.py       Synthèse vocale (Piper TTS)
├── lip_sync.py         Phonèmes → visèmes VRM (52 blendshapes)
├── avatar_renderer.py  Fenêtre PyWebView + WebSocket bridge
├── popup_manager.py    Orchestrateur parole → animation
├── titan_core.py       Point d'entrée principal
├── daily_report.py     Rapport quotidien automatique (20h)
├── alexa_connector.py  Stub webhook Alexa Skills Kit
├── install_titan.py    Script d'installation
├── voices/             Modèles Piper TTS (.onnx)
├── piper/              Exécutable Piper TTS
├── web/
│   ├── index.html      Page popup (Three.js + three-vrm)
│   ├── avatar.js       Renderer VRM + animation loop
│   └── style.css       Interface sombre
└── VRoid_V110_Male_v1.1.3.vrm   Modèle 3D
```

## Flux de données

```
[Microphone] → VAD (webrtcvad) → buffer 2s
     ↓ wake word détecté
[Whisper small INT8] → texte commande
     ↓
[titan_agent.py] → Ollama phi3:mini + contexte trading temps réel
     ↓
[tts_engine.py] → Piper TTS → audio PCM 22kHz
     ↓
[lip_sync.py] → phonèmes + RMS → frames blendshapes 30fps
     ↓
[popup_manager.py] → ouvrir fenêtre + lire audio en parallèle
     ↓
[avatar_renderer.py] → WS /titan/ws → [avatar.js] → three-vrm
```

## Consommation CPU estimée

| Composant | CPU (idle) | CPU (actif) |
|-----------|-----------|-------------|
| Whisper tiny | 0% | ~15% |
| Whisper small | 0% | ~35% |
| Piper TTS | 0% | ~5% |
| Three.js VRM | ~3% | ~3% |
| Ollama phi3:mini | 0% | ~60-80% (10-30s) |
| **Total (speak)** | ~3% | **~80%** (bref) |

Le pic CPU est court (durée de la génération LLM = 5-30 secondes selon la requête).

## Personnalisation du prompt système

Modifier `TITAN_SYSTEM_PROMPT` dans `assistant/config.py` pour changer la personnalité de Titan.

## Intégration Alexa (future)

1. Créer un Skill dans la console Amazon Developer
2. Pointer l'endpoint vers `https://votre-domaine.com/alexa/webhook`
3. Les intents sont pré-définis dans `alexa_connector.py`
4. Ajouter la vérification de signature Amazon en production

## Dépannage

| Problème | Solution |
|----------|----------|
| Wake word non détecté | Réduire `TITAN_VAD_AGGR` à 1 ou 0 dans .env |
| TTS silencieux | Vérifier `assistant/piper/piper.exe` et `assistant/voices/*.onnx` |
| Avatar ne charge pas | Ouvrir http://localhost:8080/assistant/ et vérifier la console navigateur |
| LLM trop lent | Passer à `qwen2:1.5b` ou réduire `TITAN_LLM_MAX_TOKENS` |
| phonemizer erreur | Normal — lip-sync bascule sur l'algorithme graphème (qualité légèrement inférieure) |
