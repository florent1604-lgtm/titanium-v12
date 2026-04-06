# assistant/install_titan.py -- Script d'installation automatique de Titan.
#
# Lance ce script UNE SEULE FOIS pour :
#   1. Installer les dependances Python
#   2. Telecharger Piper TTS (executable Windows)
#   3. Telecharger le modele voix francais upmc-medium
#   4. Verifier que le modele VRM est present
#   5. Verifier Ollama + modele LLM
#   6. Afficher un resume de ce qui est OK / a faire manuellement
#
# Usage :
#   cd v12
#   python assistant/install_titan.py
from __future__ import annotations
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE      = Path(__file__).resolve().parent.parent
ASST_DIR  = BASE / "assistant"
VOICES_DIR = ASST_DIR / "voices"
PIPER_DIR  = ASST_DIR / "piper"
WEB_DIR    = ASST_DIR / "web"

OK    = "  [OK]"
WARN  = "  [!] "
ERR   = "  [X] "
INFO  = "  [>] "

PYTHON_DEPS = [
    "faster-whisper",
    "sounddevice",
    "webrtcvad-wheels",   # wheels = compatible Windows sans compiler
    "pywebview",
    "numpy",
    "pynput",
    "keyboard",
    # Améliorations IA
    "scikit-learn",       # classificateur d'intention (intent routing)
    "ollama",             # client Python officiel Ollama (plus robuste qu'aiohttp)
]

PIPER_WINDOWS_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
PIPER_EXE         = PIPER_DIR / "piper.exe"

VOICE_MODEL_BASE  = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium"
VOICE_ONNX        = VOICES_DIR / "fr_FR-upmc-medium.onnx"
VOICE_JSON        = VOICES_DIR / "fr_FR-upmc-medium.onnx.json"

