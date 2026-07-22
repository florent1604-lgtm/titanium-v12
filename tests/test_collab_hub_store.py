from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from collab_hub.contracts import MessageDraft
from collab_hub.store import CollabStore, IdempotencyConflict


def _draft(key: str, *, content: str = "preuve vérifiable") -> MessageDraft:
    return MessageDraft(
        principal="codex",
        target="claude",
        kind="review",
        content=content,
        idempotency_key=key,
        task_id="COLLAB_HUB",
        evidence_refs=("gitnexus://repo/titanium-v12/context",),
    )


def test_publish_is_durable_across_restart(tmp_path: Path) -> None:
    db = tmp_path / "collab.sqlite3"
    store = CollabStore(db)
    receipt = store.publish(_draft("durable-1"))
    store.close()

    reopened = CollabStore(db)
    rows = reopened.read(after_offset=0, limit=10)

    assert receipt.global_offset == 1
    assert len(rows) == 1
    assert rows[0].message_id == receipt.message_id
    assert rows[0].content == "preuve vérifiable"
    assert rows[0].evidence_refs == (
        "gitnexus://repo/titanium-v12/context",
    )
    assert reopened.health()["journal_mode"] == "WAL"
    reopened.close()


def test_exact_retry_is_idempotent_and_divergent_retry_is_rejected(
    tmp_path: Path,
) -> None:
    store = CollabStore(tmp_path / "collab.sqlite3")
    first = store.publish(_draft("retry-1"))
    duplicate = store.publish(_draft("retry-1"))

    assert duplicate.message_id == first.message_id
    assert duplicate.global_offset == first.global_offset
    assert duplicate.duplicate is True
    with pytest.raises(IdempotencyConflict):
        store.publish(_draft("retry-1", content="contenu divergent"))
    assert len(store.read(after_offset=0, limit=10)) == 1
    store.close()


def test_concurrent_publish_allocates_unique_contiguous_offsets(
    tmp_path: Path,
) -> None:
    store = CollabStore(tmp_path / "collab.sqlite3")

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(
            pool.map(lambda index: store.publish(_draft(f"parallel-{index}")), range(24))
        )

    assert sorted(item.global_offset for item in receipts) == list(range(1, 25))
    assert len({item.message_id for item in receipts}) == 24
    store.close()


def test_consumer_offset_is_monotone_and_persists(tmp_path: Path) -> None:
    db = tmp_path / "collab.sqlite3"
    store = CollabStore(db)
    store.ack(consumer_id="hermes", global_offset=7)
    store.ack(consumer_id="hermes", global_offset=3)
    assert store.consumer_offset("hermes") == 7
    store.close()

    reopened = CollabStore(db)
    assert reopened.consumer_offset("hermes") == 7
    reopened.close()


def test_presence_is_durable_and_rejects_unknown_principal(tmp_path: Path) -> None:
    db = tmp_path / "collab.sqlite3"
    store = CollabStore(db)
    store.set_presence(principal="hermes", state="ONLINE", detail="orchestrateur C1")
    store.close()

    reopened = CollabStore(db)
    rows = reopened.list_presence()
    assert rows[0]["principal"] == "hermes"
    assert rows[0]["state"] == "ONLINE"
    assert rows[0]["detail"] == "orchestrateur C1"
    with pytest.raises(ValueError, match="principal"):
        reopened.set_presence(principal="intrus", state="ONLINE")
    reopened.close()
