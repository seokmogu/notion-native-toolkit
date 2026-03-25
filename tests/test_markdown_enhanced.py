"""Tests for enhanced markdown.py features (SPEC-001 Phase 1)."""

from __future__ import annotations

import pytest

from notion_native_toolkit.markdown import (
    _chunk_code_block,
    _make_image_block,
    _parse_admonition,
    _sanitize_mermaid,
    is_callout,
    markdown_to_notion_blocks,
)


class TestCodeBlockChunking:
    """FR-02: Code block chunking for blocks exceeding 2000 chars."""

    def test_short_code_not_chunked(self) -> None:
        blocks = _chunk_code_block("x = 1\n", "python")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"

    def test_long_code_chunked(self) -> None:
        long_code = "x = 1\n" * 500  # ~3000 chars
        blocks = _chunk_code_block(long_code, "python")
        assert len(blocks) >= 2
        for block in blocks:
            content = block["code"]["rich_text"][0]["text"]["content"]
            assert len(content) <= 2000

    def test_chunk_labels_python(self) -> None:
        long_code = "x = 1\n" * 500
        blocks = _chunk_code_block(long_code, "python")
        first = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        last = blocks[-1]["code"]["rich_text"][0]["text"]["content"]
        assert first.startswith("# Part 1 of")
        assert f"Part {len(blocks)} of {len(blocks)}" in last

    def test_chunk_labels_javascript(self) -> None:
        long_code = "const x = 1;\n" * 300
        blocks = _chunk_code_block(long_code, "javascript")
        first = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert first.startswith("// Part 1 of")

    def test_chunk_labels_sql(self) -> None:
        long_code = "SELECT 1;\n" * 300
        blocks = _chunk_code_block(long_code, "sql")
        first = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert first.startswith("-- Part 1 of")

    def test_chunk_labels_html(self) -> None:
        long_code = "<div>content</div>\n" * 200
        blocks = _chunk_code_block(long_code, "html")
        first = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert first.startswith("<!-- Part 1 of")
        assert "-->" in first.split("\n")[0]

    def test_pipeline_long_code_chunked(self) -> None:
        """AC-04: 3000 char Python code block splits into multiple blocks."""
        md = "```python\n" + "print('hello world')  # line\n" * 200 + "```\n"
        blocks, _ = markdown_to_notion_blocks(md)
        code_blocks = [b for b in blocks if b.get("type") == "code"]
        assert len(code_blocks) > 1
        first_content = code_blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert "Part 1 of" in first_content


class TestMermaidHandling:
    """FR-02: Mermaid diagrams are sanitized but never split."""

    def test_sanitize_removes_click(self) -> None:
        content = 'graph TD\n  A-->B\nclick A "http://example.com"'
        result = _sanitize_mermaid(content)
        assert "click" not in result
        assert "A-->B" in result

    def test_sanitize_removes_init(self) -> None:
        content = '%%{init: {"theme": "dark"}}%%\ngraph TD\n  A-->B'
        result = _sanitize_mermaid(content)
        assert "%%{init" not in result

    def test_pipeline_mermaid_never_split(self) -> None:
        md = "```mermaid\ngraph TD\n" + "  A-->B\n" * 500 + "```\n"
        blocks, _ = markdown_to_notion_blocks(md)
        code_blocks = [b for b in blocks if b.get("type") == "code"]
        assert len(code_blocks) == 1
        assert code_blocks[0]["code"]["language"] == "mermaid"


class TestGitHubAdmonition:
    """FR-07: GitHub-style admonition callouts."""

    @pytest.mark.parametrize(
        "text,expected_emoji,expected_kind",
        [
            ("[!NOTE] A note", "\U0001f4dd", "info"),
            ("[!TIP] A tip", "\U0001f4a1", "info"),
            ("[!WARNING] Be careful", "\u26a0\ufe0f", "warning"),
            ("[!CAUTION] Danger", "\u274c", "danger"),
            ("[!IMPORTANT] Pay attention", "\u2757", "important"),
        ],
    )
    def test_admonition_detection(
        self, text: str, expected_emoji: str, expected_kind: str
    ) -> None:
        ok, emoji, remaining, kind = _parse_admonition(text)
        assert ok
        assert emoji == expected_emoji
        assert kind == expected_kind
        assert remaining  # has content after tag

    def test_admonition_unknown_type(self) -> None:
        ok, _, _, _ = _parse_admonition("[!UNKNOWN] Something")
        assert not ok

    def test_pipeline_admonition_callout(self) -> None:
        md = "> [!WARNING] Be careful with this\n"
        blocks, _ = markdown_to_notion_blocks(md)
        callout_blocks = [b for b in blocks if b.get("type") == "callout"]
        assert len(callout_blocks) >= 1
        callout = callout_blocks[0]["callout"]
        assert callout["icon"]["emoji"] == "\u26a0\ufe0f"
        text = callout["rich_text"][0]["text"]["content"]
        assert "Be careful" in text


