from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from notion_native_toolkit.context_files import ContextScopeError
from notion_native_toolkit.session_pool import ReasoningEffort, SessionPool
from notion_native_toolkit.session_store import SessionStore, SessionStoreError


def make_store(tmp_path: Path) -> SessionStore:
    store = SessionStore(tmp_path / ".notion-session-fixture")
    store.create(SessionPool(session_id="session-fixture"))
    return store


def test_checkpoint_files_are_private_immutable_and_non_overwriting(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    original = (store.path / "checkpoint-000000.json").read_bytes()
    with store.locked(expected_revision=0) as transaction:
        transaction.pool.submit(
            "task",
            "Private fixture prompt",
            model="fixture-model",
            effort=ReasoningEffort.HIGH,
        )
        assert transaction.commit() == 1
        with pytest.raises(SessionStoreError, match="already committed"):
            transaction.commit()
    assert (store.path / "checkpoint-000000.json").read_bytes() == original
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in store.path.iterdir()
    )
    with pytest.raises(SessionStoreError, match="overwrite"):
        store.create(SessionPool())
    with store.locked(expected_revision=1) as transaction:
        assert transaction.pool.task_ids == ("task",)


def test_stale_revision_and_concurrent_lock_cannot_mutate_state(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with (
        store.locked(expected_revision=0),
        pytest.raises(SessionStoreError, match="another process"),
        store.locked(),
    ):
        pytest.fail("second writer acquired the lock")
    with (
        pytest.raises(SessionStoreError, match="stale"),
        store.locked(expected_revision=99),
    ):
        pytest.fail("stale writer acquired a transaction")
    assert len(list(store.path.glob("checkpoint-*.json"))) == 1


def test_uncommitted_mutation_does_not_change_authoritative_checkpoint(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    with store.locked(expected_revision=0) as transaction:
        transaction.pool.submit(
            "uncommitted", "fixture", model="fixture-model", effort=ReasoningEffort.HIGH
        )
    with store.locked(expected_revision=0) as transaction:
        assert transaction.pool.task_ids == ()


def test_incomplete_temporary_write_is_not_a_committed_action(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    (store.path / ".pending-crash-fixture").write_bytes(b'{"incomplete":')
    with store.locked(expected_revision=0) as transaction:
        assert transaction.pool.task_ids == ()


def test_corrupt_latest_checkpoint_fails_closed_without_rolling_back(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    path = store.path / "checkpoint-000001.json"
    path.write_bytes(b'{"incomplete":')
    path.chmod(0o600)
    with pytest.raises(SessionStoreError, match="valid JSON"), store.locked():
        pytest.fail("corrupt latest state must not fall back to revision zero")


@pytest.mark.parametrize("target", ["checkpoint-000000.json", ".lock"])
def test_symlinked_or_hardlinked_store_files_are_rejected(
    tmp_path: Path, target: str
) -> None:
    store = make_store(tmp_path)
    original = store.path / target
    external = tmp_path / "external-fixture"
    external.write_bytes(original.read_bytes())
    external.chmod(0o600)
    original.unlink()
    original.symlink_to(external)
    with pytest.raises((OSError, ContextScopeError, SessionStoreError)), store.locked():
        pytest.fail("symlink accepted")
    original.unlink()
    os.link(external, original)
    with pytest.raises(SessionStoreError), store.locked():
        pytest.fail("hardlink accepted")


def test_open_permissions_and_checkpoint_tampering_are_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.path.chmod(0o755)
    with pytest.raises(SessionStoreError, match="0700"), store.locked():
        pytest.fail("open directory accepted")
    store.path.chmod(0o700)
    with store.locked(expected_revision=0) as transaction:
        transaction.pool.pause()
        transaction.commit()
    earlier = store.path / "checkpoint-000000.json"
    envelope = json.loads(earlier.read_text())
    envelope["tampered"] = True
    earlier.write_text(json.dumps(envelope))
    with pytest.raises(SessionStoreError, match="predecessor"), store.locked():
        pytest.fail("mismatched predecessor accepted")


def test_state_directory_must_be_explicit_hidden_and_no_follow(tmp_path: Path) -> None:
    with pytest.raises(SessionStoreError):
        SessionStore(tmp_path / "visible-state")
    with pytest.raises(SessionStoreError):
        SessionStore(Path(".notion-session-relative"))
    store = make_store(tmp_path)
    alias = tmp_path / ".notion-session-alias"
    alias.symlink_to(store.path, target_is_directory=True)
    with pytest.raises(ContextScopeError), SessionStore(alias).locked():
        pytest.fail("symlinked state directory accepted")
