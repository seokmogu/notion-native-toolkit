"""Bounded descriptor-relative reads. Never follow links, including root ancestors."""

from __future__ import annotations

import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


class ContextScopeError(ValueError):
    """A context request cannot be served within the configured boundary."""


def split_path(value: str, *, root_ok: bool = False) -> tuple[str, ...]:
    if value == "." and root_ok:
        return ()
    if not isinstance(value, str) or not value or len(value.encode()) > 1024:
        raise ContextScopeError("Invalid relative path")
    if value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ContextScopeError("Invalid relative path")
    if "\\" in value or "%" in value:
        raise ContextScopeError("Invalid relative path")
    parts = tuple(value.split("/"))
    if len(parts) > 64 or any(p in {"", ".", ".."} for p in parts):
        raise ContextScopeError(
            "Project paths must not contain traversal or control characters"
        )
    return parts


@contextmanager
def open_beneath(
    root: Path, parts: tuple[str, ...], *, directory: bool = False
) -> Generator[int]:
    """Pin every ancestor using openat/O_NOFOLLOW; the returned fd owns the read."""
    if not root.is_absolute() or ".." in root.parts:
        raise ContextScopeError("Context root must be an absolute physical path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        all_parts = root.parts[1:] + parts
        device = None
        for index, part in enumerate(all_parts):
            last = index == len(all_parts) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not last or directory:
                flags |= os.O_DIRECTORY
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            info = os.fstat(fd)
            if index == len(root.parts) - 2:
                device = info.st_dev
            elif device is not None and info.st_dev != device:
                raise ContextScopeError("Mount crossing is not allowed")
        info = os.fstat(fd)
        if directory and not stat.S_ISDIR(info.st_mode):
            raise ContextScopeError("Directory required")
        if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ContextScopeError("A regular, non-hardlinked file is required")
        yield fd
    except OSError as exc:
        # Avoid filesystem paths/contents in errors crossing the MCP boundary.
        raise ContextScopeError(
            "Path unavailable or Symlinked project paths denied"
        ) from exc
    finally:
        os.close(fd)


def read_text(root: Path, parts: tuple[str, ...], max_bytes: int) -> tuple[str, bytes]:
    with open_beneath(root, parts) as fd:
        before = os.fstat(fd)
        if before.st_size > max_bytes:
            raise ContextScopeError("File exceeds byte limit")
        raw = bytearray()
        while len(raw) <= max_bytes:
            block = os.read(fd, min(65536, max_bytes + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(fd)
        if len(raw) > max_bytes:
            raise ContextScopeError("File exceeds byte limit")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ContextScopeError(
                "File changed during read; retry with fresh context"
            )
    if b"\0" in raw:
        raise ContextScopeError("Binary content is not allowed")
    try:
        return bytes(raw).decode("utf-8"), bytes(raw)
    except UnicodeDecodeError as exc:
        raise ContextScopeError("Only UTF-8 text is allowed") from exc


def list_entries(
    root: Path, parts: tuple[str, ...], limit: int
) -> list[tuple[str, int]]:
    with open_beneath(root, parts, directory=True) as fd:
        result: list[tuple[str, int]] = []
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(result) >= limit:
                    raise ContextScopeError(
                        "Directory entry limit reached; narrow the scope"
                    )
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                except OSError:
                    continue
                result.append((entry.name, mode))
        return sorted(result)
