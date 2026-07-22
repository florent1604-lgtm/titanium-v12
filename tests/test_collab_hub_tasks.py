from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from collab_hub.contracts import MessageDraft
from collab_hub.store import CollabStore
from collab_hub.task_contracts import TASK_STATES, TaskDraft


@pytest.fixture
def store(tmp_path: Path):
    opened = CollabStore(tmp_path / "collab.sqlite3")
    yield opened.tasks
    opened.close()


def _message(key: str) -> MessageDraft:
    return MessageDraft(
        principal="codex",
        target="claude",
        kind="status",
        content=key,
        idempotency_key=key,
    )


def test_create_task_persists_initial_attempt_across_restart(tmp_path: Path) -> None:
    db = tmp_path / "collab.sqlite3"
    opened = CollabStore(db)
    created = opened.tasks.create_task(
        TaskDraft(title="Reindex", owner="codex", priority="P1")
    )
    opened.close()

    reopened = CollabStore(db)
    loaded = reopened.tasks.get_task(created.task_id)

    assert loaded == created
    assert created.status == "NOUVEAU"
    assert created.attempt_id
    assert created.requested_by == "codex"
    assert len(created.payload_sha256) == 64
    assert reopened.health()["journal_mode"] == "WAL"
    reopened.close()


def test_failure_is_immutable_and_retry_creates_new_attempt(store) -> None:
    task = store.create_task(TaskDraft(title="Reindex", owner="codex", priority="P1"))
    failure = store.record_failure(task.task_id, "TEST_FAILED", "pytest:1")
    retry = store.request_retry(task.task_id, requested_by="florent")

    assert retry.attempt_id != failure.attempt_id
    assert retry.requested_by == "florent"
    assert store.list_failed(statuses=("NOUVEAU",))[0].reason_code == "TEST_FAILED"
    assert store.list_failed(statuses=("NOUVEAU",))[0] == failure


def test_state_machine_accepts_only_the_ordered_workflow(store) -> None:
    task = store.create_task(TaskDraft(title="Corriger", owner="claude", priority="P2"))

    for expected in TASK_STATES[1:]:
        task = store.transition(task.task_id, expected)
        assert task.status == expected

    with pytest.raises(ValueError, match="transition"):
        store.transition(task.task_id, "NOUVEAU")

    other = store.create_task(TaskDraft(title="Saut", owner="hermes", priority="P3"))
    with pytest.raises(ValueError, match="transition"):
        store.transition(other.task_id, "CLOS")


def test_failure_reason_must_be_registered(store) -> None:
    task = store.create_task(TaskDraft(title="Tester", owner="codex", priority="P1"))

    with pytest.raises(ValueError, match="reason_code"):
        store.record_failure(task.task_id, "ARBITRARY_EXCEPTION", "trace assainie")
    assert store.list_failed() == ()


def test_retry_requires_an_existing_failure_and_never_runs_automatically(store) -> None:
    task = store.create_task(TaskDraft(title="Attendre", owner="codex", priority="P1"))

    with pytest.raises(ValueError, match="failed"):
        store.request_retry(task.task_id, requested_by="florent")
    assert store.attempt_count(task.task_id) == 1


def test_read_before_returns_bounded_page_in_global_order(tmp_path: Path) -> None:
    opened = CollabStore(tmp_path / "collab.sqlite3")
    for index in range(1, 7):
        opened.publish(_message(f"message-{index}"))

    page = opened.read_before(before_offset=6, limit=3)

    assert [row.global_offset for row in page] == [3, 4, 5]
    assert opened.read_before(before_offset=1, limit=10) == ()
    opened.close()


def test_task_migration_is_additive_idempotent_and_serializes_writes(tmp_path: Path) -> None:
    db = tmp_path / "collab.sqlite3"
    first = CollabStore(db)
    first.publish(_message("preserved"))
    first.close()
    reopened = CollabStore(db)

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = tuple(
            pool.map(
                lambda index: reopened.tasks.create_task(
                    TaskDraft(title=f"Task {index}", owner="codex", priority="P2")
                ),
                range(24),
            )
        )

    assert len({task.task_id for task in created}) == 24
    assert len({task.attempt_id for task in created}) == 24
    assert reopened.read(after_offset=0, limit=10)[0].content == "preserved"
    assert reopened.health()["journal_mode"] == "WAL"
    reopened.close()
