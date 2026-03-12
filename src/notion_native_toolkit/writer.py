from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import NotionApiClient


BLOCKS_PER_REQUEST = 100
BLOCKS_INITIAL_CREATE = 30


@dataclass(slots=True)
class CreatedPage:
    page_id: str
    url: str
    title: str


class NotionWriter:
    def __init__(self, client: NotionApiClient):
        self.client = client

    def create_page(
        self,
        parent_page_id: str,
        title: str,
        blocks: list[dict[str, Any]],
        icon: str | dict[str, Any] | None = None,
    ) -> CreatedPage:
        initial_blocks = blocks[:BLOCKS_INITIAL_CREATE]
        remaining_blocks = blocks[BLOCKS_INITIAL_CREATE:]
        properties: dict[str, Any] = {
            "title": {
                "title": [
                    {"type": "text", "text": {"content": title}},
                ]
            }
        }
        payload: dict[str, Any] = {
            "parent": {"page_id": parent_page_id},
            "properties": properties,
            "children": initial_blocks,
        }
        if icon is not None:
            if isinstance(icon, dict):
                payload["icon"] = icon
            else:
                payload["icon"] = {"emoji": icon}
        page = self.client.create_page(payload)
        if page is None:
            payload["children"] = []
            page = self.client.create_page(payload)
            remaining_blocks = blocks
        if page is None:
            raise RuntimeError("Failed to create page in Notion")
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise RuntimeError("Notion did not return a page id")
        if remaining_blocks:
            self.append_blocks(page_id, remaining_blocks)
        url_value = page.get("url")
        url = url_value if isinstance(url_value, str) else ""
        return CreatedPage(page_id=page_id, url=url, title=title)

    def append_blocks(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        for index in range(0, len(blocks), BLOCKS_PER_REQUEST):
            chunk = blocks[index : index + BLOCKS_PER_REQUEST]
            response = self.client.append_children(page_id, chunk)
            if response is not None:
                continue
            for block in chunk:
                single = self.client.append_children(page_id, [block])
                if single is None:
                    fallback = {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "[Notion upload skipped unsupported block]"
                                    },
                                }
                            ]
                        },
                    }
                    self.client.append_children(page_id, [fallback])

    def clear_page_content(
        self, page_id: str, preserve_child_pages: bool = True
    ) -> int:
        children = self.client.fetch_children(page_id) or []
        deleted = 0
        for block in children:
            block_id = block.get("id")
            block_type = block.get("type")
            if not isinstance(block_id, str):
                continue
            if preserve_child_pages and block_type == "child_page":
                continue
            if self.client.delete_block(block_id) is not None:
                deleted += 1
        return deleted

    def replace_page_content(
        self,
        page_id: str,
        blocks: list[dict[str, Any]],
        preserve_child_pages: bool = True,
    ) -> None:
        self.clear_page_content(page_id, preserve_child_pages=preserve_child_pages)
        self.append_blocks(page_id, blocks)

    def verify_access(self, page_id: str) -> bool:
        return self.client.fetch_page(page_id) is not None

    def upload_image(self, image_bytes: bytes, filename: str) -> str | None:
        upload = self.client.create_file_upload(filename)
        if upload is None:
            return None
        upload_id = upload.get("id")
        if not isinstance(upload_id, str) or not upload_id:
            return None
        result = self.client.send_file_upload(upload_id, filename, image_bytes)
        if result is None:
            return None
        return upload_id