VRM_FILE = ASST_DIR / "VRoid_V110_Male_v1.1.3.vrm"

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def download(url: str, dest: Path, label: str) -> bool:
    """Télécharge un fichier avec barre de progression."""
    print(f"{INFO} Téléchargement {label}…")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        def progress(count, block, total):
            pct = min(100, count * block * 100 // max(total, 1))
            print(f"\r      {pct:3d}%", end="", flush=True)

        urllib.request.urlretrieve(url, str(dest), reporthook=progress)
        print()   # newline après la barre
        return True
    except Exception as e:
        print(f"\n{ERR} Échec : {e}")
        return False


def section(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print("-" * 55)


# ── Étapes d'installation ─────────────────────────────────────────────────────

def step_python_deps() -> None:
    section("1. Dépendances Python")
    for dep in PYTHON_DEPS:
        result = run([sys.executable, "-m", "pip", "install", "--quiet", dep])
        if result.returncode == 0:
            print(f"{OK} {dep}")
        else:
            print(f"{ERR} {dep} — lancer manuellement : pip install {dep}")

    # phonemizer optionnel (améliore la qualité du lip-sync)
    print(f"{INFO} Installation phonemizer (optionnel, améliore le lip-sync)…")
    result = run([sys.executable, "-m", "pip", "install", "--quiet", "phonemizer"])
    if result.returncode == 0:
        print(f"{OK} phonemizer")
    else:
        print(f"{WARN} phonemizer non installé — lip-sync fonctionnera avec l'algorithme de fallback")
        print(f"       (pour installer : pip install phonemizer + eSpeak NG)")

    # Vérification classificateur sklearn
    print(f"{INFO} Vérification scikit-learn…")
    try:
        from sklearn.svm import LinearSVC  # noqa
        print(f"{OK} scikit-learn disponible (classificateur d'intention actif)")
    except ImportError:
        print(f"{WARN} scikit-learn non disponible — les requêtes passeront toutes par le LLM")


def step_piper() -> None:
    section("2. Piper TTS (synthèse vocale)")

    if PIPER_EXE.exists():
        print(f"{OK} Piper déjà présent : {PIPER_EXE}")
        return

    if platform.system() != "Windows":
        print(f"{WARN} Ce script installe Piper pour Windows.")
        print(f"       Autres systèmes : https://github.com/rhasspy/piper/releases")
        return

    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = PIPER_DIR / "piper_windows_amd64.zip"

    if download(PIPER_WINDOWS_URL, zip_path, "Piper Windows x64"):
        print(f"{INFO} Extraction de l'archive…")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(PIPER_DIR)
            zip_path.unlink()

            # Piper extrait dans un sous-dossier "piper/" — remonter
            inner = PIPER_DIR / "piper"
            if inner.exists() and (inner / "piper.exe").exists():
                for f in inner.iterdir():
                    shutil.move(str(f), str(PIPER_DIR / f.name))
                inner.rmdir()

            if PIPER_EXE.exists():
                print(f"{OK} Piper installé : {PIPER_EXE}")
            else:
                print(f"{WARN} piper.exe non trouvé après extraction — vérifier le contenu de {PIPER_DIR}")
        except Exception as e:
            print(f"{ERR} Extraction échouée : {e}")
    else:
        print(f"{WARN} Téléchargement manuel requis :")
        print(f"       {PIPER_WINDOWS_URL}")
        print(f"       → Extraire dans {PIPER_DIR}")


def step_voice_model() -> None:
    section("3. Modèle voix français (Piper upmc-medium)")

    VOICES_DIR.mkdir(parents=True, exist_ok=True)

    files = [
        (f"{VOICE_MODEL_BASE}/fr_FR-upmc-medium.onnx", VOICE_ONNX, "fr_FR-upmc-medium.onnx"),
        (f"{VOICE_MODEL_BASE}/fr_FR-upmc-medium.onnx.json", VOICE_JSON, "config JSON"),
    ]
    for url, dest, label in files:
        if dest.exists():
            print(f"{OK} {label} déjà présent")
        else:
            download(url, dest, label)
            if dest.exists():
                print(f"{OK} {label} téléchargé")


def step_vrm() -> None:
    section("4. Modèle VRM")

    if VRM_FILE.exists():
        size_mb = VRM_FILE.stat().st_size / 1024 / 1024
        print(f"{OK} {VRM_FILE.name} ({size_mb:.1f} MB)")
    else:
        # Chercher d'autres VRM
        vrm_files = list(ASST_DIR.glob("*.vrm"))
        if vrm_files:
            found = vrm_files[0]
            print(f"{WARN} VRM trouvé mais nom différent : {found.name}")
            print(f"       Mettre à jour TITAN_AVATAR_FILE dans .env :")
            print(f"       TITAN_AVATAR_FILE={found.name}")
        else:
            print(f"{ERR} Aucun fichier .vrm trouvé dans {ASST_DIR}")
            print(f"       Placer votre VRM dans : {ASST_DIR}")


def step_ollama() -> None:
    section("5. Ollama + modèle LLM")

    ollama = shutil.which("ollama")
    if not ollama:
        print(f"{WARN} Ollama non trouvé dans PATH")
        print(f"       Télécharger : https://ollama.com/download")
        return
    print(f"{OK} Ollama installé : {ollama}")

    # Vérifier si phi3:mini est disponible
    result = run(["ollama", "list"], capture_output=True, text=True)
    models = result.stdout.lower() if result.returncode == 0 else ""

    if "phi3:mini" in models or "phi3" in models:
        print(f"{OK} Modèle phi3:mini disponible")
    else:
        print(f"{WARN} phi3:mini non trouvé — téléchargement en cours…")
        print(f"       (3.8B Q4 ≈ 2.3 GB — patience…)")
        result = run(["ollama", "pull", "phi3:mini"])
        if result.returncode == 0:
            print(f"{OK} phi3:mini installé")
        else:
            print(f"{ERR} Échec — lancer manuellement : ollama pull phi3:mini")
            print(f"       Alternative plus légère : ollama pull qwen2:1.5b")


def step_env() -> None:
    section("6. Variables .env")

    env_file = BASE / ".env"
    additions = """
# ── Titan Assistant ─────────────────────────────────────────────────────────
TITAN_ENABLED=0
TITAN_WAKE_WORDS=titan,hey titan
TITAN_STT_MODEL=small
TITAN_STT_DEVICE=cpu
TITAN_STT_COMPUTE=int8
TITAN_LLM_MODEL=phi3:mini
TITAN_LLM_URL=http://localhost:11434
TITAN_LLM_TIMEOUT=30
TITAN_LLM_MAX_TOKENS=300
TITAN_VOICE_MODEL=fr_FR-upmc-medium.onnx
TITAN_VOICE_DIR=assistant/voices
TITAN_AVATAR_FILE=VRoid_V110_Male_v1.1.3.vrm
TITAN_WINDOW_WIDTH=420
TITAN_WINDOW_HEIGHT=620
TITAN_REPORT_HOUR=20
TITAN_REPORT_MIN=0
TITAN_REPORT_ENABLED=1
TITAN_SILENCE_SEC=1.5
TITAN_MAX_RECORD_SEC=15
TITAN_VAD_AGGR=2
TITAN_SCORE_CONTEXT=1
TITAN_API_BASE=http://localhost:8080
"""
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        if "TITAN_ENABLED" in content:
            print(f"{OK} Variables TITAN déjà dans .env")
        else:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(additions)
            print(f"{OK} Variables TITAN ajoutées au .env")
            print(f"       → Mettre TITAN_ENABLED=1 pour activer")
    else:
        env_file.write_text(additions.strip(), encoding="utf-8")
        print(f"{OK} .env créé avec variables TITAN")


def step_summary() -> None:
    section("Résumé")

    try:
        from sklearn.svm import LinearSVC  # noqa
        sklearn_ok = True
    except ImportError:
        sklearn_ok = False

    try:
        import ollama  # noqa
        ollama_client_ok = True
    except ImportError:
        ollama_client_ok = False

    checks = [
        ("Piper TTS",              PIPER_EXE.exists()),
        ("Voix fr upmc",           VOICE_ONNX.exists()),
        ("Modèle VRM",             any(ASST_DIR.glob("*.vrm"))),
        ("Ollama (serveur)",       bool(shutil.which("ollama"))),
        ("ollama Python client",   ollama_client_ok),
        ("scikit-learn (intent)",  sklearn_ok),
        ("Plugins dir",            (ASST_DIR / "plugins").exists()),
        ("Knowledge dir",          (ASST_DIR / "knowledge").exists()),
        ("Web/index.html",         (WEB_DIR / "index.html").exists()),
    ]
    all_ok = True
    for label, ok in checks:
        status = OK if ok else ERR
        print(f"{status} {label}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  Tout est prêt ! Pour activer Titan :")
        print("  1. Mettre TITAN_ENABLED=1 dans .env")
        print("  2. Redémarrer main.py")
        print("  3. Dire 'Titan' suivi de votre commande")
    else:
        print("  Compléter les éléments marqués [X] puis relancer ce script.")

    print(f"\n  Interface avatar : http://localhost:8080/assistant/")
    print(f"  API speak       : POST http://localhost:8080/titan/speak")
    print(f"  API commande    : POST http://localhost:8080/titan/command")
    print(f"  Status          : GET  http://localhost:8080/titan/status")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  TITAN — Installation de l'assistant Titanium v12")
    print("═" * 55)

    step_python_deps()
    step_piper()
    step_voice_model()
    step_vrm()
    step_ollama()
    step_env()
    step_summary()

    print("\n" + "═" * 55 + "\n")
