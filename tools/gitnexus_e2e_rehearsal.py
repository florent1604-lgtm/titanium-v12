"""tools/gitnexus_e2e_rehearsal.py — Répétition BOUT-EN-BOUT de la garde d'écriture signée.

⚠️ NE TOUCHE PAS le registre GitNexus. Construit une DEMANDE de rename (dry-run,
format identique à ce que produit la garde) puis PROUVE que la garde exige
2 signatures Ed25519 (superviseur + Florent). Aucune exécution downstream, aucun
rename réel : c'est une répétition du circuit d'APPROBATION avec les vraies clés.

  propose : crée la demande dans collab/messages/stream.ndjson + imprime la carte
            et les 2 commandes de signature à lancer par Florent.
  verify  : lit la demande + acks.ndjson, prouve ACCEPTED avec 2 sigs valides,
            REJECTED avec 1 seule, et l'anti-rejeu (usage unique) sur un ledger
            de test isolé (la production n'est pas polluée).
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta, timezone
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.gitnexus_write_policy import (  # noqa: E402
    ExecutionLedger,
    GateRefused,
    WriteRequest,
    args_sha256,
    find_valid_approvals,
    fingerprint_files,
    load_trusted_public_keys,
    normalize_args,
)

STREAM = ROOT / "collab" / "messages" / "stream.ndjson"
ACKS = ROOT / "collab" / "messages" / "acks.ndjson"
KEYS = ROOT / "collab" / "governance" / "gitnexus_approver_keys.json"
KEYDIR = Path.home() / ".titanium_gitnexus_keys"

# Cible BÉNIGNE : rename no-op d'un symbole vers lui-même (jamais exécuté).
TARGET_FILE = "emotion/market_context.py"
TARGET_SYMBOL = "emotion_for"
REHEARSAL_TTL_SECONDS = 3600   # 1 h propose→sign (chaque signature reste valable 15 min avant le verify)


def _append(path: Path, row: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_requests() -> list[dict]:
    import json
    if not STREAM.exists():
        return []
    out = []
    for line in STREAM.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _load_acks() -> list[dict]:
    import json
    if not ACKS.exists():
        return []
    out = []
    for line in ACKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _request_obj(msg: dict) -> WriteRequest:
    created = datetime.fromisoformat(str(msg["ts_utc"]).replace("Z", "+00:00"))
    expires = datetime.fromisoformat(str(msg["expires_ts"]).replace("Z", "+00:00"))
    return WriteRequest(
        request_id=str(msg["id"]), tool=msg["tool"], args=dict(msg["args"]),
        args_sha256=str(msg["args_sha256"]), created_ts=created, expires_ts=expires,
        impact_risk=str(msg["impact_risk"]), files=tuple(msg["files"]),
        file_fingerprint=str(msg["file_fingerprint"]),
    )


def propose() -> None:
    from uuid import uuid4
    args = normalize_args("rename", {
        "repo": "titanium-v12", "file_path": TARGET_FILE,
        "symbol_name": TARGET_SYMBOL, "new_name": TARGET_SYMBOL, "dry_run": True,
    })
    created = datetime.now(timezone.utc)
    request = WriteRequest(
        request_id=str(uuid4()), tool="rename", args=args,
        args_sha256=args_sha256(args), created_ts=created,
        expires_ts=created + timedelta(seconds=REHEARSAL_TTL_SECONDS),
        impact_risk="LOW", files=(TARGET_FILE,),
        file_fingerprint=fingerprint_files([TARGET_FILE], root=ROOT),
    )
    msg = {
        "id": request.request_id, "type": "gitnexus_write_request", "from": "hermes",
        "to": "claude_or_codex", "task": "GITNEXUS_WRITE",
        "ts_utc": request.created_ts.isoformat(), "expires_ts": request.expires_ts.isoformat(),
        "tool": request.tool, "args": request.args, "args_sha256": request.args_sha256,
        "impact_risk": request.impact_risk, "files": list(request.files),
        "file_fingerprint": request.file_fingerprint,
        "preview": {"note": "REHEARSAL — aucune exécution downstream", "dry_run": True},
        "content": "PENDING_APPROVAL", "body": "PENDING_APPROVAL",
    }
    _append(STREAM, msg)

    fp = KEYDIR / "florent-perso.private.pem"
    sp = KEYDIR / "superviseur-perso.private.pem"
    py = r"venv\Scripts\python.exe"
    print("\n── CARTE DE DEMANDE (répétition) ──────────────────────────────")
    print(f"  request-id : {request.request_id}")
    print(f"  outil      : {request.tool}  (dry_run=True)")
    print(f"  cible      : {TARGET_SYMBOL} → {TARGET_SYMBOL}  dans {TARGET_FILE}")
    print(f"  risque     : {request.impact_risk}")
    print(f"  args_sha256: {request.args_sha256[:16]}…")
    print(f"  expire à   : {request.expires_ts.isoformat()}")
    print("────────────────────────────────────────────────────────────────")
    print("\n▶ Florent, signe avec TES DEUX clés (ordre indifférent) :\n")
    print(f'  {py} tools\\gitnexus_sign_approval.py --request-id {request.request_id} --key "{fp}"')
    print(f'  {py} tools\\gitnexus_sign_approval.py --request-id {request.request_id} --key "{sp}"')
    print("\n  Puis je lance la vérification :")
    print(f'  {py} tools\\gitnexus_e2e_rehearsal.py verify --request-id {request.request_id}\n')


def verify(request_id: str) -> None:
    reqs = [m for m in _load_requests()
            if m.get("type") == "gitnexus_write_request" and m.get("id") == request_id]
    if not reqs:
        raise SystemExit(f"Demande introuvable : {request_id}")
    request = _request_obj(reqs[-1])
    approvals = [a for a in _load_acks() if a.get("in_reply_to") == request_id]
    trusted = load_trusted_public_keys(KEYS)

    signers = sorted({a.get("from") for a in approvals})
    print(f"\n  Demande       : {request_id}")
    print(f"  Approbations  : {len(approvals)} — signataires {signers}")

    # 1) Cas nominal : 2 signatures valides → ACCEPTED
    try:
        result = find_valid_approvals(request, approvals, trusted_public_keys=trusted,
                                      require_florent_all=True)
        print(f"\n  ✅ ACCEPTED — superviseur='{result.supervisor}', florent_override={result.florent_override}")
    except GateRefused as e:
        print(f"\n  ⛔ REFUSÉE ({e}). Il faut 2 signatures valides (superviseur + florent) non expirées.")
        return

    # 2) Preuve : une seule signature ne suffit pas
    only_super = [a for a in approvals if str(a.get("from")).lower() in ("claude", "codex")]
    only_flo = [a for a in approvals if str(a.get("from")).lower() == "florent"]
    for label, subset, expect in [("superviseur seul", only_super, "FLORENT_REQUIRED"),
                                  ("florent seul", only_flo, "SUPERVISOR_REQUIRED")]:
        try:
            find_valid_approvals(request, subset, trusted_public_keys=trusted, require_florent_all=True)
            print(f"  ⚠️  {label} : ACCEPTÉ — ANOMALIE (devrait être refusé)")
        except GateRefused as e:
            print(f"  ✅ {label} → REFUSÉ ({e})")

    # 3) Anti-rejeu sur un ledger de TEST isolé (production non touchée)
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="gn_rehearsal_"))
    ledger = ExecutionLedger(tmp / "ledger.ndjson", tmp / "ledger.lock")
    ledger.consume_once(request_id)
    try:
        ledger.consume_once(request_id)
        print("  ⚠️  rejeu : ACCEPTÉ — ANOMALIE (devrait être refusé)")
    except GateRefused as e:
        print(f"  ✅ usage unique → 2e consommation REFUSÉE ({e})")
    print("\n  ⓘ Répétition terminée. Aucun rename réel, registre GitNexus intact.\n")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Répétition E2E de la garde d'écriture signée.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("propose")
    v = sub.add_parser("verify")
    v.add_argument("--request-id", required=True)
    a = ap.parse_args()
    if a.cmd == "propose":
        propose()
    else:
        verify(a.request_id)


if __name__ == "__main__":
    main()
