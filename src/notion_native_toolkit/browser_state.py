from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
    domain_contains: str = "notion.so",
) -> str | None:
    for cookie in read_storage_state_cookies(path):
        if cookie.get("name") != name:
            continue
        domain = str(cookie.get("domain") or "")
        if domain_contains in domain:
            value = cookie.get("value")
            return str(value) if value else None
    return None
