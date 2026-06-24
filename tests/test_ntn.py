from __future__ import annotations

import subprocess
from typing import Any

import pytest

from notion_native_toolkit.cli import _ensure_leading_h1, _parent_page_ref
from notion_native_toolkit.ntn import NotionCliClient, NotionCliError


def test_ensure_leading_h1_preserves_existing_title() -> None:
    assert _ensure_leading_h1("# Existing\n\nBody", "New") == "# Existing\n\nBody"


def test_ensure_leading_h1_adds_title_when_missing() -> None:
    assert _ensure_leading_h1("Body", "Title") == "# Title\n\nBody"


def test_parent_page_ref_accepts_raw_page_id_or_explicit_ref() -> None:
    assert _parent_page_ref("abc-def") == "page:abcdef"
    assert _parent_page_ref("database:db-id") == "database:db-id"


def test_pages_create_uses_stdin_and_profile_token(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b'{"id":"page-id","url":"https://notion.so/page-id"}',
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(token="ntn_secret", env={"PATH": "/bin"})
    payload = client.pages_create("page:parent-id", "# Title\n\nBody")

    assert payload["id"] == "page-id"
    assert calls[0]["args"][0] == [
        "/bin/ntn",
        "pages",
        "create",
        "--parent",
        "page:parent-id",
        "--json",
    ]
    assert calls[0]["kwargs"]["input"] == b"# Title\n\nBody"
    assert calls[0]["kwargs"]["env"]["NOTION_API_TOKEN"] == "ntn_secret"


def test_api_discovery_commands(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        stdout = b'[{"method":"POST","path":"/v1/comments"}]'
        if "--docs" in args[0]:
            stdout = b"# Docs\n"
        elif "--spec" in args[0]:
            stdout = b'{"paths":{}}'
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=stdout,
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    assert client.api_list() == [{"method": "POST", "path": "/v1/comments"}]
    assert client.api_docs("v1/comments", method="post") == "# Docs\n"
    assert client.api_spec("v1/comments", method="post") == {"paths": {}}

    assert calls == [
        ["/bin/ntn", "api", "ls", "--json"],
        ["/bin/ntn", "api", "v1/comments", "--docs", "-X", "POST"],
        ["/bin/ntn", "api", "v1/comments", "--spec", "-X", "POST"],
    ]


def test_pages_edit_allows_child_content_deletion_only_when_requested(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b'{"id":"page-id"}',
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    client.pages_edit("page-id", "# Updated")
    client.pages_edit("page-id", "# Updated", allow_deleting_content=True)

    assert "--allow-deleting-content" not in calls[0]
    assert "--allow-deleting-content" in calls[1]


def test_pages_trash_requires_intentional_command(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b"Trashed page-id\n",
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    result = client.pages_trash("page-id")

    assert result.stdout == "Trashed page-id\n"
    assert calls == [["/bin/ntn", "pages", "trash", "page-id", "--yes"]]


def test_datasources_query_builds_filter_sort_and_cursor_args(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b'{"results":[{"id":"row-1"}]}',
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    payload = client.datasources_query(
        "ds-id",
        limit=50,
        start_cursor="cursor-1",
        sorts=["Priority desc", "Name asc"],
        filter_payload={"property": "Done", "checkbox": {"equals": True}},
    )

    assert payload == {"results": [{"id": "row-1"}]}
    assert calls[0]["args"][0] == [
        "/bin/ntn",
        "datasources",
        "query",
        "ds-id",
        "--limit",
        "50",
        "--start-cursor",
        "cursor-1",
        "--sort",
        "Priority desc",
        "--sort",
        "Name asc",
        "--filter",
        '{"property": "Done", "checkbox": {"equals": true}}',
        "--json",
    ]


def test_datasources_resolve_outputs_json(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b'{"data_sources":[{"id":"ds-id"}]}',
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    assert client.datasources_resolve("database-id") == {
        "data_sources": [{"id": "ds-id"}]
    }
    assert calls == [["/bin/ntn", "datasources", "resolve", "database-id", "--json"]]


def test_whoami_outputs_json(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b'{"object":"user","id":"user-id"}',
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})

    assert client.whoami() == {"object": "user", "id": "user-id"}
    assert calls == [["/bin/ntn", "whoami", "--json"]]


def test_files_create_passes_bytes_and_filename(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b'{"id":"upload-id","status":"uploaded"}',
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    payload = client.files_create(
        b"image-bytes",
        filename="image.png",
        content_type="image/png",
    )

    assert payload["id"] == "upload-id"
    assert calls[0]["args"][0] == [
        "/bin/ntn",
        "files",
        "create",
        "--filename",
        "image.png",
        "--content-type",
        "image/png",
        "--json",
    ]
    assert calls[0]["kwargs"]["input"] == b"image-bytes"


def test_files_get_and_list_parse_json(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        stdout = b'{"id":"upload-id","status":"uploaded"}'
        if args[0][2] == "list":
            stdout = b'{"results":[{"id":"upload-id"}]}'
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=stdout,
            stderr=b"",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})

    assert client.files_get("upload-id") == {"id": "upload-id", "status": "uploaded"}
    assert client.files_list() == {"results": [{"id": "upload-id"}]}
    assert calls == [
        ["/bin/ntn", "files", "get", "upload-id", "--json"],
        ["/bin/ntn", "files", "list", "--json"],
    ]


def test_failed_command_raises_cli_error(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout=b"",
            stderr=b"not authenticated",
        )

    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: "/bin/ntn")
    monkeypatch.setattr("notion_native_toolkit.ntn.subprocess.run", fake_run)

    client = NotionCliClient(env={"PATH": "/bin"})
    with pytest.raises(NotionCliError, match="not authenticated"):
        client.version()


def test_missing_ntn_binary_raises_file_not_found(monkeypatch) -> None:
    monkeypatch.setattr("notion_native_toolkit.ntn.shutil.which", lambda _: None)

    client = NotionCliClient(env={"PATH": "/bin"})
    with pytest.raises(FileNotFoundError):
        client.version()