class TestEmojiCallout:
    """FR-07: Extended emoji callout mapping."""

    @pytest.mark.parametrize(
        "text,expected_kind",
        [
            ("\u26a0\ufe0f Warning text", "warning"),
            ("\U0001f525 Hot take", "warning"),
            ("\U0001f4a1 Info", "default"),
            ("\U0001f4cc Pinned", "default"),
            ("\u2705 Done", "default"),
            ("\u274c Error", "warning"),
        ],
    )
    def test_emoji_callout(self, text: str, expected_kind: str) -> None:
        ok, emoji, remaining, kind = is_callout(text)
        assert ok
        assert emoji is not None
        assert kind == expected_kind
        assert remaining.strip()

    def test_plain_text_not_callout(self) -> None:
        ok, _, _, _ = is_callout("Just normal text")
        assert not ok


class TestImageBlock:
    """FR-01 P1: Image block support."""

    def test_make_image_block(self) -> None:
        block = _make_image_block("https://example.com/img.png", "Alt text")
        assert block["type"] == "image"
        assert block["image"]["external"]["url"] == "https://example.com/img.png"
        assert block["image"]["caption"][0]["text"]["content"] == "Alt text"

    def test_make_image_block_no_alt(self) -> None:
        block = _make_image_block("https://example.com/img.png")
        assert block["image"]["caption"] == []

    def test_pipeline_image(self) -> None:
        md = "![Architecture](https://example.com/arch.png)\n"
        blocks, _ = markdown_to_notion_blocks(md)
        img_blocks = [b for b in blocks if b.get("type") == "image"]
        assert len(img_blocks) == 1
        assert img_blocks[0]["image"]["external"]["url"] == "https://example.com/arch.png"


class TestNestedList:
    """FR-01 P2: Nested list support."""

    def test_nested_bullets(self) -> None:
        md = "- Parent 1\n  - Child 1a\n  - Child 1b\n- Parent 2\n"
        blocks, _ = markdown_to_notion_blocks(md)
        bullets = [b for b in blocks if b.get("type") == "bulleted_list_item"]
        assert len(bullets) == 2
        children = bullets[0]["bulleted_list_item"].get("children", [])
        assert len(children) == 2

    def test_deeply_nested(self) -> None:
        md = "- Level 1\n  - Level 2\n    - Level 3\n"
        blocks, _ = markdown_to_notion_blocks(md)
        bullets = [b for b in blocks if b.get("type") == "bulleted_list_item"]
        assert len(bullets) == 1
        level2 = bullets[0]["bulleted_list_item"].get("children", [])
        assert len(level2) == 1
        level3 = level2[0]["bulleted_list_item"].get("children", [])
        assert len(level3) == 1

    def test_nested_numbered(self) -> None:
        md = "1. First\n   1. Sub first\n   2. Sub second\n2. Second\n"
        blocks, _ = markdown_to_notion_blocks(md)
        nums = [b for b in blocks if b.get("type") == "numbered_list_item"]
        assert len(nums) == 2
        children = nums[0]["numbered_list_item"].get("children", [])
        assert len(children) == 2

    def test_nested_checkbox(self) -> None:
        md = "- [ ] Parent task\n  - [x] Done subtask\n  - [ ] Pending subtask\n"
        blocks, _ = markdown_to_notion_blocks(md)
        todos = [b for b in blocks if b.get("type") == "to_do"]
        assert len(todos) == 1
        children = todos[0]["to_do"].get("children", [])
        assert len(children) == 2

    def test_flat_list_no_children(self) -> None:
        md = "- item 1\n- item 2\n- item 3\n"
        blocks, _ = markdown_to_notion_blocks(md)
        bullets = [b for b in blocks if b.get("type") == "bulleted_list_item"]
        assert len(bullets) == 3
        for b in bullets:
            assert "children" not in b.get("bulleted_list_item", {})


class TestCalloutChildren:
    """FR-07: Callout blocks with nested children."""

    def test_callout_with_paragraph_children(self) -> None:
        md = "> [!NOTE] Main text\n> \n> Additional details here\n"
        blocks, _ = markdown_to_notion_blocks(md)
        callouts = [b for b in blocks if b.get("type") == "callout"]
        assert len(callouts) >= 1

    def test_existing_round_trip_preserved(self) -> None:
        """Ensure existing test still passes after changes."""
        source = "# Sample\n\n## Tasks\n\n- [ ] first item\n- plain bullet\n\n> \U0001f4a1 callout body\n\n```python\nprint('hi')\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        blocks, pending = markdown_to_notion_blocks(source)
        assert pending == []
        types = [b.get("type") for b in blocks]
        assert "heading_1" in types
        assert "heading_2" in types
        assert "to_do" in types
        assert "callout" in types
        assert "code" in types
        assert "table" in types
