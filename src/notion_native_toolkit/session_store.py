"""Private, locked, immutable checkpoints for the desktop session pool.

This store never controls UI. Commit a prepared action before handing it to an
operator; after a crash use explicit recovery rather than repeating the action.
It protects against accidental concurrent writers, not a malicious local owner.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from notion_native_toolkit.context_files import open_beneath
from notion_native_toolkit.session_pool import SessionPool

MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024
MAX_CHECKPOINTS = 10000
_CHECKPOINT = re.compile(r"checkpoint-(\d{6})\.json\Z")


class SessionStoreError(RuntimeError):
    """A private session checkpoint cannot be read or safely committed."""


def _json_bytes(value: object) -> bytes:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise SessionStoreError("session checkpoint exceeds the byte limit")
    return data


def _private_file(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SessionStoreError(
            "session files must be owned regular files with mode 0600"
        )


def _read_checkpoint(directory: int, name: str) -> tuple[dict[str, Any], str]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        _private_file(fd)
        if os.fstat(fd).st_size > MAX_CHECKPOINT_BYTES:
            raise SessionStoreError("session checkpoint exceeds the byte limit")
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(MAX_CHECKPOINT_BYTES + 1)
        if len(data) > MAX_CHECKPOINT_BYTES:
            raise SessionStoreError("session checkpoint exceeds the byte limit")
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            raise SessionStoreError("session checkpoint is not valid JSON") from None
        if not isinstance(result, dict):
            raise SessionStoreError("session checkpoint must be an object")
        return result, sha256(data).hexdigest()
    finally:
        os.close(fd)


@dataclass
class SessionTransaction:
    """One locked transaction. Nothing is persisted until commit succeeds."""

    pool: SessionPool
    revision: int
    _directory: int
    _previous_sha256: str | None
    _committed: bool = False

    def commit(self) -> int:
        if self._committed:
            raise SessionStoreError("transaction was already committed")
        revision = self.revision + 1
        if revision >= MAX_CHECKPOINTS:
            raise SessionStoreError(
                "session checkpoint limit reached; archive and start a new session"
            )
        state = self.pool.to_state()
        # A persisted snapshot must pass the same validator as a later reader.
        SessionPool.from_state(state, recovering=False)
        data = _json_bytes(
            {
                "schema_version": 1,
                "revision": revision,
                "previous_sha256": self._previous_sha256,
                "state": state,
            }
        )
        temporary = f".pending-{uuid4().hex}"
        target = f"checkpoint-{revision:06d}.json"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._directory,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as output:
                output.write(data)
                output.flush()
                os.fsync(fd)
            # Hard-link promotion is atomic and cannot overwrite an existing checkpoint.
            os.link(
                temporary,
                target,
                src_dir_fd=self._directory,
                dst_dir_fd=self._directory,
                follow_symlinks=False,
            )
        finally:
            os.close(fd)
            os.unlink(temporary, dir_fd=self._directory)
        os.fsync(self._directory)
        self.revision = revision
        self._previous_sha256 = sha256(data).hexdigest()
        self._committed = True
        return revision


class SessionStore:
    """Use an explicit hidden project-owned directory; never a runtime default."""

    def __init__(self, path: Path) -> None:
        if (
            not path.is_absolute()
            or ".." in path.parts
            or not path.name.startswith(".notion-session-")
        ):
            raise SessionStoreError(
                "state directory must be an absolute .notion-session-<name> path"
            )
        self.path = path

    def create(self, pool: SessionPool) -> int:
        # No recursive mkdir and no overwriting an earlier run.
        _json_bytes(pool.to_state())
        with open_beneath(self.path.parent, (), directory=True) as parent:
            try:
                os.mkdir(self.path.name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                raise SessionStoreError(
                    "refusing to overwrite an existing session directory"
                ) from None
        with self.locked(expected_revision=-1, initial_pool=pool) as transaction:
            return transaction.commit()

    @contextmanager
    def locked(
        self,
        *,
        expected_revision: int | None = None,
        initial_pool: SessionPool | None = None,
    ) -> Generator[SessionTransaction]:
        with open_beneath(self.path, (), directory=True) as directory:
            info = os.fstat(directory)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise SessionStoreError(
                    "state directory must be owned by this user with mode 0700"
                )
            lock = os.open(
                ".lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory,
            )
            try:
                _private_file(lock)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise SessionStoreError(
                        "another process owns the session lock"
                    ) from None
                names = []
                with os.scandir(directory) as entries:
                    for count, entry in enumerate(entries):
                        if count > MAX_CHECKPOINTS + 100:
                            raise SessionStoreError("session checkpoint limit reached")
                        if _CHECKPOINT.fullmatch(entry.name):
                            names.append(entry.name)
                        elif entry.name != ".lock" and not entry.name.startswith(
                            ".pending-"
                        ):
                            raise SessionStoreError(
                                "unexpected file in the session store"
                            )
                names.sort()
                if not names:
                    if initial_pool is None:
                        raise SessionStoreError(
                            "session store has no committed checkpoint"
                        )
                    transaction = SessionTransaction(initial_pool, -1, directory, None)
                else:
                    if initial_pool is not None:
                        raise SessionStoreError(
                            "refusing to overwrite an existing session"
                        )
                    if names != [f"checkpoint-{i:06d}.json" for i in range(len(names))]:
                        raise SessionStoreError("session checkpoint sequence has a gap")
                    envelope, digest = _read_checkpoint(directory, names[-1])
                    revision = len(names) - 1
                    if (
                        set(envelope)
                        != {"schema_version", "revision", "previous_sha256", "state"}
                        or type(envelope["schema_version"]) is not int
                        or envelope["schema_version"] != 1
                        or type(envelope["revision"]) is not int
                        or envelope["revision"] != revision
                    ):
                        raise SessionStoreError("invalid checkpoint envelope")
                    previous = (
                        _read_checkpoint(directory, names[-2])[1] if revision else None
                    )
                    if envelope["previous_sha256"] != previous:
                        raise SessionStoreError(
                            "checkpoint predecessor digest does not match"
                        )
                    pool = SessionPool.from_state(envelope["state"], recovering=False)
                    transaction = SessionTransaction(pool, revision, directory, digest)
                if expected_revision is not None and (
                    type(expected_revision) is not int
                    or expected_revision != transaction.revision
                ):
                    raise SessionStoreError(
                        "stale session revision; read status before retrying"
                    )
                yield transaction
            finally:
                os.close(lock)
