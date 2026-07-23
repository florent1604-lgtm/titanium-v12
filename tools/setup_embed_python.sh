#!/usr/bin/env bash
# tools/setup_embed_python.sh — Déploie un Python 3.12 EMBEDDABLE dans le workdir
# (.pyembed/) pour que le sandbox de Codex puisse rejouer pytest LUI-MÊME.
#
# POURQUOI (au-delà du venv non portable) : le sandbox de Codex n'a AUCUN Python
# accessible — pas de launcher `py`, et le venv du projet pointe vers un Python312
# HORS workdir (donc invisible). Un Python embeddable est autonome (aucun launcher,
# aucune install de base) et vit ICI, dans le workdir → accessible au sandbox.
#
# Idempotent : relançable. Usage : bash tools/setup_embed_python.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=".pyembed"
VER="3.12.10"
ZIP="python-${VER}-embed-amd64.zip"

echo "[1/5] Python embeddable ${VER}…"
rm -rf "$DEST" && mkdir -p "$DEST"
curl -sS --max-time 180 -o "$DEST/py.zip" "https://www.python.org/ftp/python/${VER}/${ZIP}"

echo "[2/5] Extraction…"
python - "$DEST/py.zip" "$DEST" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
rm -f "$DEST/py.zip"

echo "[3/5] Activation site-packages + racine du repo dans le ._pth…"
python - "$DEST" <<'PY'
import glob, os
d = os.sys.argv[1]
pth = glob.glob(os.path.join(d, "*._pth"))[0]
lines = open(pth).read().splitlines()
out = []
for ln in lines:
    out.append(ln)
    if ln.strip() == ".":
        out.append("..")                       # racine du repo (relative a .pyembed) → import `core`
out = [("import site" if l.strip() == "#import site" else l) for l in out]
if "Lib\\site-packages" not in out:
    out.append("Lib\\site-packages")
open(pth, "w").write("\n".join(out) + "\n")
print("".join(open(pth).readlines()))
PY

echo "[4/5] pip (get-pip) + dépendances de test…"
curl -sS --max-time 90 -o "$DEST/get-pip.py" https://bootstrap.pypa.io/get-pip.py
"$DEST/python.exe" "$DEST/get-pip.py" --no-warn-script-location -q
rm -f "$DEST/get-pip.py"
"$DEST/python.exe" -m pip install --quiet -r requirements-test.txt

echo "[5/5] Vérification (suite ENTRY_DETECTION) :"
"$DEST/python.exe" -m pytest \
  tests/test_candlestick.py tests/test_closed_bars.py tests/test_volume_profile.py \
  tests/test_fib_ote.py tests/test_sr_levels.py tests/test_binance_kline_feed.py \
  tests/test_confluence_gate.py tests/test_confluence_adapter.py -q

echo
echo "→ Python de test prêt (workdir-local, sandbox-accessible). Pour rejouer :"
echo "   .pyembed/python.exe -m pytest tests/test_confluence_gate.py -q"
