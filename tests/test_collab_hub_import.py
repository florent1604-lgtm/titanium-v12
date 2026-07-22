from __future__ import annotations

import json
from pathlib import Path

from collab_hub.import_ndjson import import_ndjson_paths
from collab_hub.store import CollabStore


def test_import_is_idempotent_reports_malformed_lines_and_never_mutates_source(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "stream.ndjson"
    valid = {
        "id": "11111111-1111-4111-8111-111111111111",
        "type": "handoff",
        "from": "codex",
        "to": "claude",
        "task": "MIGRATION",
        "content": "preuve historique",
    }
    original = json.dumps(valid) + "\n{ligne-cassee\n"
    stream.write_text(original, encoding="utf-8")
    store = CollabStore(tmp_path / "collab.sqlite3")

    first = import_ndjson_paths(store, (stream,))
    second = import_ndjson_paths(store, (stream,))

    assert first.imported == 1
    assert first.duplicates == 0
    assert len(first.errors) == 1
    assert first.errors[0]["line"] == 2
    assert second.imported == 0
    assert second.duplicates == 1
    assert stream.read_text(encoding="utf-8") == original
    rows = store.read(after_offset=0, limit=10)
    assert rows[0].kind == "handoff"
    assert rows[0].idempotency_key == "legacy:11111111-1111-4111-8111-111111111111"
    store.close()


def test_import_maps_legacy_ack_to_c1_ack_kind(tmp_path: Path) -> None:
    ack_file = tmp_path / "acks.ndjson"
    ack_file.write_text(
        json.dumps(
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "type": "ack",
                "from": "claude",
                "to": "codex",
                "in_reply_to": "11111111-1111-4111-8111-111111111111",
                "body": "reçu",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = CollabStore(tmp_path / "collab.sqlite3")

    report = import_ndjson_paths(store, (ack_file,))

    assert report.imported == 1
    row = store.read(after_offset=0, limit=1)[0]
    assert row.kind == "ack"
    assert row.in_reply_to == "11111111-1111-4111-8111-111111111111"
    store.close()


def test_import_maps_collective_targets_without_granting_authority(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "stream.ndjson"
    rows = (
        {
            "id": "33333333-3333-4333-8333-333333333333",
            "type": "message",
            "from": "hermes",
            "to": "all",
            "content": "information equipe",
        },
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "type": "gitnexus_write_request",
            "from": "hermes",
            "to": "claude_or_codex",
            "content": "PENDING_APPROVAL",
        },
    )
    stream.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    store = CollabStore(tmp_path / "collab.sqlite3")

    report = import_ndjson_paths(store, (stream,))

    assert report.imported == 2
    assert report.skipped_security == 0
    imported = store.read(after_offset=0, limit=10)
    assert imported[0].target == "topic:team"
    assert imported[0].classification == "INTERNAL"
    assert imported[1].target == "topic:supervisors"
    assert imported[1].classification == "SENSITIVE_METADATA"
    store.close()


def test_import_excludes_signed_gitnexus_approvals_from_general_hub(
    tmp_path: Path,
) -> None:
    approvals = tmp_path / "acks.ndjson"
    approvals.write_text(
        json.dumps(
            {
                "id": "55555555-5555-4555-8555-555555555555",
                "type": "gitnexus_write_approval",
                "from": "claude",
                "to": "codex",
                "signature": "must-not-enter-general-hub",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = CollabStore(tmp_path / "collab.sqlite3")

    report = import_ndjson_paths(store, (approvals,))

    assert report.imported == 0
    assert report.skipped_security == 1
    assert report.errors == ()
    assert store.read(after_offset=0, limit=10) == ()
    store.close()
