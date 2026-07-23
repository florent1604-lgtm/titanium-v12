"""tools/rebuild_test_venv.py — Reconstruit un venv de TEST local et rejoue la suite
ENTRY_DETECTION. Débloque la vérification indépendante de Codex.

POURQUOI : le venv du projet (`venv/`) n'est PAS portable — son `pyvenv.cfg` pointe en
dur vers `C:\\...\\Python312\\python.exe`, absent du sandbox de Codex. D'où « venv cassé ».
Ce script crée un venv NEUF (`.venv_test/`, chemin relatif au repo) avec l'interpréteur
qui le lance, installe requirements-test.txt, puis lance pytest sur les 8 fichiers.

USAGE (depuis la racine du repo, avec N'IMPORTE quel Python ≥3.10 disponible) :
    py -3.12 tools/rebuild_test_venv.py          # Windows, Python 3.12 préféré
    python tools/rebuild_test_venv.py            # à défaut, le python courant
Puis, pour rejouer ensuite sans réinstaller :
    .venv_test/Scripts/python -m pytest tests/test_confluence_gate.py -q   # (Windows)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv_test"
REQ = ROOT / "requirements-test.txt"

SUITE = [
    "tests/test_candlestick.py", "tests/test_closed_bars.py",
    "tests/test_volume_profile.py", "tests/test_fib_ote.py",
    "tests/test_sr_levels.py", "tests/test_binance_kline_feed.py",
    "tests/test_confluence_gate.py", "tests/test_confluence_adapter.py",
]


def _venv_python() -> Path:
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    return VENV / scripts / exe


def main() -> int:
    print(f"[1/4] Interpréteur de base : {sys.executable} (Python {sys.version.split()[0]})")
    if sys.version_info < (3, 10):
        print("  ! Python ≥ 3.10 requis (pandas 3.x). Relance avec `py -3.12`.")
        return 2

    print(f"[2/4] Création du venv de test : {VENV}")
    subprocess.run([sys.executable, "-m", "venv", "--clear", str(VENV)], check=True)
    vpy = _venv_python()

    print("[3/4] Installation de requirements-test.txt (pip résout les deps transitives)…")
    subprocess.run([str(vpy), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([str(vpy), "-m", "pip", "install", "--quiet", "-r", str(REQ)], check=True)

    print("[4/4] Suite ENTRY_DETECTION :")
    r = subprocess.run([str(vpy), "-m", "pytest", *SUITE, "-q"], cwd=str(ROOT))
    print("\n→ venv de test prêt. Pour rejouer :"
          f"\n  {vpy} -m pytest {' '.join(SUITE)} -q")
    return r.returncode


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
