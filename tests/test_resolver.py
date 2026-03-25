"""Tests for resolver.py (SPEC-001 FR-03)."""

from __future__ import annotations

from pathlib import Path

from notion_native_toolkit.mapping import PageMapping
from notion_native_toolkit.resolver import (
    is_image_link,
    is_relative_path,
    resolve_blocks_links,
    resolve_relative_link,
)


class TestIsRelativePath:
    def test_relative_paths(self) -> None:
        assert is_relative_path("./img/a.png")
        assert is_relative_path("../docs/b.md")
        assert is_relative_path("guide.md")

    def test_absolute_urls(self) -> None:
        assert not is_relative_path("https://example.com")
        assert not is_relative_path("http://example.com")
        assert not is_relative_path("mailto:x@y.com")
        assert not is_relative_path("#anchor")
        assert not is_relative_path("/absolute/path")


class TestIsImageLink:
    def test_image_extensions(self) -> None:
        assert is_image_link("photo.png")
        assert is_image_link("./img/arch.jpg")
        assert is_image_link("icon.svg")
        assert is_image_link("photo.webp")

    def test_non_image(self) -> None:
        assert not is_image_link("guide.md")
        assert not is_image_link("data.json")


class TestResolveRelativeLink:
    def test_with_base_url(self) -> None:
        url = resolve_relative_link(
            "./api.md",
            Path("/project/docs/guide.md"),
            Path("/project"),
            base_url="https://github.com/org/repo/raw/main",
        )
        assert url == "https://github.com/org/repo/raw/main/docs/api.md"

    def test_with_mapping(self) -> None:
        m = PageMapping()
        m.set("docs/api.md", "page123", "https://notion.so/api", "API", "")
        url = resolve_relative_link(
            "./api.md",
            Path("/project/docs/guide.md"),
            Path("/project"),
            mapping=m,
        )
        assert url == "https://notion.so/api"

    def test_with_anchor(self) -> None:
        m = PageMapping()
        m.set("docs/api.md", "page123", "https://notion.so/api", "API", "")
        url = resolve_relative_link(
            "./api.md#auth",
            Path("/project/docs/guide.md"),
            Path("/project"),
            mapping=m,
        )
        assert url == "https://notion.so/api#auth"

    def test_pending_links(self) -> None:
        pending: list[dict[str, str]] = []
        resolve_relative_link(
            "./unknown.md",
            Path("/project/docs/guide.md"),
            Path("/project"),
            pending_links=pending,
        )
        assert len(pending) == 1
        assert pending[0]["target"] == "docs/unknown.md"

    def test_absolute_url_passthrough(self) -> None:
        url = resolve_relative_link(
            "https://example.com",
            Path("/project/docs/guide.md"),
            Path("/project"),
        )
        assert url == "https://example.com"

    def test_mapping_takes_priority_over_base_url(self) -> None:
        m = PageMapping()
        m.set("docs/api.md", "page123", "https://notion.so/api", "API", "")
        url = resolve_relative_link(
            "./api.md",
            Path("/project/docs/guide.md"),
            Path("/project"),
            mapping=m,
            base_url="https://github.com/raw/main",
        )
        assert url == "https://notion.so/api"


class TestResolveBlocksLinks:
    def test_resolve_text_link(self) -> None:
        m = PageMapping()
        m.set("docs/api.md", "p1", "https://notion.so/api", "API", "")
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "See API",
                                "link": {"url": "./api.md"},
                            },
                        }
                    ]
                },
            }
        ]
        resolve_blocks_links(
            blocks, Path("/project/docs/guide.md"), Path("/project"), mapping=m
        )
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["link"]["url"] == "https://notion.so/api"

    def test_resolve_image_block(self) -> None:
        blocks = [
            {
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": "./img/arch.png"},
                },
            }
        ]
        resolve_blocks_links(
            blocks,
            Path("/project/docs/guide.md"),
            Path("/project"),
            base_url="https://raw.github.com/org/repo/main",
        )
        assert "raw.github.com" in blocks[0]["image"]["external"]["url"]
