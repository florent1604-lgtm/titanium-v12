"""tools/gitnexus_sign_gui.py — Fenêtre de signature GitNexus (indépendante, Tkinter).

Pour APPROUVER une écriture GitNexus sans galérer avec getpass dans un terminal.
Ouvre une vraie fenêtre Windows : carte de la demande la plus récente + deux
champs mot de passe MASQUÉS (fiables) pour signer avec florent-perso puis
superviseur-perso. Écrit les approbations signées Ed25519 dans acks.ndjson.

Aucun secret n'est stocké : la passphrase reste en mémoire de la fenêtre, la clé
privée reste chiffrée sur disque. Lancement :
    venv\\Scripts\\python.exe tools\\gitnexus_sign_gui.py
"""
from __future__ import annotations

import base64
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.gitnexus_write_policy import canonical_approval_payload  # noqa: E402

STREAM = ROOT / "collab" / "messages" / "stream.ndjson"
ACKS = ROOT / "collab" / "messages" / "acks.ndjson"
KEYDIR = Path.home() / ".titanium_gitnexus_keys"
KEYS = [("florent-perso", "florent"), ("superviseur-perso", "claude")]


def _latest_request() -> dict | None:
    if not STREAM.exists():
        return None
    reqs = []
    for line in STREAM.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "gitnexus_write_request":
            reqs.append(r)
    return reqs[-1] if reqs else None


def _already_signed(request_id: str, actor: str) -> bool:
    if not ACKS.exists():
        return False
    for line in ACKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            a = json.loads(line)
        except json.JSONDecodeError:
            continue
        if a.get("in_reply_to") == request_id and str(a.get("from")).lower() == actor:
            return True
    return False


def _sign(req: dict, key_id: str, passphrase: str) -> str:
    priv = KEYDIR / f"{key_id}.private.pem"
    meta = json.loads((KEYDIR / f"{key_id}.meta.json").read_text(encoding="utf-8"))
    actor = meta["actor"]
    sk = serialization.load_pem_private_key(priv.read_bytes(), password=passphrase.encode("utf-8"))
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
    sig = sk.sign(canonical_approval_payload(approval))
    approval["signature"] = {"algorithm": "Ed25519", "key_id": meta["key_id"],
                             "value_b64": base64.b64encode(sig).decode()}
    ACKS.parent.mkdir(parents=True, exist_ok=True)
    with ACKS.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(approval, ensure_ascii=False, sort_keys=True) + "\n")
    return actor


class App:
    def __init__(self, root: tk.Tk, req: dict) -> None:
        self.req = req
        root.title("Signer l'approbation GitNexus")
        root.geometry("640x420")
        pad = {"padx": 12, "pady": 6}

        head = ttk.Label(root, text="Répétition — garde d'écriture signée", font=("Segoe UI", 13, "bold"))
        head.pack(anchor="w", **pad)

        args = req.get("args", {})
        card = (
            f"Demande   : {req.get('id')}\n"
            f"Outil     : {req.get('tool')}  (dry_run={args.get('dry_run')})\n"
            f"Cible     : {args.get('symbol_name')} → {args.get('new_name')}  dans {args.get('file_path')}\n"
            f"Fichiers  : {', '.join(req.get('files', []))}\n"
            f"Risque    : {req.get('impact_risk')}\n"
            f"Expire à  : {req.get('expires_ts')}"
        )
        box = tk.Text(root, height=7, width=76, relief="solid", borderwidth=1)
        box.insert("1.0", card)
        box.configure(state="disabled", background="#1e1e1e", foreground="#d4d4d4")
        box.pack(**pad)

        ttk.Label(root, text="Saisis la passphrase de CHAQUE clé puis clique « Signer ».").pack(anchor="w", **pad)

        self.rows = {}
        for key_id, actor in KEYS:
            frame = ttk.Frame(root)
            frame.pack(fill="x", **pad)
            done = _already_signed(req["id"], actor)
            ttk.Label(frame, text=f"{key_id}  ({actor})", width=24).pack(side="left")
            var = tk.StringVar()
            entry = ttk.Entry(frame, show="•", textvariable=var, width=24)
            entry.pack(side="left", padx=6)
            status = ttk.Label(frame, text="✅ déjà signé" if done else "en attente",
                               foreground="green" if done else "gray")
            status.pack(side="left", padx=6)
            btn = ttk.Button(frame, text="Signer",
                             command=lambda k=key_id, a=actor: self.do_sign(k, a))
            btn.pack(side="right")
            if done:
                entry.configure(state="disabled")
                btn.configure(state="disabled")
            self.rows[actor] = (var, status, entry, btn)

        self.msg = ttk.Label(root, text="", foreground="#2266cc")
        self.msg.pack(anchor="w", **pad)
        ttk.Button(root, text="Fermer", command=root.destroy).pack(side="right", padx=12, pady=10)
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        signed = [a for a, (_, s, _, _) in self.rows.items() if "✅" in s.cget("text")]
        if len(signed) >= 2:
            self.msg.configure(text="✅ Les DEUX signatures sont posées. Reviens sur Claude et écris « signé ».")

    def do_sign(self, key_id: str, actor: str) -> None:
        var, status, entry, btn = self.rows[actor]
        pw = var.get()
        if not pw:
            messagebox.showwarning("Passphrase", "Entre la passphrase de cette clé.")
            return
        try:
            _sign(self.req, key_id, pw)
        except Exception as exc:  # passphrase incorrecte ou clé illisible
            messagebox.showerror("Échec", f"Signature refusée : passphrase incorrecte ou clé illisible.\n\n{type(exc).__name__}")
            var.set("")
            return
        status.configure(text="✅ signé", foreground="green")
        entry.configure(state="disabled")
        btn.configure(state="disabled")
        var.set("")
        self._refresh_hint()


def main() -> None:
    req = _latest_request()
    root = tk.Tk()
    if req is None:
        messagebox.showerror("Aucune demande", "Aucune demande d'écriture GitNexus en attente dans le bus.")
        root.destroy()
        return
    App(root, req)
    root.mainloop()


if __name__ == "__main__":
    main()
