from notion_native_toolkit.markdown import (
    markdown_to_notion_blocks,
    notion_blocks_to_markdown,
)
from notion_native_toolkit.cli import _strip_matching_leading_h1


def test_markdown_round_trip_keeps_key_constructs() -> None:
    source = """# Sample\n\n## Tasks\n\n- [ ] first item\n- plain bullet\n\n> 💡 callout body\n\n```python\nprint('hi')\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"""
    blocks, pending_links = markdown_to_notion_blocks(source)
    assert pending_links == []
    output = notion_blocks_to_markdown(blocks, title="Sample")
    assert "# Sample" in output
    assert "## Tasks" in output
    assert "- [ ] first item" in output
    assert "> 💡 callout body" in output
    assert "```python" in output
    assert "| A | B |" in output


def test_table_export_skips_imported_separator_rows() -> None:
    blocks = [
        {
            "type": "table",
            "table": {
                "children": [
                    {
                        "type": "table_row",
                        "table_row": {
                            "cells": [
                                [{"type": "text", "text": {"content": "A"}}],
                                [{"type": "text", "text": {"content": "B"}}],
                            ]
                        },
                    },
                    {
                        "type": "table_row",
                        "table_row": {
                            "cells": [
                                [{"type": "text", "text": {"content": "---"}}],
                                [{"type": "text", "text": {"content": "---:"}}],
                            ]
                        },
                    },
                    {
                        "type": "table_row",
                        "table_row": {
                            "cells": [
                                [{"type": "text", "text": {"content": "1"}}],
                                [{"type": "text", "text": {"content": "2"}}],
                            ]
                        },
                    },
                ]
            },
        }
    ]

    output = notion_blocks_to_markdown(blocks)

    assert output.strip().splitlines() == ["| A | B |", "|---|---|", "| 1 | 2 |"]
    assert "| --- | ---: |" not in output


def test_strip_matching_leading_h1_keeps_body_only() -> None:
    source = "# Title\n\n## Section\n\nBody"

    assert _strip_matching_leading_h1(source, "Title") == "## Section\n\nBody"
    assert _strip_matching_leading_h1(source, "Other") == source


def test_explicit_empty_blocks_stay_before_h2_and_h3() -> None:
    source = (
        "Intro\n\n"
        "<empty-block/>\n\n"
        "## H2\n"
        "H2 body\n\n"
        "<empty-block/>\n\n"
        "### H3\n"
        "H3 body\n"
    )

    blocks, pending_links = markdown_to_notion_blocks(source)

    assert pending_links == []
    assert [block["type"] for block in blocks] == [
        "paragraph",
        "paragraph",
        "heading_2",
        "paragraph",
        "paragraph",
        "heading_3",
        "paragraph",
    ]
    assert blocks[1]["paragraph"]["rich_text"] == []
    assert blocks[4]["paragraph"]["rich_text"] == []
    assert blocks[2]["heading_2"]["rich_text"][0]["text"]["content"] == "H2"
    assert blocks[5]["heading_3"]["rich_text"][0]["text"]["content"] == "H3"
    assert "<empty-block/>\n\n## H2\n\nH2 body" in notion_blocks_to_markdown(blocks)
    assert "<empty-block/>\n\n### H3\n\nH3 body" in notion_blocks_to_markdown(blocks)


def test_markdown_conversion_does_not_add_spacing_after_blocks() -> None:
    source = (
        "# Title\n\n"
        "## H2\n\n"
        "H2 body\n\n"
        "### H3\n\n"
        "H3 body\n\n"
        "> 💡 Callout\n\n"
        "```text\ncode\n```\n"
    )

    blocks, _ = markdown_to_notion_blocks(source)

    assert [block["type"] for block in blocks] == [
        "heading_1",
        "heading_2",
        "paragraph",
        "heading_3",
        "paragraph",
        "callout",
        "code",
    ]
    assert all(
        block["type"] != "paragraph" or block["paragraph"]["rich_text"]
        for block in blocks
    )


def test_inline_empty_block_text_remains_literal() -> None:
    blocks, pending_links = markdown_to_notion_blocks(
        "Explain <empty-block/> here.\n"
    )

    assert pending_links == []
    assert [block["type"] for block in blocks] == ["paragraph"]
    assert (
        blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
        == "Explain <empty-block/> here."
    )


def test_multi_paragraph_quote_preserves_every_paragraph() -> None:
    source = (
        "> **Conclusion:** first\n"
        ">\n"
        "> **First check:** second\n"
        ">\n"
        "> **Hold:** third\n"
    )

    blocks, pending_links = markdown_to_notion_blocks(source)

    assert pending_links == []
    assert len(blocks) == 1
    quote = blocks[0]["quote"]
    assert len(quote["children"]) == 2
    assert quote["children"][0]["paragraph"]["rich_text"][0]["text"]["content"] == "First check:"
    assert quote["children"][1]["paragraph"]["rich_text"][0]["text"]["content"] == "Hold:"
    assert notion_blocks_to_markdown(blocks) == (
        "> **Conclusion:** first\n"
        ">\n"
        "> **First check:** second\n"
        ">\n"
        "> **Hold:** third\n"
    )
