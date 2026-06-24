from __future__ import annotations

import base64
import html
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx


GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
NOTION_CODE_PATTERN = re.compile(r"\b(\d{6})\b")
NOTION_SENDER_PATTERNS = ("notion", "makenotion")
GMAIL_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def configured_gmail_token_file(value: str | None = None) -> Path | None:
    raw = value or os.getenv("NOTION_GMAIL_TOKEN_FILE") or os.getenv("GMAIL_TOKEN_FILE")
    if not raw:
        return None
    return Path(raw).expanduser()


def configured_gmail_user(value: str | None = None) -> str:
    return value or os.getenv("NOTION_GMAIL_USER") or os.getenv("GMAIL_USER") or "me"


def get_gmail_access_token(token_file: Path | None = None) -> str | None:
    token_path = token_file or configured_gmail_token_file()
    token_data = _gmail_token_data(token_path)
    access_token = str(
        os.getenv("NOTION_GMAIL_ACCESS_TOKEN")
        or os.getenv("GMAIL_ACCESS_TOKEN")
        or token_data.get("access_token")
        or token_data.get("token")
        or ""
    )
    if access_token and not _gmail_token_expired(token_data):
        return access_token

    refresh_token = str(
        os.getenv("NOTION_GMAIL_REFRESH_TOKEN")
        or os.getenv("GMAIL_REFRESH_TOKEN")
        or token_data.get("refresh_token")
        or ""
    )
    client_id = str(
        os.getenv("NOTION_GMAIL_CLIENT_ID")
        or os.getenv("GMAIL_CLIENT_ID")
        or token_data.get("client_id")
        or ""
    )
    client_secret = str(
        os.getenv("NOTION_GMAIL_CLIENT_SECRET")
        or os.getenv("GMAIL_CLIENT_SECRET")
        or token_data.get("client_secret")
        or ""
    )
    if refresh_token and client_id and client_secret:
        refreshed = _refresh_gmail_access_token(client_id, client_secret, refresh_token)
        access_token = str(refreshed.get("access_token") or "")
        if not access_token:
            return None
        if token_path is not None:
            token_data.update(refreshed)
            token_data["token"] = access_token
            token_data["access_token"] = access_token
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(
                json.dumps(token_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return access_token
    return access_token or None


def fetch_notion_login_code_from_gmail(
    access_token: str,
    since: datetime,
    *,
    gmail_user: str = "me",
) -> str | None:
    with _gmail_client(access_token) as client:
        for message in _iter_notion_login_messages(
            client,
            since,
            gmail_user=gmail_user,
        ):
            text = _notion_message_text(message)
            match = NOTION_CODE_PATTERN.search(text)
            if match:
                return match.group(1)
    return None


def fetch_notion_login_link_from_gmail(
    access_token: str,
    since: datetime,
    *,
    gmail_user: str = "me",
) -> str | None:
    with _gmail_client(access_token) as client:
        for message in _iter_notion_login_messages(
            client,
            since,
            gmail_user=gmail_user,
        ):
            link = _notion_magic_link(message)
            if link:
                return link
    return None


def _iter_notion_login_messages(
    client: httpx.Client,
    since: datetime,
    *,
    gmail_user: str,
) -> list[dict[str, Any]]:
    after = since.astimezone(UTC).strftime("%Y/%m/%d")
    query = f"(from:notion OR from:makenotion OR subject:Notion) after:{after}"
    response = client.get(
        f"{GMAIL_BASE}/users/{quote(gmail_user, safe='')}/messages",
        params={"q": query, "maxResults": 20},
    )
    if response.status_code != 200:
        return []
    messages: list[dict[str, Any]] = []
    for item in response.json().get("messages", []):
        if not isinstance(item, dict):
            continue
        message_id = str(item.get("id") or "")
        if not message_id:
            continue
        message = _get_gmail_message(client, message_id, gmail_user=gmail_user)
        if not _gmail_message_matches(message, since):
            continue
        messages.append(message)
    return messages


def _gmail_token_data(token_file: Path | None) -> dict[str, Any]:
    if token_file is None or not token_file.exists():
        return {}
    payload = json.loads(token_file.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _gmail_token_expired(token_data: dict[str, Any]) -> bool:
    expiry = str(token_data.get("expiry") or token_data.get("expires_at") or "")
    if not expiry:
        return False
    try:
        parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.astimezone(UTC) <= datetime.now(UTC) + timedelta(seconds=60)


def _refresh_gmail_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any]:
    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=GMAIL_TIMEOUT,
    )
    if response.status_code != 200:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, int):
        payload["expiry"] = (
            datetime.now(UTC) + timedelta(seconds=max(expires_in - 60, 0))
        ).isoformat()
    return payload


