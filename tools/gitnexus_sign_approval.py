"""tools/gitnexus_sign_approval.py — Signe une demande d'écriture GitNexus en attente.

À LANCER PAR FLORENT (ou un superviseur) pour APPROUVER une écriture proposée
par Hermes. Lit la demande sur le bus, construit l'approbation, la SIGNE avec ta
clé privée (déchiffrée par ta passphrase) et l'ajoute au canal d'acks.

Usage :
  venv\\Scripts\\python.exe tools\\gitnexus_sign_approval.py --request-id <ID> --key <chemin .private.pem>
Vérifie la CARTE affichée (outil, cible, fichiers, risque) AVANT de confirmer.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def _read_passphrase(prompt: str) -> str:
    """Lit la passphrase. Priorité à TITANIUM_KEY_PASSPHRASE (fiable dans TOUT
    terminal, notamment le terminal intégré VS Code où getpass n'accepte pas la
    saisie). Sinon getpass (masqué), puis repli input() visible. Ne fragilise pas
    la crypto : la clé reste chiffrée, la passphrase n'est jamais écrite sur disque."""
    env = os.environ.get("TITANIUM_KEY_PASSPHRASE")
    if env:
        print("  (passphrase lue depuis TITANIUM_KEY_PASSPHRASE)")
        return env
    try:
        pw = getpass.getpass(prompt)
    except Exception:
        pw = ""
    if pw:
        return pw
    print("  (saisie masquée indisponible dans ce terminal — la frappe sera VISIBLE)")
    return input(prompt)

from cryptography.hazmat.primitives import serialization

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.gitnexus_write_policy import canonical_approval_payload  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STREAM = ROOT / "collab" / "messages" / "stream.ndjson"
ACKS = ROOT / "collab" / "messages" / "acks.ndjson"


def _load_request(request_id: str) -> dict:
    for line in STREAM.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("type") == "gitnexus_write_request" and row.get("id") == request_id:
            return row
    raise SystemExit(f"Demande introuvable : {request_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Signe une approbation d'écriture GitNexus.")
    ap.add_argument("--request-id", required=True)
    ap.add_argument("--key", required=True, help="chemin de ta clé privée .private.pem")
    args = ap.parse_args()

    priv_path = Path(args.key)
    meta_path = priv_path.with_name(priv_path.name.replace(".private.pem", ".meta.json"))
    if not priv_path.is_file() or not meta_path.is_file():
        raise SystemExit("Clé privée ou méta introuvable (fichiers .private.pem + .meta.json).")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    actor, key_id = meta["actor"], meta["key_id"]

    req = _load_request(args.request_id)
    print("\n── CARTE DE DEMANDE (à vérifier) ─────────────────────────────")
    print(f"  outil     : {req.get('tool')}")
    print(f"  args      : {json.dumps(req.get('args'), ensure_ascii=False)}")
    print(f"  fichiers  : {req.get('files')}")
    print(f"  risque    : {req.get('impact_risk')}")
    print(f"  expire à  : {req.get('expires_ts')}")
    print("──────────────────────────────────────────────────────────────")
    if input(f"Approuver cette écriture en tant que '{actor}' ? (oui/non) : ").strip().lower() not in ("oui", "o", "yes", "y"):
        raise SystemExit("Annulé.")

    pw = _read_passphrase("Passphrase de ta clé privée : ")
    try:
        sk = serialization.load_pem_private_key(priv_path.read_bytes(), password=pw.encode("utf-8"))
    except Exception:
        raise SystemExit("Passphrase incorrecte ou clé illisible.")

    approval = {
        "id": f"ap-{actor}-{secrets.token_hex(4)}",
        "type": "gitnexus_write_approval", "verdict": "APPROVED",
        "from": actor, "to": "hermes", "in_reply_to": req["id"],
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "tool": req["tool"], "args_sha256": req["args_sha256"],
        "file_fingerprint": req["file_fingerprint"],
        "request_expires_ts": req["expires_ts"],
        "nonce": secrets.token_hex(16),
        "florent_override": actor == "florent",
    }
    signature = sk.sign(canonical_approval_payload(approval))
    approval["signature"] = {"algorithm": "Ed25519", "key_id": key_id,
                             "value_b64": base64.b64encode(signature).decode()}

    ACKS.parent.mkdir(parents=True, exist_ok=True)
    with ACKS.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(approval, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"\n✅ Approbation SIGNÉE ajoutée pour la demande {req['id']} (acteur {actor}).")
    print("   Valable 15 min, à usage unique. Un superviseur (claude/codex) doit aussi signer.")


if __name__ == "__main__":
    main()
