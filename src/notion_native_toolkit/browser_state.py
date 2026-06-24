from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


NOTION_SESSION_DOMAINS = ("notion.com", "notion.so")


def read_storage_state_cookies(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    state_path = Path(path).expanduser()
    if not state_path.exists():
        return []
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        return []
    return [cookie for cookie in cookies if isinstance(cookie, dict)]


def find_storage_state_cookie(
    path: str | Path | None,
    name: str,
    *,
    domain_contains: str | tuple[str, ...] = NOTION_SESSION_DOMAINS,
) -> str | None:
    candidates: list[dict[str, Any]] = []
    domains = (domain_contains,) if isinstance(domain_contains, str) else domain_contains
    for cookie in read_storage_state_cookies(path):
        if cookie.get("name") != name:
            continue
        domain = str(cookie.get("domain") or "")
        if any(item in domain for item in domains):
            candidates.append(cookie)
    for cookie in sorted(candidates, key=_cookie_priority):
        value = cookie.get("value")
        if value:
            return str(value)
    return None


def _cookie_priority(cookie: dict[str, Any]) -> tuple[int, int]:
    domain = str(cookie.get("domain") or "")
    expires = cookie.get("expires")
    if not isinstance(expires, int | float):
        expires = -1
    expired = expires != -1 and expires <= time.time()
    return (
        1 if expired else 0,
        0 if "notion.com" in domain else 1,
    )
