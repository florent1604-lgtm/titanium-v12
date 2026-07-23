"""tools/gitnexus_keygen.py — Génère une paire de clés d'approbation (Ed25519).

À LANCER PAR FLORENT (ou un superviseur), pas par un agent : la clé PRIVÉE ne
doit jamais transiter par un agent ni par le dépôt.

Ce que fait l'outil :
  - génère une paire Ed25519 ;
  - CHIFFRE la clé privée avec TA passphrase (elle est inutilisable sans elle),
    et la range HORS du dépôt (~/.titanium_gitnexus_keys par défaut) ;
  - installe UNIQUEMENT la clé PUBLIQUE dans le registre versionné
    collab/governance/gitnexus_approver_keys.json.

Ainsi Hermes peut lire la clé publique mais ne peut ni forger de signature ni
utiliser ta clé privée (chiffrée, hors dépôt).

Usage :
  venv\\Scripts\\python.exe tools\\gitnexus_keygen.py --actor florent
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = ROOT / "collab" / "governance" / "gitnexus_approver_keys.json"
DEFAULT_KEYDIR = Path.home() / ".titanium_gitnexus_keys"   # HORS dépôt


def _one_prompt(label: str) -> str:
    """getpass (masqué) ; si le terminal ne capte rien → saisie VISIBLE de secours."""
    try:
        val = getpass.getpass(label)
    except Exception:
        val = ""
    if val == "":
        val = input(label + "[visible] ")
    return val


def _read_passphrase() -> str:
    """1) variable TITANIUM_KEY_PASSPHRASE si définie (méthode fiable), sinon
    2) invite masquée avec repli visible, en boucle jusqu'à validité."""
    env = os.environ.get("TITANIUM_KEY_PASSPHRASE")
    if env is not None:
        if len(env) < 8:
            raise SystemExit("TITANIUM_KEY_PASSPHRASE trop courte (min. 8 caractères).")
        print("Passphrase lue depuis la variable TITANIUM_KEY_PASSPHRASE.")
        return env
    for _ in range(5):
        pw = _one_prompt("Passphrase pour CHIFFRER la clé privée (min 8) : ")
        if len(pw) < 8:
            print("→ Trop courte (min 8 caractères). Réessayez.")
            continue
        if pw != _one_prompt("Confirmez la passphrase : "):
            print("→ Les deux saisies diffèrent. Réessayez.")
            continue
        return pw
    raise SystemExit("Saisie impossible. Utilisez la variable TITANIUM_KEY_PASSPHRASE (voir aide).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Génère une clé d'approbation GitNexus (Ed25519).")
    ap.add_argument("--actor", default="florent", choices=["florent", "claude", "codex"])
    ap.add_argument("--key-id", default=None,
                    help="nom MÉMORABLE de la clé (ex. florent-perso). Auto-généré sinon. "
                         "N.B. : c'est l'IDENTIFIANT (le nom), pas la valeur de la clé.")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--keydir", default=str(DEFAULT_KEYDIR))
    args = ap.parse_args()

    print(f"Génération d'une clé pour l'acteur : {args.actor}")
    pw = _read_passphrase()

    sk = Ed25519PrivateKey.generate()
    pub_raw = sk.public_key().public_bytes_raw()
    pub_b64 = base64.b64encode(pub_raw).decode()
    if args.key_id:
        import re
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", args.key_id):
            raise SystemExit("--key-id invalide (3 à 64 caractères : lettres, chiffres, . _ -).")
        key_id = args.key_id
    else:
        key_id = f"{args.actor}-{hashlib.sha256(pub_raw).hexdigest()[:12]}"

    keydir = Path(args.keydir)
    keydir.mkdir(parents=True, exist_ok=True)
    priv_path = keydir / f"{key_id}.private.pem"
    if priv_path.exists():
        raise SystemExit(f"Existe déjà : {priv_path} (ne pas écraser).")
    priv_pem = sk.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(pw.encode("utf-8")),
    )
    priv_path.write_bytes(priv_pem)
    (keydir / f"{key_id}.meta.json").write_text(
        json.dumps({"key_id": key_id, "actor": args.actor, "public_key_b64": pub_b64},
                   indent=2), encoding="utf-8")

    reg_path = Path(args.registry)
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        if not isinstance(reg, dict) or reg.get("version") != 1 or not isinstance(reg.get("keys"), list):
            raise SystemExit("Registre existant invalide — vérifier manuellement.")
    else:
        reg = {"version": 1, "keys": []}
    if any(r.get("key_id") == key_id for r in reg["keys"]):
        raise SystemExit(f"key_id déjà présent dans le registre : {key_id} (choisis-en un autre).")
    if any(r.get("actor") == args.actor and r.get("enabled") for r in reg["keys"]):
        print(f"⚠ Une clé ACTIVE existe déjà pour {args.actor} ; la nouvelle s'ajoute "
              "(désactive l'ancienne dans le registre si tu la remplaces).")
    reg["keys"].append({"key_id": key_id, "actor": args.actor, "algorithm": "Ed25519",
                        "public_key_b64": pub_b64, "enabled": True})
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n✅ Clé PUBLIQUE installée dans le registre :")
    print(f"   key_id : {key_id}")
    print(f"   registre : {reg_path}")
    print(f"🔒 Clé PRIVÉE chiffrée (HORS dépôt, à conserver précieusement, ne jamais partager) :")
    print(f"   {priv_path}")
    print("   → inutilisable sans ta passphrase ; le dépôt ne contient QUE la clé publique.")


if __name__ == "__main__":
    main()
