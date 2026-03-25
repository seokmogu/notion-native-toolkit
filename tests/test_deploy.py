"""Tests for deploy.py (SPEC-001 FR-04, FR-06)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from notion_native_toolkit.deploy import (
    DeployReport,
    DeployResult,
    Section,
    _collect_md_files,
    _extract_title,
    split_by_h1,
)


class TestExtractTitle:
    def test_h1_title(self) -> None:
        assert _extract_title("# My Guide\nContent", Path("guide.md")) == "My Guide"

    def test_no_heading_uses_filename(self) -> None:
        assert _extract_title("No heading", Path("my-doc.md")) == "My Doc"

    def test_h2_not_used(self) -> None:
        title = _extract_title("## Section\nContent", Path("doc.md"))
        assert title == "Doc"  # Falls back to filename

    def test_first_h1_used(self) -> None:
        title = _extract_title("# First\n# Second", Path("doc.md"))
        assert title == "First"


class TestCollectMdFiles:
    def test_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "readme.md"
            f.write_text("# Readme")
            files = _collect_md_files(f)
            assert len(files) == 1
            assert files[0].name == "readme.md"

    def test_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "a.md").write_text("# A")
            (p / "b.md").write_text("# B")
            (p / "c.txt").write_text("not md")
            files = _collect_md_files(p)
            assert len(files) == 2

    def test_hidden_files_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "readme.md").write_text("# Readme")
            (p / ".hidden.md").write_text("# Hidden")
            files = _collect_md_files(p)
            assert len(files) == 1
            assert files[0].name == "readme.md"

    def test_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "root.md").write_text("# Root")
            sub = p / "sub"
            sub.mkdir()
            (sub / "nested.md").write_text("# Nested")
            files = _collect_md_files(p)
            names = [f.name for f in files]
            assert "root.md" in names
            assert "nested.md" in names

    def test_non_md_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "data.json"
            f.write_text("{}")
            assert _collect_md_files(f) == []

    def test_nonexistent(self) -> None:
        assert _collect_md_files(Path("/nonexistent")) == []


class TestDeployReport:
    def test_summary_counts(self) -> None:
        report = DeployReport()
        report.results.append(
            DeployResult("a.md", "id1", "url1", "A", "created", 5)
        )
        report.results.append(
            DeployResult("b.md", "id2", "url2", "B", "updated", 3)
        )
        report.results.append(
            DeployResult("c.md", "id3", "url3", "C", "skipped", 0)
        )
        assert report.created == 1
        assert report.updated == 1
        assert report.skipped == 1

    def test_to_dict(self) -> None:
        report = DeployReport()
        report.results.append(
            DeployResult("a.md", "id1", "url1", "A", "created", 5)
        )
        report.errors.append({"file": "err.md", "error": "failed"})
        report.stale_pages.append("old.md")
        d = report.to_dict()
        assert d["summary"]["created"] == 1
        assert d["summary"]["errors"] == 1
        assert d["summary"]["stale_pages"] == 1
        assert len(d["results"]) == 1
        assert len(d["errors"]) == 1
        assert len(d["stale_pages"]) == 1


class TestSplitByH1:
    """FR-05: Split markdown by H1 headings for tree mode."""

    def test_multiple_h1(self) -> None:
        md = "# Intro\nIntro text.\n\n# API\nAPI docs.\n\n# Changelog\n- v1.0\n"
        sections = split_by_h1(md)
        assert len(sections) == 3
        assert sections[0].title == "Intro"
        assert "Intro text" in sections[0].content
        assert sections[1].title == "API"
        assert sections[2].title == "Changelog"

    def test_no_h1(self) -> None:
        md = "## Only H2\nContent here\n"
        sections = split_by_h1(md)
        assert len(sections) == 1
        assert sections[0].title == ""
        assert "Only H2" in sections[0].content

    def test_single_h1(self) -> None:
        md = "# Only Title\nSome content\n"
        sections = split_by_h1(md)
        assert len(sections) == 1
        assert sections[0].title == "Only Title"

    def test_content_before_first_h1(self) -> None:
        md = "Preamble text\n\n# First Section\nContent\n"
        sections = split_by_h1(md)
        assert len(sections) == 2
        assert sections[0].title == ""
        assert "Preamble" in sections[0].content
        assert sections[1].title == "First Section"

    def test_h2_not_split(self) -> None:
        md = "# Main\n## Sub\nContent under sub\n"
        sections = split_by_h1(md)
        assert len(sections) == 1
        assert "## Sub" in sections[0].content

    def test_preserves_content_between_h1(self) -> None:
        md = "# A\nLine 1\nLine 2\n\n## Sub A\nMore\n\n# B\nB content\n"
        sections = split_by_h1(md)
        assert len(sections) == 2
        assert "Line 1" in sections[0].content
        assert "## Sub A" in sections[0].content
        assert "B content" in sections[1].content
