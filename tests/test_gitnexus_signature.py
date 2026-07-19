"""Verdict Claude — la signature Ed25519 ferme le trou de forge (P0 initial).

Prouve : une approbation SIGNÉE par une clé du registre est acceptée ; une
approbation NON signée, signée par une clé INCONNUE, ALTÉRÉE, ou dont l'acteur
ne correspond pas à la clé, est REFUSÉE. Registre vide = fail-closed.
"""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import tools.gitnexus_write_policy as pol


def _keypair():
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes_raw()
    return sk, base64.b64encode(pub).decode()


def _registry(entries):
    # entries: list of (key_id, actor, pub_b64)
    keys = [{"key_id": kid, "actor": a, "algorithm": "Ed25519",
             "public_key_b64": pb, "enabled": True} for kid, a, pb in entries]
    return {kid: {"actor": a, "algorithm": "Ed25519", "public_key_b64": pb}
            for kid, a, pb in entries}


def _request():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    return pol.WriteRequest(
        request_id="req-1", tool="rename",
        args={"repo": "titanium-v12", "symbol_name": "foo", "new_name": "bar", "dry_run": True},
        args_sha256="a" * 64, created_ts=now, expires_ts=now + timedelta(seconds=600),
        impact_risk="LOW", files=("README.md",), file_fingerprint="f" * 64)


def _signed_approval(req, actor, key_id, sk, override):
    ap = {
        "id": f"ap-{actor}", "type": "gitnexus_write_approval", "verdict": "APPROVED",
        "from": actor, "to": "hermes", "in_reply_to": req.request_id,
        "ts_utc": req.created_ts.isoformat(), "tool": req.tool,
        "args_sha256": req.args_sha256, "file_fingerprint": req.file_fingerprint,
        "request_expires_ts": req.expires_ts.isoformat(),
        "nonce": "n" * 24, "florent_override": override,
    }
    sig = sk.sign(pol.canonical_approval_payload(ap))
    ap["signature"] = {"algorithm": "Ed25519", "key_id": key_id,
                       "value_b64": base64.b64encode(sig).decode()}
    return ap


def test_valid_signed_supervisor_plus_florent_accepted():
    req = _request()
    sk_c, pb_c = _keypair(); sk_f, pb_f = _keypair()
    reg = _registry([("k-claude", "claude", pb_c), ("k-florent", "florent", pb_f)])
    a_sup = _signed_approval(req, "claude", "k-claude", sk_c, False)
    a_flo = _signed_approval(req, "florent", "k-florent", sk_f, True)
    res = pol.find_valid_approvals(req, [a_sup, a_flo], trusted_public_keys=reg,
                                   now=req.created_ts + timedelta(seconds=1))
    assert res.supervisor == "claude" and res.florent_override is True


def test_unsigned_approval_refused():
    req = _request()
    sk_c, pb_c = _keypair()
    reg = _registry([("k-claude", "claude", pb_c)])
    a = _signed_approval(req, "claude", "k-claude", sk_c, False)
    a.pop("signature")                      # ← Hermes forge sans signature
    with pytest.raises(pol.GateRefused) as e:
        pol.find_valid_approvals(req, [a], trusted_public_keys=reg,
                                 now=req.created_ts + timedelta(seconds=1))
    assert "SIGNATURE_REQUIRED" in str(e.value)


def test_unknown_key_refused():
    req = _request()
    sk_evil, _ = _keypair(); _, pb_c = _keypair()
    reg = _registry([("k-claude", "claude", pb_c)])
    a = _signed_approval(req, "claude", "k-claude", sk_evil, False)  # bonne key_id, MAUVAISE clé
    with pytest.raises(pol.GateRefused) as e:
        pol.find_valid_approvals(req, [a], trusted_public_keys=reg,
                                 now=req.created_ts + timedelta(seconds=1))
    assert "SIGNATURE_INVALID" in str(e.value)


def test_actor_key_mismatch_refused():
    # Hermes signe avec SA clé mais prétend 'from: claude'
    req = _request()
    sk_h, pb_h = _keypair()
    reg = _registry([("k-hermes", "florent", pb_h)])   # clé enregistrée pour florent
    a = _signed_approval(req, "claude", "k-hermes", sk_h, False)  # from=claude ≠ actor florent
    with pytest.raises(pol.GateRefused) as e:
        pol.find_valid_approvals(req, [a], trusted_public_keys=reg,
                                 now=req.created_ts + timedelta(seconds=1))
    assert "SIGNER_ACTOR_MISMATCH" in str(e.value)


def test_tampered_after_signature_refused():
    req = _request()
    sk_c, pb_c = _keypair(); sk_f, pb_f = _keypair()
    reg = _registry([("k-claude", "claude", pb_c), ("k-florent", "florent", pb_f)])
    a_sup = _signed_approval(req, "claude", "k-claude", sk_c, False)
    a_flo = _signed_approval(req, "florent", "k-florent", sk_f, True)
    a_sup["args_sha256"] = "b" * 64        # ← altération après signature
    with pytest.raises(pol.GateRefused):    # APPROVAL_MISMATCH (ne correspond plus à la requête)
        pol.find_valid_approvals(req, [a_sup, a_flo], trusted_public_keys=reg,
                                 now=req.created_ts + timedelta(seconds=1))


def test_supervisor_only_without_florent_refused():
    req = _request()
    sk_c, pb_c = _keypair()
    reg = _registry([("k-claude", "claude", pb_c)])
    a_sup = _signed_approval(req, "claude", "k-claude", sk_c, False)
    with pytest.raises(pol.GateRefused) as e:   # Florent requis pour TOUS les writes
        pol.find_valid_approvals(req, [a_sup], trusted_public_keys=reg,
                                 now=req.created_ts + timedelta(seconds=1))
    assert "FLORENT_REQUIRED" in str(e.value)


def test_empty_registry_fail_closed(tmp_path):
    reg_file = tmp_path / "keys.json"
    reg_file.write_text('{"version": 1, "keys": []}', encoding="utf-8")
    with pytest.raises(pol.GateRefused) as e:
        pol.load_trusted_public_keys(reg_file)
    assert "SIGNATURE_KEYS_UNAVAILABLE" in str(e.value)
