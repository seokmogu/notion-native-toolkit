from __future__ import annotations

import os
import time
from typing import Any, Literal

import httpx


NOTION_VERSION = "2022-06-28"
NOTION_LATEST_VERSION = "2026-03-11"


class NotionApiClient:
    def __init__(
        self,
        token: str,
        rate_limit: float = 0.0,
        timeout: float = 60.0,
        notion_version: str | None = None,
    ):
        # rate_limit kept for backward-compat but defaults to 0.
        # Throttling is now reactive: 429/409 trigger retry with Retry-After
        # header (see `call` below). No need for pre-call sleep.
        self.token = token
        self.rate_limit = rate_limit
        self.timeout = timeout
        configured_version = notion_version or os.getenv("NOTION_API_VERSION")
        self.notion_version = configured_version or NOTION_VERSION
        self.latest_notion_version = configured_version or NOTION_LATEST_VERSION
        verify_ssl = not bool(os.getenv("NO_SSL_VERIFY"))
        self.base_url = "https://api.notion.com/v1/"
        self.session = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            verify=verify_ssl,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": self.notion_version,
                "Content-Type": "application/json",
            },
        )

    def _request_once(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        notion_version: str | None = None,
    ) -> httpx.Response | None:
        if self.rate_limit > 0:
            time.sleep(self.rate_limit)
        headers = None
        if notion_version is not None:
            headers = {"Notion-Version": notion_version}
        try:
            return self.session.request(method, endpoint, json=data, headers=headers)
        except httpx.TimeoutException:
            return None
        except httpx.HTTPError:
            return None

    def call(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        notion_version: str | None = None,
    ) -> dict[str, Any] | None:
        max_retries = 3
        backoffs = [1.5, 3.0, 6.0]
        for attempt in range(max_retries + 1):
            response = self._request_once(
                method,
                endpoint,
                data,
                notion_version=notion_version,
            )
            if response is None:
                if attempt < max_retries:
                    time.sleep(backoffs[attempt])
                    continue
                return None
            if response.status_code in {429, 409} and attempt < max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = backoffs[attempt]
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = backoffs[attempt]
                time.sleep(delay)
                continue
            if response.status_code >= 400:
                return None
            payload = response.json()
            if not isinstance(payload, dict):
                return None
            return payload
        return None

    def fetch_page(self, page_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"pages/{page_id}")

    def update_page_title(self, page_id: str, title: str) -> dict[str, Any] | None:
        payload = {
            "properties": {
                "title": {
                    "title": [
                        {"type": "text", "text": {"content": title}},
                    ]
                }
            }
        }
        return self.update_page(page_id, payload)

    def fetch_block(self, block_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"blocks/{block_id}")

    def fetch_children(self, block_id: str) -> list[dict[str, Any]] | None:
        return self._collect_paginated_get(
            f"blocks/{block_id}/children",
            notion_version=self.latest_notion_version,
        )

    def update_block(
        self,
        block_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._call_latest("PATCH", f"blocks/{block_id}", payload)

    def query_meeting_notes(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_latest("POST", "blocks/meeting_notes/query", payload)

    def fetch_database(self, database_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"databases/{database_id}")

    def query_database(
        self,
        database_id: str,
        payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        return self._collect_paginated_post(
            f"databases/{database_id}/query",
            payload,
        )

    def fetch_data_source(self, data_source_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"data_sources/{data_source_id}")

    def query_data_source(
        self,
        data_source_id: str,
        payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        return self._collect_paginated_post(
            f"data_sources/{data_source_id}/query",
            payload,
            notion_version=self.latest_notion_version,
        )

    def create_data_source(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_latest("POST", "data_sources", payload)

    def update_data_source(
        self, data_source_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self._call_latest("PATCH", f"data_sources/{data_source_id}", payload)

    def list_data_source_templates(
        self, data_source_id: str
    ) -> list[dict[str, Any]] | None:
        return self._collect_paginated_get(
            f"data_sources/{data_source_id}/templates",
            notion_version=self.latest_notion_version,
        )

    def list_comments(self, block_id: str) -> list[dict[str, Any]] | None:
        endpoint = self._append_query("comments", "block_id", block_id)
        return self._collect_paginated_get(
            endpoint,
            notion_version=self.latest_notion_version,
        )

    def fetch_comment(self, comment_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"comments/{comment_id}")

    def create_comment(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_latest("POST", "comments", payload)

    def create_comment_markdown(
        self,
        markdown: str,
        *,
        parent_page_id: str | None = None,
        parent_block_id: str | None = None,
        discussion_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        display_name: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = self._comment_location_payload(
            parent_page_id=parent_page_id,
            parent_block_id=parent_block_id,
            discussion_id=discussion_id,
        )
        payload["markdown"] = markdown
        if attachments is not None:
            payload["attachments"] = attachments
        if display_name is not None:
            payload["display_name"] = display_name
        return self.create_comment(payload)

    def update_comment(
        self,
        comment_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._call_latest("PATCH", f"comments/{comment_id}", payload)

    def update_comment_markdown(
        self,
        comment_id: str,
        markdown: str,
    ) -> dict[str, Any] | None:
        return self.update_comment(comment_id, {"markdown": markdown})

    def delete_comment(self, comment_id: str) -> dict[str, Any] | None:
        return self._call_latest("DELETE", f"comments/{comment_id}")

    def search(
        self,
        payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        return self._collect_paginated_post(
            "search",
            payload,
            notion_version=self.latest_notion_version,
        )

    def list_custom_emojis(self) -> list[dict[str, Any]] | None:
        return self._collect_paginated_get(
            "custom_emojis",
            notion_version=self.latest_notion_version,
        )

    def fetch_user(self, user_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"users/{user_id}")

    def fetch_bot_user(self) -> dict[str, Any] | None:
        return self._call_latest("GET", "users/me")

    def fetch_page_property(
        self,
        page_id: str,
        property_id: str,
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        endpoint = f"pages/{page_id}/properties/{property_id}"
        response = self._call_latest("GET", endpoint)
        if response is None:
            return None
        if response.get("object") == "list":
            return self._collect_paginated_get(
                endpoint,
                notion_version=self.latest_notion_version,
            )
        return response

    def list_views(
        self,
        *,
        database_id: str | None = None,
        data_source_id: str | None = None,
    ) -> list[dict[str, Any]] | None:
        if database_id is None and data_source_id is None:
            raise ValueError("Pass database_id, data_source_id, or both")
        endpoint = "views"
        if database_id is not None:
            endpoint = self._append_query(endpoint, "database_id", database_id)
        if data_source_id is not None:
            endpoint = self._append_query(endpoint, "data_source_id", data_source_id)
        return self._collect_paginated_get(
            endpoint,
            notion_version=self.latest_notion_version,
        )

    def create_view(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_latest("POST", "views", payload)

    def fetch_view(self, view_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"views/{view_id}")

    def update_view(
        self,
        view_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._call_latest("PATCH", f"views/{view_id}", payload)

    def delete_view(self, view_id: str) -> dict[str, Any] | None:
        return self._call_latest("DELETE", f"views/{view_id}")

    def create_view_query(
        self,
        view_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._call_latest("POST", f"views/{view_id}/queries", payload)

    def fetch_view_query_results(
        self,
        view_id: str,
        query_id: str,
    ) -> list[dict[str, Any]] | None:
        return self._collect_paginated_get(
            f"views/{view_id}/queries/{query_id}",
            notion_version=self.latest_notion_version,
        )

    def delete_view_query(
        self,
        view_id: str,
        query_id: str,
    ) -> dict[str, Any] | None:
        return self._call_latest("DELETE", f"views/{view_id}/queries/{query_id}")

    def create_page(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_latest("POST", "pages", payload)

    def create_page_markdown(
        self,
        parent_page_id: str,
        title: str,
        markdown: str,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [
                        {"type": "text", "text": {"content": title}},
                    ]
                }
            },
            "markdown": markdown,
        }
        return self._call_latest("POST", "pages", payload)

    def create_database(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_latest("POST", "databases", payload)

    def update_database(
        self, database_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self._call_latest("PATCH", f"databases/{database_id}", payload)

    def append_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
        after: str | None = None,
        position: Literal["start", "end"] | None = None,
    ) -> dict[str, Any] | None:
        if after is not None and position is not None:
            raise ValueError("Pass either after or position, not both")
        payload: dict[str, Any] = {"children": children}
        if after is not None:
            payload["position"] = {
                "type": "after_block",
                "after_block": {"id": after},
            }
        elif position is not None:
            payload["position"] = {"type": position}
        return self._call_latest("PATCH", f"blocks/{block_id}/children", payload)

    def update_page(
        self, page_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self._call_latest("PATCH", f"pages/{page_id}", payload)

    def move_page(
        self,
        page_id: str,
        *,
        parent_page_id: str | None = None,
        parent_data_source_id: str | None = None,
    ) -> dict[str, Any] | None:
        if (parent_page_id is None) == (parent_data_source_id is None):
            raise ValueError(
                "Pass exactly one of parent_page_id or parent_data_source_id"
            )
        if parent_page_id is not None:
            parent = {"type": "page_id", "page_id": parent_page_id}
        else:
            parent = {
                "type": "data_source_id",
                "data_source_id": parent_data_source_id,
            }
        return self._call_latest("POST", f"pages/{page_id}/move", {"parent": parent})

    def retrieve_markdown(self, page_id: str) -> str | None:
        payload = self._call_latest("GET", f"pages/{page_id}/markdown")
        if payload is None:
            return None
        markdown = payload.get("markdown")
        if isinstance(markdown, str):
            return markdown
        return None

    def replace_markdown(self, page_id: str, markdown: str) -> dict[str, Any] | None:
        payload = {
            "type": "replace_content",
            "replace_content": {"new_str": markdown},
        }
        return self._call_latest("PATCH", f"pages/{page_id}/markdown", payload)

    def delete_block(self, block_id: str) -> dict[str, Any] | None:
        return self._call_latest("DELETE", f"blocks/{block_id}")

    def archive_block(self, block_id: str) -> dict[str, Any] | None:
        return self.call("PATCH", f"blocks/{block_id}", {"archived": True})

    def list_users(self) -> list[dict[str, Any]] | None:
        return self._collect_paginated_get(
            "users",
            notion_version=self.latest_notion_version,
        )

    def _collect_paginated_get(
        self,
        endpoint: str,
        page_size: int = 100,
        notion_version: str | None = None,
    ) -> list[dict[str, Any]] | None:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page_endpoint = self._append_query(endpoint, "page_size", str(page_size))
            if cursor:
                page_endpoint = self._append_query(
                    page_endpoint, "start_cursor", cursor
                )
            response = self.call("GET", page_endpoint, notion_version=notion_version)
            if response is None:
                return None
            batch = _read_results(response)
            if batch is None:
                return None
            rows.extend(batch)
            if not response.get("has_more"):
                return rows
            next_cursor = response.get("next_cursor")
            if next_cursor is None:
                return rows
            if not isinstance(next_cursor, str):
                return None
            cursor = next_cursor

    def _collect_paginated_post(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        page_size: int = 100,
        notion_version: str | None = None,
    ) -> list[dict[str, Any]] | None:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        base_payload = payload.copy() if payload else {}
        base_payload.setdefault("page_size", page_size)
        while True:
            query_payload = base_payload.copy()
            if cursor:
                query_payload["start_cursor"] = cursor
            response = self.call(
                "POST",
                endpoint,
                query_payload,
                notion_version=notion_version,
            )
            if response is None:
                return None
            batch = _read_results(response)
            if batch is None:
                return None
            rows.extend(batch)
            if not response.get("has_more"):
                return rows
            next_cursor = response.get("next_cursor")
            if next_cursor is None:
                return rows
            if not isinstance(next_cursor, str):
                return None
            cursor = next_cursor

    @staticmethod
    def _append_query(endpoint: str, key: str, value: str) -> str:
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{key}={value}"

    def create_file_upload(self, filename: str) -> dict[str, Any] | None:
        return self._call_latest(
            "POST", "file_uploads", {"mode": "single_part", "filename": filename}
        )

    def list_file_uploads(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]] | None:
        endpoint = "file_uploads"
        if status is not None:
            endpoint = self._append_query(endpoint, "status", status)
        return self._collect_paginated_get(
            endpoint,
            notion_version=self.latest_notion_version,
        )

    def fetch_file_upload(self, upload_id: str) -> dict[str, Any] | None:
        return self._call_latest("GET", f"file_uploads/{upload_id}")

    def complete_file_upload(self, upload_id: str) -> dict[str, Any] | None:
        return self._call_latest("POST", f"file_uploads/{upload_id}/complete")

    def send_file_upload(
        self, upload_id: str, filename: str, content: bytes
    ) -> dict[str, Any] | None:
        verify_ssl = not bool(os.getenv("NO_SSL_VERIFY"))
        with httpx.Client(timeout=self.timeout, verify=verify_ssl) as session:
            try:
                response = session.post(
                    f"{self.base_url}file_uploads/{upload_id}/send",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Notion-Version": self.latest_notion_version,
                    },
                    files={"file": (filename, content)},
                )
                if response.status_code >= 400:
                    return None
                payload = response.json()
            except httpx.HTTPError:
                return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _call_latest(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.call(
            method,
            endpoint,
            data,
            notion_version=self.latest_notion_version,
        )

    @staticmethod
    def _comment_location_payload(
        *,
        parent_page_id: str | None = None,
        parent_block_id: str | None = None,
        discussion_id: str | None = None,
    ) -> dict[str, Any]:
        provided = [
            parent_page_id is not None,
            parent_block_id is not None,
            discussion_id is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "Pass exactly one of parent_page_id, parent_block_id, or discussion_id"
            )
        if parent_page_id is not None:
            return {"parent": {"type": "page_id", "page_id": parent_page_id}}
        if parent_block_id is not None:
            return {"parent": {"type": "block_id", "block_id": parent_block_id}}
        return {"discussion_id": discussion_id}


def _read_results(response: dict[str, Any]) -> list[dict[str, Any]] | None:
    results = response.get("results")
    if not isinstance(results, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            return None
        rows.append(item)
    return rows
