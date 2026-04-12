"""Tests for NotionInternalClient (internal.py)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from notion_native_toolkit.internal import NotionInternalClient


SPACE_ID = "test-space-id"
USER_ID = "test-user-id"
TOKEN = "fake-token-v2"


@pytest.fixture()
def client() -> NotionInternalClient:
    c = NotionInternalClient(
        token_v2=TOKEN,
        space_id=SPACE_ID,
        user_id=USER_ID,
        rate_limit=0,
    )
    yield c
    c.close()


def _mock_response(data: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=data,
        request=httpx.Request("POST", "https://www.notion.so/api/v3/test"),
    )


class TestClientInit:
    def test_attributes(self, client: NotionInternalClient) -> None:
        assert client.token_v2 == TOKEN
        assert client.space_id == SPACE_ID
        assert client.user_id == USER_ID

    def test_context_manager(self) -> None:
        with NotionInternalClient(TOKEN, SPACE_ID, rate_limit=0) as c:
            assert c.space_id == SPACE_ID


class TestPost:
    def test_success(self, client: NotionInternalClient) -> None:
        mock_resp = _mock_response({"ok": True})
        with patch.object(client._session, "post", return_value=mock_resp):
            result = client._post("test", {"key": "value"})
        assert result == {"ok": True}

    def test_http_error_returns_none(self, client: NotionInternalClient) -> None:
        with patch.object(client._session, "post", side_effect=httpx.ConnectError("fail")):
            result = client._post("test", retries=0)
        assert result is None

    def test_400_returns_none(self, client: NotionInternalClient) -> None:
        mock_resp = _mock_response({"error": "bad"}, status=400)
        with patch.object(client._session, "post", return_value=mock_resp):
            result = client._post("test", retries=0)
        assert result is None

    def test_429_retries(self, client: NotionInternalClient) -> None:
        resp_429 = _mock_response({"error": "rate"}, status=429)
        resp_ok = _mock_response({"ok": True})
        with patch.object(client._session, "post", side_effect=[resp_429, resp_ok]):
            result = client._post("test", retries=1)
        assert result == {"ok": True}


class TestSearch:
    def test_builds_payload(self, client: NotionInternalClient) -> None:
        expected_resp = {"results": [], "total": 0}
        with patch.object(client, "_post", return_value=expected_resp) as mock:
            result = client.search("test query", limit=5)
        assert result == expected_resp
        call_args = mock.call_args
        payload = call_args[0][1]
        assert payload["query"] == "test query"
        assert payload["limit"] == 5
        assert payload["spaceId"] == SPACE_ID
        assert payload["type"] == "BlocksInSpace"


class TestUsers:
    def test_list_users_search(self, client: NotionInternalClient) -> None:
        expected = {"users": [{"id": "u1", "name": "Test"}], "hasMore": False}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.list_users_search("test")
        assert result == expected
        payload = mock.call_args[0][1]
        assert payload["query"] == "test"
        assert payload["spaceId"] == SPACE_ID

    def test_find_user(self, client: NotionInternalClient) -> None:
        expected = {"value": {"id": "u1"}}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.find_user("test@example.com")
        payload = mock.call_args[0][1]
        assert payload["email"] == "test@example.com"

    def test_get_visible_users(self, client: NotionInternalClient) -> None:
        expected = {"users": [], "userSimilarity": {}}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.get_visible_users()
        assert result == expected

    def test_get_teams(self, client: NotionInternalClient) -> None:
        expected = {"teams": [{"id": "t1"}]}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.get_teams(team_types=["Joined", "Default"])
        payload = mock.call_args[0][1]
        assert payload["teamTypes"] == ["Joined", "Default"]


class TestAI:
    def test_get_available_models(self, client: NotionInternalClient) -> None:
        expected = {"models": ["gpt-4", "claude"]}
        with patch.object(client, "_post", return_value=expected):
            result = client.get_available_models()
        assert result == expected

    def test_get_ai_usage(self, client: NotionInternalClient) -> None:
        expected = {"usage": 100, "limits": 1000}
        with patch.object(client, "_post", return_value=expected):
            result = client.get_ai_usage()
        assert result == expected

    def test_get_custom_agents(self, client: NotionInternalClient) -> None:
        expected = {"agentIds": ["a1", "a2"]}
        with patch.object(client, "_post", return_value=expected):
            result = client.get_custom_agents()
        assert result == expected

    def test_run_ai_builds_transcript(self, client: NotionInternalClient) -> None:
        with patch.object(client, "_post_stream", return_value=iter([{"type": "done"}])) as mock:
            chunks = list(client.run_ai("Hello", block_id="block-1"))
        assert len(chunks) == 1
        payload = mock.call_args[0][1]
        assert payload["spaceId"] == SPACE_ID
        assert len(payload["transcript"]) == 3
        assert payload["transcript"][0]["type"] == "config"
        assert payload["transcript"][1]["type"] == "context"
        assert payload["transcript"][2]["type"] == "user"
        assert payload["transcript"][2]["value"] == [["Hello"]]


class TestContent:
    def test_load_page_chunk(self, client: NotionInternalClient) -> None:
        expected = {"recordMap": {}, "cursors": {}}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.load_page_chunk("page-id")
        payload = mock.call_args[0][1]
        assert payload["page"]["id"] == "page-id"

    def test_get_backlinks(self, client: NotionInternalClient) -> None:
        expected = {"backlinks": []}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.get_backlinks("block-id")
        payload = mock.call_args[0][1]
        assert payload["block"]["id"] == "block-id"

    def test_detect_language(self, client: NotionInternalClient) -> None:
        expected = {"detectedLanguage": "ko"}
        with patch.object(client, "_post", return_value=expected) as mock:
            result = client.detect_language("page-id")
        payload = mock.call_args[0][1]
        assert payload["pagePointer"]["id"] == "page-id"
        assert payload["pagePointer"]["spaceId"] == SPACE_ID


class TestTransactions:
    def test_save_transactions(self, client: NotionInternalClient) -> None:
        ops = [{"command": "set", "pointer": {"table": "block", "id": "b1"}, "args": {}}]
        with patch.object(client, "_post", return_value={}) as mock:
            client.save_transactions(ops, user_action="test")
        endpoint, payload = mock.call_args[0]
        assert endpoint == "saveTransactionsMain"
        txn = payload["transactions"][0]
        assert txn["operations"] == ops
        assert txn["debug"]["userAction"] == "test"
        assert txn["spaceId"] == SPACE_ID

    def test_save_transactions_fanout(self, client: NotionInternalClient) -> None:
        ops = [{"command": "insertText", "pointer": {"table": "block", "id": "b1"}, "args": {}}]
        with patch.object(client, "_post", return_value={}) as mock:
            client.save_transactions_fanout(ops)
        endpoint, _ = mock.call_args[0]
        assert endpoint == "saveTransactionsFanout"

    def test_create_db_row(self, client: NotionInternalClient) -> None:
        with patch.object(client, "save_transactions", return_value={}) as mock:
            row_id = client.create_db_row("collection-123")
        assert row_id is not None
        ops = mock.call_args[0][0]
        assert len(ops) == 2
        assert ops[0]["command"] == "set"
        assert ops[0]["args"]["type"] == "page"
        assert ops[1]["command"] == "setParent"
        assert ops[1]["args"]["parentId"] == "collection-123"
        assert ops[1]["args"]["parentTable"] == "collection"

    def test_create_db_row_returns_none_on_failure(self, client: NotionInternalClient) -> None:
        with patch.object(client, "save_transactions", return_value=None):
            row_id = client.create_db_row("collection-123")
        assert row_id is None


class TestWorkspace:
    def test_get_space_usage(self, client: NotionInternalClient) -> None:
        expected = {"blockUsage": 1000}
        with patch.object(client, "_post", return_value=expected):
            assert client.get_space_usage() == expected

    def test_get_bots(self, client: NotionInternalClient) -> None:
        expected = {"bots": []}
        with patch.object(client, "_post", return_value=expected):
            assert client.get_bots() == expected

    def test_search_integrations(self, client: NotionInternalClient) -> None:
        expected = {"integrationIds": ["i1"]}
        with patch.object(client, "_post", return_value=expected) as mock:
            client.search_integrations("slack", "external")
        payload = mock.call_args[0][1]
        assert payload["query"] == "slack"
        assert payload["type"] == "external"
