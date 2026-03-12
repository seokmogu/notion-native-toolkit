from __future__ import annotations

import os
import time
from typing import Any

import httpx


NOTION_VERSION = "2022-06-28"


class NotionApiClient:
    def __init__(self, token: str, rate_limit: float = 0.35, timeout: float = 60.0):
        self.token = token
        self.rate_limit = rate_limit
        self.timeout = timeout
        verify_ssl = not bool(os.getenv("NO_SSL_VERIFY"))
        self.base_url = "https://api.notion.com/v1/"
        self.session = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            verify=verify_ssl,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )

    def _request_once(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response | None:
        time.sleep(self.rate_limit)
        try:
            return self.session.request(method, endpoint, json=data)
        except httpx.TimeoutException:
            return None
        except httpx.HTTPError:
            return None

    def call(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        max_retries = 3
        backoffs = [1.5, 3.0, 6.0]
        for attempt in range(max_retries + 1):
            response = self._request_once(method, endpoint, data)
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
        return self.call("GET", f"pages/{page_id}")

    def fetch_block(self, block_id: str) -> dict[str, Any] | None:
        return self.call("GET", f"blocks/{block_id}")

    def fetch_children(self, block_id: str) -> list[dict[str, Any]] | None:
        children: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            endpoint = f"blocks/{block_id}/children?page_size=100"
            if cursor:
                endpoint += f"&start_cursor={cursor}"
            response = self.call("GET", endpoint)
            if response is None:
                return None
            results = response.get("results")
            if not isinstance(results, list):
                return None
            for item in results:
                if not isinstance(item, dict):
                    return None
                children.append(item)
            if not response.get("has_more"):
                return children
            next_cursor = response.get("next_cursor")
            if next_cursor is None:
                return children
            if not isinstance(next_cursor, str):
                return None
            cursor = next_cursor

    def fetch_database(self, database_id: str) -> dict[str, Any] | None:
        return self.call("GET", f"databases/{database_id}")

    def query_database(
        self,
        database_id: str,
        payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        base_payload = payload.copy() if payload else {}
        base_payload["page_size"] = 100
        while True:
            query_payload = base_payload.copy()
            if cursor:
                query_payload["start_cursor"] = cursor
            response = self.call(
                "POST", f"databases/{database_id}/query", query_payload
            )
            if response is None:
                return None
            results = response.get("results")
            if not isinstance(results, list):
                return None
            for item in results:
                if not isinstance(item, dict):
                    return None
                rows.append(item)
            if not response.get("has_more"):
                return rows
            next_cursor = response.get("next_cursor")
            if next_cursor is None:
                return rows
            if not isinstance(next_cursor, str):
                return None
            cursor = next_cursor

    def create_page(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.call("POST", "pages", payload)

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
        return self.call("POST", "pages", payload)

    def create_database(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.call("POST", "databases", payload)

    def update_database(
        self, database_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self.call("PATCH", f"databases/{database_id}", payload)

    def append_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
        after: str | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"children": children}
        if after is not None:
            payload["after"] = after
        return self.call("PATCH", f"blocks/{block_id}/children", payload)

    def update_page(
        self, page_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self.call("PATCH", f"pages/{page_id}", payload)

    def retrieve_markdown(self, page_id: str) -> str | None:
        payload = self.call("GET", f"pages/{page_id}/markdown")
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
        return self.call("PATCH", f"pages/{page_id}/markdown", payload)

    def delete_block(self, block_id: str) -> dict[str, Any] | None:
        return self.call("DELETE", f"blocks/{block_id}")

    def archive_block(self, block_id: str) -> dict[str, Any] | None:
        return self.call("PATCH", f"blocks/{block_id}", {"archived": True})

    def list_users(self) -> list[dict[str, Any]] | None:
        users: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            endpoint = "users?page_size=100"
            if cursor:
                endpoint += f"&start_cursor={cursor}"
            response = self.call("GET", endpoint)
            if response is None:
                return None
            results = response.get("results")
            if not isinstance(results, list):
                return None
            for item in results:
                if not isinstance(item, dict):
                    return None
                users.append(item)
            if not response.get("has_more"):
                return users
            next_cursor = response.get("next_cursor")
            if not isinstance(next_cursor, str):
                return users
            cursor = next_cursor

    def create_file_upload(self, filename: str) -> dict[str, Any] | None:
        return self.call(
            "POST", "file_uploads", {"mode": "single_part", "filename": filename}
        )

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
                        "Notion-Version": NOTION_VERSION,
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