def _gmail_client(access_token: str) -> httpx.Client:
    return httpx.Client(
        headers=_gmail_api_headers(access_token),
        timeout=GMAIL_TIMEOUT,
    )


def _get_gmail_message(
    client: httpx.Client,
    message_id: str,
    *,
    gmail_user: str,
) -> dict[str, Any]:
    response = client.get(
        f"{GMAIL_BASE}/users/{quote(gmail_user, safe='')}/messages/{message_id}",
        params={"format": "full"},
    )
    if response.status_code != 200:
        return {}
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _gmail_api_headers(access_token: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    quota_project = os.getenv("NOTION_GMAIL_QUOTA_PROJECT") or os.getenv(
        "GMAIL_QUOTA_PROJECT", ""
    )
    if quota_project:
        headers["x-goog-user-project"] = quota_project
    return headers


def _gmail_message_matches(message: dict[str, Any], since: datetime) -> bool:
    internal_date = str(message.get("internalDate") or "")
    if internal_date:
        try:
            received_at = datetime.fromtimestamp(int(internal_date) / 1000, UTC)
        except ValueError:
            received_at = since
        if received_at < since:
            return False

    headers = _gmail_headers(message.get("payload") or {})
    sender = headers.get("from", "").casefold()
    subject = headers.get("subject", "").casefold()
    return any(pattern in sender or pattern in subject for pattern in NOTION_SENDER_PATTERNS)


def _notion_message_text(message: dict[str, Any]) -> str:
    headers = _gmail_headers(message.get("payload") or {})
    return " ".join(
        [
            headers.get("subject", ""),
            str(message.get("snippet") or ""),
            html.unescape(_gmail_message_text(message.get("payload") or {})),
        ]
    )


def _notion_magic_link(message: dict[str, Any]) -> str | None:
    text = _notion_message_text(message)
    candidates = [
        *_extract_href_links(text),
        *re.findall(r"https?://[^\s\"'<>]+", text),
    ]
    for raw_link in candidates:
        link = html.unescape(raw_link).replace("&amp;", "&")
        parsed = urlparse(link)
        if "notion." not in parsed.netloc:
            continue
        lowered = f"{parsed.path}?{parsed.query}".casefold()
        if any(marker in lowered for marker in ("login", "auth", "magic")):
            return link
    return None


def _extract_href_links(text: str) -> list[str]:
    return re.findall(r"""href=["']([^"']+)["']""", text)


def _gmail_headers(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    headers = payload.get("headers") or []
    return {
        str(header.get("name") or "").casefold(): str(header.get("value") or "")
        for header in headers
        if isinstance(header, dict)
    }


def _gmail_message_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    chunks: list[str] = []
    body = payload.get("body") or {}
    if isinstance(body, dict) and body.get("data"):
        chunks.append(_decode_gmail_body(str(body["data"])))
    for part in payload.get("parts") or []:
        chunks.append(_gmail_message_text(part))
    return "\n".join(chunk for chunk in chunks if chunk)


def _decode_gmail_body(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}").decode(
        "utf-8",
        errors="replace",
    )
