from __future__ import annotations

from notion_native_toolkit.client import (
    NOTION_LATEST_VERSION,
    NOTION_VERSION,
    NotionApiClient,
)


def test_client_uses_default_notion_version(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_API_VERSION", raising=False)

    client = NotionApiClient(token="secret")
    try:
        assert client.session.headers["Notion-Version"] == NOTION_VERSION
        assert client.latest_notion_version == NOTION_LATEST_VERSION
    finally:
        client.session.close()


def test_client_uses_notion_api_version_env(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_API_VERSION", "2026-03-11")

    client = NotionApiClient(token="secret")
    try:
        assert client.session.headers["Notion-Version"] == "2026-03-11"
        assert client.latest_notion_version == "2026-03-11"
    finally:
        client.session.close()


def test_client_constructor_version_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_API_VERSION", "2026-03-11")

    client = NotionApiClient(token="secret", notion_version="2026-06-01")
    try:
        assert client.session.headers["Notion-Version"] == "2026-06-01"
        assert client.latest_notion_version == "2026-06-01"
    finally:
        client.session.close()


def test_call_can_override_notion_version(monkeypatch) -> None:
    client = NotionApiClient(token="secret")
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"ok": True}

    def fake_request(method, endpoint, json=None, headers=None):
        calls.append((method, endpoint, json, headers))
        return FakeResponse()

    try:
        monkeypatch.setattr(client.session, "request", fake_request)
        assert client.call("GET", "pages/page-id", notion_version="2026-03-11") == {
            "ok": True
        }
    finally:
        client.session.close()

    assert calls == [("GET", "pages/page-id", None, {"Notion-Version": "2026-03-11"})]


def test_page_and_database_crud_use_latest_version_but_database_query_stays_legacy() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        if endpoint == "databases/db-id/query":
            return {"results": [{"id": "row-1"}], "has_more": False}
        return {"ok": True}

    page_payload = {"parent": {"page_id": "parent-id"}, "properties": {}}
    page_update = {"properties": {"Name": {"title": []}}}
    database_payload = {"parent": {"page_id": "parent-id"}, "title": []}
    database_update = {"title": []}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.fetch_page("page-id") == {"ok": True}
        assert client.create_page(page_payload) == {"ok": True}
        assert client.update_page("page-id", page_update) == {"ok": True}
        assert client.fetch_database("db-id") == {"ok": True}
        assert client.create_database(database_payload) == {"ok": True}
        assert client.update_database("db-id", database_update) == {"ok": True}
        assert client.query_database("db-id", {"filter": {"property": "Done"}}) == [
            {"id": "row-1"}
        ]
    finally:
        client.session.close()

    assert calls == [
        ("GET", "pages/page-id", None, NOTION_LATEST_VERSION),
        ("POST", "pages", page_payload, NOTION_LATEST_VERSION),
        ("PATCH", "pages/page-id", page_update, NOTION_LATEST_VERSION),
        ("GET", "databases/db-id", None, NOTION_LATEST_VERSION),
        ("POST", "databases", database_payload, NOTION_LATEST_VERSION),
        ("PATCH", "databases/db-id", database_update, NOTION_LATEST_VERSION),
        (
            "POST",
            "databases/db-id/query",
            {"filter": {"property": "Done"}, "page_size": 100},
            None,
        ),
    ]


def test_query_data_source_paginates_without_mutating_payload() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    responses = [
        {
            "results": [{"id": "row-1"}],
            "has_more": True,
            "next_cursor": "cursor-1",
        },
        {
            "results": [{"id": "row-2"}],
            "has_more": False,
        },
    ]

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        return responses.pop(0)

    try:
        client.call = fake_call  # type: ignore[method-assign]
        payload = {"filter": {"property": "Done", "checkbox": {"equals": True}}}
        rows = client.query_data_source("ds-id", payload)
    finally:
        client.session.close()

    assert rows == [{"id": "row-1"}, {"id": "row-2"}]
    assert payload == {"filter": {"property": "Done", "checkbox": {"equals": True}}}
    assert calls == [
        (
            "POST",
            "data_sources/ds-id/query",
            {
                "filter": {"property": "Done", "checkbox": {"equals": True}},
                "page_size": 100,
            },
            NOTION_LATEST_VERSION,
        ),
        (
            "POST",
            "data_sources/ds-id/query",
            {
                "filter": {"property": "Done", "checkbox": {"equals": True}},
                "page_size": 100,
                "start_cursor": "cursor-1",
            },
            NOTION_LATEST_VERSION,
        ),
    ]


def test_list_data_source_templates_uses_get_pagination() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    responses = [
        {
            "results": [{"id": "template-1"}],
            "has_more": True,
            "next_cursor": "cursor-1",
        },
        {
            "results": [{"id": "template-2"}],
            "has_more": False,
        },
    ]

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        return responses.pop(0)

    try:
        client.call = fake_call  # type: ignore[method-assign]
        rows = client.list_data_source_templates("ds-id")
    finally:
        client.session.close()

    assert rows == [{"id": "template-1"}, {"id": "template-2"}]
    assert calls == [
        (
            "GET",
            "data_sources/ds-id/templates?page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "GET",
            "data_sources/ds-id/templates?page_size=100&start_cursor=cursor-1",
            None,
            NOTION_LATEST_VERSION,
        ),
    ]


def test_data_source_crud_endpoints() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        return {"ok": True}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.fetch_data_source("ds-id") == {"ok": True}
        assert client.create_data_source({"parent": {"page_id": "page-id"}}) == {
            "ok": True
        }
        assert client.update_data_source("ds-id", {"title": []}) == {"ok": True}
    finally:
        client.session.close()

    assert calls == [
        ("GET", "data_sources/ds-id", None, NOTION_LATEST_VERSION),
        (
            "POST",
            "data_sources",
            {"parent": {"page_id": "page-id"}},
            NOTION_LATEST_VERSION,
        ),
        ("PATCH", "data_sources/ds-id", {"title": []}, NOTION_LATEST_VERSION),
    ]


def test_comments_crud_and_pagination_use_latest_version() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    comment_pages = [
        {
            "results": [{"id": "comment-1"}],
            "has_more": True,
            "next_cursor": "cursor-1",
        },
        {
            "results": [{"id": "comment-2"}],
            "has_more": False,
        },
    ]

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        if method == "GET" and endpoint.startswith("comments?"):
            return comment_pages.pop(0)
        return {"id": "comment-id"}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.list_comments("block-id") == [
            {"id": "comment-1"},
            {"id": "comment-2"},
        ]
        assert client.fetch_comment("comment-id") == {"id": "comment-id"}
        assert client.create_comment_markdown(
            "Looks good",
            parent_page_id="page-id",
        ) == {"id": "comment-id"}
        assert client.create_comment_markdown(
            "Reply",
            discussion_id="discussion-id",
        ) == {"id": "comment-id"}
        assert client.update_comment_markdown("comment-id", "Updated") == {
            "id": "comment-id"
        }
        assert client.delete_comment("comment-id") == {"id": "comment-id"}
    finally:
        client.session.close()

    assert calls == [
        (
            "GET",
            "comments?block_id=block-id&page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "GET",
            "comments?block_id=block-id&page_size=100&start_cursor=cursor-1",
            None,
            NOTION_LATEST_VERSION,
        ),
        ("GET", "comments/comment-id", None, NOTION_LATEST_VERSION),
        (
            "POST",
            "comments",
            {
                "parent": {"type": "page_id", "page_id": "page-id"},
                "markdown": "Looks good",
            },
            NOTION_LATEST_VERSION,
        ),
        (
            "POST",
            "comments",
            {"discussion_id": "discussion-id", "markdown": "Reply"},
            NOTION_LATEST_VERSION,
        ),
        (
            "PATCH",
            "comments/comment-id",
            {"markdown": "Updated"},
            NOTION_LATEST_VERSION,
        ),
        ("DELETE", "comments/comment-id", None, NOTION_LATEST_VERSION),
    ]


def test_create_comment_markdown_rejects_ambiguous_location() -> None:
    client = NotionApiClient(token="secret")
    try:
        try:
            client.create_comment_markdown("Missing location")
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError("create_comment_markdown should require a location")

        try:
            client.create_comment_markdown(
                "Too many locations",
                parent_page_id="page-id",
                parent_block_id="block-id",
            )
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError(
                "create_comment_markdown should reject multiple locations"
            )
    finally:
        client.session.close()


def test_search_users_custom_emojis_and_page_property_use_latest_version() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    paged_responses = {
        ("POST", "search"): [
            {
                "results": [{"id": "page-1"}],
                "has_more": True,
                "next_cursor": "cursor-1",
            },
            {"results": [{"id": "page-2"}], "has_more": False},
        ],
        ("GET", "users?page_size=100"): [
            {"results": [{"id": "user-1"}], "has_more": False}
        ],
        ("GET", "custom_emojis?page_size=100"): [
            {"results": [{"id": "emoji-1"}], "has_more": False}
        ],
        ("GET", "pages/page-id/properties/relation?page_size=100"): [
            {"results": [{"id": "relation-1"}], "has_more": False}
        ],
    }

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        if method == "POST" and endpoint == "search":
            return paged_responses[(method, endpoint)].pop(0)
        if method == "GET" and endpoint in {
            "users?page_size=100",
            "custom_emojis?page_size=100",
            "pages/page-id/properties/relation?page_size=100",
        }:
            return paged_responses[(method, endpoint)].pop(0)
        if endpoint == "pages/page-id/properties/relation":
            return {"object": "list"}
        return {"id": endpoint.rsplit("/", 1)[-1]}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.search({"query": "roadmap"}) == [
            {"id": "page-1"},
            {"id": "page-2"},
        ]
        assert client.list_users() == [{"id": "user-1"}]
        assert client.fetch_user("user-id") == {"id": "user-id"}
        assert client.fetch_bot_user() == {"id": "me"}
        assert client.list_custom_emojis() == [{"id": "emoji-1"}]
        assert client.fetch_page_property("page-id", "title") == {"id": "title"}
        assert client.fetch_page_property("page-id", "relation") == [
            {"id": "relation-1"}
        ]
    finally:
        client.session.close()

    assert calls == [
        (
            "POST",
            "search",
            {"query": "roadmap", "page_size": 100},
            NOTION_LATEST_VERSION,
        ),
        (
            "POST",
            "search",
            {"query": "roadmap", "page_size": 100, "start_cursor": "cursor-1"},
            NOTION_LATEST_VERSION,
        ),
        ("GET", "users?page_size=100", None, NOTION_LATEST_VERSION),
        ("GET", "users/user-id", None, NOTION_LATEST_VERSION),
        ("GET", "users/me", None, NOTION_LATEST_VERSION),
        ("GET", "custom_emojis?page_size=100", None, NOTION_LATEST_VERSION),
        (
            "GET",
            "pages/page-id/properties/title",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "GET",
            "pages/page-id/properties/relation",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "GET",
            "pages/page-id/properties/relation?page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
    ]


def test_views_crud_and_query_results_use_latest_version() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    paged_responses = {
        ("GET", "views?database_id=db-id&data_source_id=ds-id&page_size=100"): [
            {"results": [{"id": "view-1"}], "has_more": False}
        ],
        ("GET", "views/view-id/queries/query-id?page_size=100"): [
            {"results": [{"id": "row-1"}], "has_more": False}
        ],
    }

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        if (method, endpoint) in paged_responses:
            return paged_responses[(method, endpoint)].pop(0)
        return {"id": endpoint.rsplit("/", 1)[-1]}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.list_views(database_id="db-id", data_source_id="ds-id") == [
            {"id": "view-1"}
        ]
        assert client.create_view({"parent": {"data_source_id": "ds-id"}}) == {
            "id": "views"
        }
        assert client.fetch_view("view-id") == {"id": "view-id"}
        assert client.update_view("view-id", {"name": "New view"}) == {"id": "view-id"}
        assert client.delete_view("view-id") == {"id": "view-id"}
        assert client.create_view_query("view-id", {"filter": {}}) == {"id": "queries"}
        assert client.fetch_view_query_results("view-id", "query-id") == [
            {"id": "row-1"}
        ]
        assert client.delete_view_query("view-id", "query-id") == {"id": "query-id"}
    finally:
        client.session.close()

    assert calls == [
        (
            "GET",
            "views?database_id=db-id&data_source_id=ds-id&page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "POST",
            "views",
            {"parent": {"data_source_id": "ds-id"}},
            NOTION_LATEST_VERSION,
        ),
        ("GET", "views/view-id", None, NOTION_LATEST_VERSION),
        ("PATCH", "views/view-id", {"name": "New view"}, NOTION_LATEST_VERSION),
        ("DELETE", "views/view-id", None, NOTION_LATEST_VERSION),
        ("POST", "views/view-id/queries", {"filter": {}}, NOTION_LATEST_VERSION),
        (
            "GET",
            "views/view-id/queries/query-id?page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "DELETE",
            "views/view-id/queries/query-id",
            None,
            NOTION_LATEST_VERSION,
        ),
    ]


def test_list_views_requires_parent_scope() -> None:
    client = NotionApiClient(token="secret")
    try:
        try:
            client.list_views()
        except ValueError as exc:
            assert "database_id" in str(exc)
        else:
            raise AssertionError("list_views should require a parent scope")
    finally:
        client.session.close()


def test_blocks_and_meeting_notes_use_latest_version() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    paged_responses = {
        ("GET", "blocks/block-id/children?page_size=100"): [
            {"results": [{"id": "child-1"}], "has_more": False}
        ],
    }

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        if (method, endpoint) in paged_responses:
            return paged_responses[(method, endpoint)].pop(0)
        return {"id": "block-id"}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.fetch_block("block-id") == {"id": "block-id"}
        assert client.fetch_children("block-id") == [{"id": "child-1"}]
        assert client.append_children("block-id", [{"paragraph": {}}]) == {
            "id": "block-id"
        }
        assert client.append_children(
            "block-id",
            [{"paragraph": {}}],
            after="previous-block-id",
        ) == {"id": "block-id"}
        assert client.update_block("block-id", {"paragraph": {"rich_text": []}}) == {
            "id": "block-id"
        }
        assert client.delete_block("block-id") == {"id": "block-id"}
        assert client.query_meeting_notes({"query": "weekly"}) == {"id": "block-id"}
    finally:
        client.session.close()

    assert calls == [
        ("GET", "blocks/block-id", None, NOTION_LATEST_VERSION),
        (
            "GET",
            "blocks/block-id/children?page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "PATCH",
            "blocks/block-id/children",
            {"children": [{"paragraph": {}}]},
            NOTION_LATEST_VERSION,
        ),
        (
            "PATCH",
            "blocks/block-id/children",
            {
                "children": [{"paragraph": {}}],
                "position": {
                    "type": "after_block",
                    "after_block": {"id": "previous-block-id"},
                },
            },
            NOTION_LATEST_VERSION,
        ),
        (
            "PATCH",
            "blocks/block-id",
            {"paragraph": {"rich_text": []}},
            NOTION_LATEST_VERSION,
        ),
        ("DELETE", "blocks/block-id", None, NOTION_LATEST_VERSION),
        (
            "POST",
            "blocks/meeting_notes/query",
            {"query": "weekly"},
            NOTION_LATEST_VERSION,
        ),
    ]


def test_list_file_uploads_supports_status_filter_and_pagination() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []
    responses = [
        {
            "results": [{"id": "upload-1"}],
            "has_more": True,
            "next_cursor": "cursor-1",
        },
        {
            "results": [{"id": "upload-2"}],
            "has_more": False,
        },
    ]

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        return responses.pop(0)

    try:
        client.call = fake_call  # type: ignore[method-assign]
        rows = client.list_file_uploads(status="uploaded")
    finally:
        client.session.close()

    assert rows == [{"id": "upload-1"}, {"id": "upload-2"}]
    assert calls == [
        (
            "GET",
            "file_uploads?status=uploaded&page_size=100",
            None,
            NOTION_LATEST_VERSION,
        ),
        (
            "GET",
            "file_uploads?status=uploaded&page_size=100&start_cursor=cursor-1",
            None,
            NOTION_LATEST_VERSION,
        ),
    ]


def test_file_upload_retrieve_and_complete_endpoints() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        return {"id": "upload-id"}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.fetch_file_upload("upload-id") == {"id": "upload-id"}
        assert client.complete_file_upload("upload-id") == {"id": "upload-id"}
    finally:
        client.session.close()

    assert calls == [
        ("GET", "file_uploads/upload-id", None, NOTION_LATEST_VERSION),
        ("POST", "file_uploads/upload-id/complete", None, NOTION_LATEST_VERSION),
    ]


def test_send_file_upload_uses_latest_notion_version(monkeypatch) -> None:
    client = NotionApiClient(token="secret")
    posts = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "upload-id", "status": "uploaded"}

    class FakeHttpxClient:
        def __init__(self, *, timeout, verify):
            self.timeout = timeout
            self.verify = verify

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def post(url, *, headers, files):
            posts.append((url, headers, files))
            return FakeResponse()

    try:
        monkeypatch.setattr(
            "notion_native_toolkit.client.httpx.Client", FakeHttpxClient
        )
        payload = client.send_file_upload("upload-id", "report.pdf", b"pdf-bytes")
    finally:
        client.session.close()

    assert payload == {"id": "upload-id", "status": "uploaded"}
    assert posts == [
        (
            "https://api.notion.com/v1/file_uploads/upload-id/send",
            {
                "Authorization": "Bearer secret",
                "Notion-Version": NOTION_LATEST_VERSION,
            },
            {"file": ("report.pdf", b"pdf-bytes")},
        )
    ]


def test_modern_page_markdown_endpoints_use_latest_version() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        if endpoint.endswith("/markdown") and method == "GET":
            return {"markdown": "# Title"}
        return {"id": "page-id"}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.create_page_markdown("parent-id", "Title", "# Title") == {
            "id": "page-id"
        }
        assert client.retrieve_markdown("page-id") == "# Title"
        assert client.replace_markdown("page-id", "# Updated") == {"id": "page-id"}
    finally:
        client.session.close()

    assert calls == [
        (
            "POST",
            "pages",
            {
                "parent": {"page_id": "parent-id"},
                "properties": {
                    "title": {
                        "title": [
                            {"type": "text", "text": {"content": "Title"}},
                        ]
                    }
                },
                "markdown": "# Title",
            },
            NOTION_LATEST_VERSION,
        ),
        ("GET", "pages/page-id/markdown", None, NOTION_LATEST_VERSION),
        (
            "PATCH",
            "pages/page-id/markdown",
            {
                "type": "replace_content",
                "replace_content": {"new_str": "# Updated"},
            },
            NOTION_LATEST_VERSION,
        ),
    ]


def test_move_page_supports_page_and_data_source_parents() -> None:
    client = NotionApiClient(token="secret")
    calls: list[tuple[str, str, dict | None, str | None]] = []

    def fake_call(method, endpoint, data=None, notion_version=None):
        calls.append((method, endpoint, data, notion_version))
        return {"id": "page-id"}

    try:
        client.call = fake_call  # type: ignore[method-assign]
        assert client.move_page("page-id", parent_page_id="parent-page-id") == {
            "id": "page-id"
        }
        assert client.move_page(
            "page-id", parent_data_source_id="parent-data-source-id"
        ) == {"id": "page-id"}
    finally:
        client.session.close()

    assert calls == [
        (
            "POST",
            "pages/page-id/move",
            {"parent": {"type": "page_id", "page_id": "parent-page-id"}},
            NOTION_LATEST_VERSION,
        ),
        (
            "POST",
            "pages/page-id/move",
            {
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": "parent-data-source-id",
                }
            },
            NOTION_LATEST_VERSION,
        ),
    ]


def test_move_page_rejects_ambiguous_parent() -> None:
    client = NotionApiClient(token="secret")
    try:
        try:
            client.move_page("page-id")
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError("move_page should reject a missing parent")

        try:
            client.move_page(
                "page-id",
                parent_page_id="parent-page-id",
                parent_data_source_id="parent-data-source-id",
            )
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError("move_page should reject multiple parents")
    finally:
        client.session.close()
