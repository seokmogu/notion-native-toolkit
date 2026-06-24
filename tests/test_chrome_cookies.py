from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from notion_native_toolkit import chrome_cookies


def _create_cookie_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            create table cookies(
                creation_utc integer not null,
                host_key text not null,
                top_frame_site_key text not null,
                name text not null,
                value text not null,
                encrypted_value blob not null,
                path text not null,
                expires_utc integer not null,
                is_secure integer not null,
                is_httponly integer not null,
                last_access_utc integer not null,
                has_expires integer not null,
                is_persistent integer not null,
                priority integer not null,
                samesite integer not null,
                source_scheme integer not null,
                source_port integer not null,
                last_update_utc integer not null,
                source_type integer not null,
                has_cross_site_ancestor integer not null
            )
            """
        )


def _insert_cookie(
    db_path: Path,
    *,
    host_key: str,
    name: str,
    value: str = "",
    encrypted_value: bytes = b"",
    expires: int = -1,
    has_expires: int = 0,
    is_persistent: int = 0,
    samesite: int = -1,
) -> None:
    expires_utc = 0
    if expires >= 0:
        expires_utc = int(
            (expires + chrome_cookies.CHROME_EPOCH_OFFSET_SECONDS) * 1_000_000
        )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into cookies values(
                0, ?, '', ?, ?, ?, '/', ?, 1, 1, 0, ?, ?, 1, ?, 2, 443, 0, 0, 0
            )
            """,
            (
                host_key,
                name,
                value,
                encrypted_value,
                expires_utc,
                has_expires,
                is_persistent,
                samesite,
            ),
        )


def test_sync_chrome_cookies_to_storage_state_merges_notion_cookies(tmp_path: Path) -> None:
    cookie_db = tmp_path / "chrome" / "Profile 1" / "Cookies"
    _create_cookie_db(cookie_db)
    _insert_cookie(
        cookie_db,
        host_key=".www.notion.so",
        name="token_v2",
        value="token",
        expires=1_800_000_000,
        has_expires=1,
        is_persistent=1,
        samesite=1,
    )
    _insert_cookie(
        cookie_db,
        host_key=".www.notion.so",
        name="notion_user_id",
        value="user-id",
    )
    storage_state = tmp_path / "state.json"
    storage_state.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "keep", "value": "1", "domain": "example.com", "path": "/"},
                    {
                        "name": "old",
                        "value": "old",
                        "domain": ".www.notion.so",
                        "path": "/",
                    },
                ],
                "origins": [{"origin": "https://www.notion.so", "localStorage": []}],
            }
        ),
        encoding="utf-8",
    )

    result = chrome_cookies.sync_chrome_cookies_to_storage_state(
        storage_state,
        chrome_profile="Profile 1",
        chrome_user_data_dir=tmp_path / "chrome",
    )

    payload = json.loads(storage_state.read_text(encoding="utf-8"))
    cookies = payload["cookies"]
    assert result.cookies_synced == 2
    assert result.token_v2_present is True
    assert {cookie["name"] for cookie in cookies} == {"keep", "token_v2", "notion_user_id"}
    token = next(cookie for cookie in cookies if cookie["name"] == "token_v2")
    assert token["value"] == "token"
    assert token["expires"] == 1_800_000_000
    assert token["sameSite"] == "Lax"
    assert payload["origins"] == [
        {"origin": "https://www.notion.so", "localStorage": []}
    ]


def test_export_chrome_cookies_decrypts_encrypted_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cookie_db = tmp_path / "Default" / "Cookies"
    _create_cookie_db(cookie_db)
    _insert_cookie(
        cookie_db,
        host_key=".www.notion.so",
        name="token_v2",
        encrypted_value=b"v10encrypted",
    )

    monkeypatch.setattr(
        chrome_cookies,
        "_decrypt_chrome_value",
        lambda host_key, encrypted_value: f"decrypted:{host_key}:{encrypted_value!r}",
    )

    cookies = chrome_cookies.export_chrome_cookies(cookie_db)

    assert cookies[0]["value"] == "decrypted:.www.notion.so:b'v10encrypted'"


def test_find_chrome_cookie_db_auto_discovers_profile_with_notion_cookie(
    tmp_path: Path,
) -> None:
    default_db = tmp_path / "Default" / "Cookies"
    profile_db = tmp_path / "Profile 1" / "Cookies"
    _create_cookie_db(default_db)
    _create_cookie_db(profile_db)
    _insert_cookie(
        profile_db,
        host_key=".www.notion.so",
        name="token_v2",
        value="token",
    )

    assert (
        chrome_cookies.find_chrome_cookie_db(chrome_user_data_dir=tmp_path)
        == profile_db
    )
