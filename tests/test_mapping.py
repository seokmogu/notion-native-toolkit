"""Tests for mapping.py (SPEC-001 FR-04)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from notion_native_toolkit.mapping import (
    PageEntry,
    PageMapping,
    compute_content_hash,
    load_mapping,
    needs_update,
    save_mapping,
)


class TestPageMapping:
    def test_set_and_get(self) -> None:
        m = PageMapping()
        m.set("docs/guide.md", "abc", "https://notion.so/guide", "Guide", "sha256:x")
        entry = m.get("docs/guide.md")
        assert entry is not None
        assert entry.page_id == "abc"
        assert entry.url == "https://notion.so/guide"
        assert entry.title == "Guide"

    def test_get_missing(self) -> None:
        m = PageMapping()
        assert m.get("nonexistent") is None

    def test_remove(self) -> None:
        m = PageMapping()
        m.set("a.md", "id1", "url1", "A", "h1")
        removed = m.remove("a.md")
        assert removed is not None
        assert removed.page_id == "id1"
        assert m.get("a.md") is None

    def test_list_paths_sorted(self) -> None:
        m = PageMapping()
        m.set("c.md", "id3", "u3", "C", "h3")
        m.set("a.md", "id1", "u1", "A", "h1")
        m.set("b.md", "id2", "u2", "B", "h2")
        assert m.list_paths() == ["a.md", "b.md", "c.md"]

    def test_to_dict_and_from_dict(self) -> None:
        m = PageMapping()
        m.set("x.md", "idx", "urlx", "X", "hx")
        d = m.to_dict()
        m2 = PageMapping.from_dict(d)
        assert m2.get("x.md") is not None
        assert m2.get("x.md").page_id == "idx"


class TestSaveLoad:
    def test_round_trip(self) -> None:
        m = PageMapping()
        m.set("docs/a.md", "id1", "url1", "A", "sha256:abc")
        m.set("docs/b.md", "id2", "url2", "B", "sha256:def")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            save_mapping(p, m)
            loaded = load_mapping(p)
            assert loaded.get("docs/a.md").url == "url1"
            assert loaded.get("docs/b.md").page_id == "id2"

    def test_load_missing_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            loaded = load_mapping(Path(td))
            assert len(loaded.entries) == 0

    def test_load_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "page_mapping.json"
            p.write_text("not json")
            loaded = load_mapping(Path(td))
            assert len(loaded.entries) == 0


class TestContentHash:
    def test_deterministic(self) -> None:
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("hello")
        assert h1 == h2

    def test_different_content(self) -> None:
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("world")
        assert h1 != h2

    def test_prefix(self) -> None:
        h = compute_content_hash("test")
        assert h.startswith("sha256:")


class TestNeedsUpdate:
    def test_none_entry(self) -> None:
        assert needs_update(None, "any content")

    def test_same_content(self) -> None:
        h = compute_content_hash("hello")
        entry = PageEntry(page_id="x", url="y", title="z", content_hash=h)
        assert not needs_update(entry, "hello")

    def test_changed_content(self) -> None:
        h = compute_content_hash("hello")
        entry = PageEntry(page_id="x", url="y", title="z", content_hash=h)
        assert needs_update(entry, "changed")
