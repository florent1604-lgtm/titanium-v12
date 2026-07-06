"""gemini_architect.py — Relais vers Gemini pour second avis technique.

Usage:
    python gemini_architect.py "Ton message, une demande de revue, un plan à valider"

Prérequis:
    pip install google-generativeai
    set GEMINI_API_KEY=ta_cle          (Windows cmd)
    $env:GEMINI_API_KEY="ta_cle"       (PowerShell)

Le modèle est configurable via GEMINI_MODEL (défaut: gemini-1.5-pro).
"""
import os
import sys
from pathlib import Path

try:
    import google.generativeai as genai
except ImportError:
    print("Erreur : bibliothèque manquante. Installer avec : pip install google-generativeai")
    sys.exit(1)


def _load_dotenv_key(name: str) -> str | None:
    """Lit une variable depuis le .env du projet si absente de l'environnement."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


api_key = os.environ.get("GEMINI_API_KEY") or _load_dotenv_key("GEMINI_API_KEY")
if not api_key:
    print("Erreur : GEMINI_API_KEY introuvable.")
    print("Option 1 : ajouter la ligne  GEMINI_API_KEY=ta_cle  dans le fichier .env du projet")
    print('Option 2 : PowerShell :  setx GEMINI_API_KEY "ta_cle"  (puis rouvrir le terminal)')
    sys.exit(1)

genai.configure(api_key=api_key)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")
model = genai.GenerativeModel(MODEL_NAME)

SYSTEM_INSTRUCTION = (
    "Tu es un architecte logiciel senior consulté pour un second avis sur le projet "
    "Titanium (bot de trading algorithmique Python/FastAPI, paper trading, analyse "
    "spectrale des cycles). Analyse la situation présentée, valide ou corrige la "
    "démarche, signale les risques (lookahead, coûts de transaction, sur-optimisation) "
    "et donne des recommandations techniques précises et actionnables."
)


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python gemini_architect.py "Ton message ou point de situation"')
        sys.exit(1)

    user_input = " ".join(sys.argv[1:])

    try:
        response = model.generate_content(
            f"{SYSTEM_INSTRUCTION}\n\nSituation / question :\n{user_input}"
        )
        print("\n=== RETOUR DE L'ARCHITECTE (GEMINI) ===")
        print(response.text)
        print("=======================================\n")
    except Exception as e:
        print(f"Erreur lors de la communication avec Gemini : {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
