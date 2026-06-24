from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from notion_native_toolkit import gmail


def _gmail_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_get_gmail_access_token_refreshes_token_file(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "gmail_token.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "expired",
                "refresh_token": "refresh",
                "client_id": "client",
                "client_secret": "secret",
                "expiry": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    def fake_post(
        url: str,
        *,
        data: dict[str, str],
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        assert url == gmail.GOOGLE_TOKEN_URL
        assert data["grant_type"] == "refresh_token"
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})

    monkeypatch.delenv("NOTION_GMAIL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GMAIL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_GMAIL_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)
    monkeypatch.setattr(gmail.httpx, "post", fake_post)

    assert gmail.get_gmail_access_token(token_file) == "fresh"
    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["access_token"] == "fresh"
    assert saved["token"] == "fresh"


def test_fetch_notion_login_code_from_gmail_extracts_recent_code(monkeypatch) -> None:
    since = datetime(2026, 6, 24, 5, 20, tzinfo=UTC)
    body = "Your Notion verification code is 123456."

    monkeypatch.setattr(
        gmail,
        "_iter_notion_login_messages",
        lambda client, since, gmail_user: [
            {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Notion <team@mail.notion.so>"},
                        {"name": "Subject", "value": "Your Notion login code"},
                    ],
                    "parts": [{"body": {"data": _gmail_body(body)}}],
                },
            }
        ],
    )

    assert (
        gmail.fetch_notion_login_code_from_gmail(
            "token",
            since,
            gmail_user="user@example.com",
        )
        == "123456"
    )


def test_fetch_notion_login_link_from_gmail_extracts_magic_link(monkeypatch) -> None:
    since = datetime(2026, 6, 24, 5, 20, tzinfo=UTC)
    link = "https://app.notion.com/loginwithemail?token=temporary"
    body = f'<a href="{link}">Sign in with Magic Link</a>'

    monkeypatch.setattr(
        gmail,
        "_iter_notion_login_messages",
        lambda client, since, gmail_user: [
            {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Notion <team@mail.notion.so>"},
                        {"name": "Subject", "value": "Login to Notion"},
                    ],
                    "parts": [{"body": {"data": _gmail_body(body)}}],
                },
            }
        ],
    )

    assert gmail.fetch_notion_login_link_from_gmail("token", since) == link


def test_gmail_message_matches_ignores_old_message() -> None:
    since = datetime(2026, 6, 24, 5, 20, tzinfo=UTC)
    message = {
        "internalDate": str(int((since - timedelta(seconds=3)).timestamp() * 1000)),
        "payload": {
            "headers": [{"name": "From", "value": "Notion <team@mail.notion.so>"}],
            "body": {"data": _gmail_body("Your code is 123456.")},
        },
    }

    assert gmail._gmail_message_matches(message, since) is False


def test_configured_gmail_token_file_prefers_notion_env(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_TOKEN_FILE", "gmail.json")
    monkeypatch.setenv("NOTION_GMAIL_TOKEN_FILE", "notion-gmail.json")

    assert gmail.configured_gmail_token_file() == Path("notion-gmail.json")


def test_gmail_headers_include_quota_project(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_GMAIL_QUOTA_PROJECT", "quota-project")

    assert gmail._gmail_api_headers("token")["x-goog-user-project"] == "quota-project"
