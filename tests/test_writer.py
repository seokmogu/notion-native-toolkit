from __future__ import annotations

from typing import Any

from notion_native_toolkit.writer import NotionWriter


class FakeClient:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.appended: list[tuple[list[dict[str, Any]], str | None]] = []

    def fetch_children(self, page_id: str) -> list[dict[str, Any]]:
        assert page_id == "page-id"
        return [
            {"id": "child-page-id", "type": "child_page"},
            {"id": "old-paragraph-id", "type": "paragraph"},
        ]

    def delete_block(self, block_id: str) -> dict[str, str]:
        self.deleted.append(block_id)
        return {"id": block_id}

    def append_children(
        self,
        page_id: str,
        children: list[dict[str, Any]],
        after: str | None = None,
        position: str | None = None,
    ) -> dict[str, str]:
        assert page_id == "page-id"
        assert after is None
        self.appended.append((children, position))
        return {"id": page_id}


def test_replace_page_content_places_new_body_before_preserved_child_pages() -> None:
    client = FakeClient()
    writer = NotionWriter(client)  # type: ignore[arg-type]
    blocks = [{"type": "paragraph", "index": index} for index in range(101)]

    writer.replace_page_content("page-id", blocks, preserve_child_pages=True)

    assert client.deleted == ["old-paragraph-id"]
    assert client.appended == [
        ([blocks[100]], "start"),
        (blocks[:100], "start"),
    ]
