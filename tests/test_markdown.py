from notion_native_toolkit.markdown import (
    markdown_to_notion_blocks,
    notion_blocks_to_markdown,
)


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
