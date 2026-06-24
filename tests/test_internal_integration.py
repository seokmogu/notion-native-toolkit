"""Integration tests for NotionInternalClient.

These tests hit the real Notion API. Run with:
    pytest tests/test_internal_integration.py -v

Requires Chrome cookies synced at ~/.chrome-automation-profile/cookies.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from notion_native_toolkit.browser_state import find_storage_state_cookie
from notion_native_toolkit.internal import NotionInternalClient
from notion_native_toolkit.profiles import WorkspaceProfile, get_profile

COOKIES_PATH = Path.home() / ".chrome-automation-profile" / "cookies.json"
DEFAULT_SPACE_ID = "7197d832-2b04-81a8-94d3-00038ba30695"
INTEGRATION_PROFILE = os.getenv("NOTION_NATIVE_INTEGRATION_PROFILE", "worxphere")
TEST_PAGE_ID = "33f7d832-2b04-8046-a0ad-f3bd451fee4f"  # AX page

pytestmark = pytest.mark.integration


def _load_credentials() -> tuple[str, str | None, str]:
    env_token = os.getenv("NOTION_TOKEN_V2")
    if env_token:
        return (
            env_token,
            os.getenv("NOTION_USER_ID"),
            os.getenv("NOTION_SPACE_ID") or DEFAULT_SPACE_ID,
        )

    profile = _load_integration_profile()
    if profile and profile.browser_state_path:
        token = find_storage_state_cookie(profile.browser_state_path, "token_v2")
        if token:
            return (
                token,
                find_storage_state_cookie(
                    profile.browser_state_path,
                    "notion_user_id",
                ),
                profile.space_id or DEFAULT_SPACE_ID,
            )

    if not COOKIES_PATH.exists():
        pytest.skip("Chrome cookies not found")
    cookies = json.loads(COOKIES_PATH.read_text())
    token = next(
        (c["value"] for c in cookies if c["name"] == "token_v2" and "notion.so" in c["domain"]),
        None,
    )
    user_id = next(
        (c["value"] for c in cookies if c["name"] == "notion_user_id" and "notion.so" in c["domain"]),
        None,
    )
    if not token:
        pytest.skip("token_v2 not found in cookies")
    return token, user_id, DEFAULT_SPACE_ID


def _load_integration_profile() -> WorkspaceProfile | None:
    try:
        return get_profile(INTEGRATION_PROFILE)
    except ValueError:
        return None


@pytest.fixture(scope="module")
def client() -> NotionInternalClient:
    token, user_id, space_id = _load_credentials()
    c = NotionInternalClient(
        token_v2=token,
        space_id=space_id,
        user_id=user_id,
        rate_limit=0.5,
    )
    if c.get_visible_users() is None:
        c.close()
        pytest.skip("token_v2 is expired or does not authorize internal API reads")
    yield c
    c.close()


# --- Search ---

class TestSearch:
    def test_search_returns_results(self, client: NotionInternalClient) -> None:
        result = client.search("Talent Agent", limit=3)
        assert result is not None
        assert "results" in result
        assert "total" in result

    def test_search_empty_query(self, client: NotionInternalClient) -> None:
        result = client.search("", limit=1)
        assert result is not None


# --- Users ---

class TestUsers:
    def test_get_visible_users(self, client: NotionInternalClient) -> None:
        result = client.get_visible_users()
        assert result is not None
        assert any(k in result for k in ("users", "visibleUsers", "shouldUseEdgeCache"))

    def test_list_users_search(self, client: NotionInternalClient) -> None:
        result = client.list_users_search("seok")
        assert result is not None
        assert "users" in result
        users = result["users"]
        assert isinstance(users, list)
        assert len(users) > 0

    def test_get_teams(self, client: NotionInternalClient) -> None:
        result = client.get_teams()
        assert result is not None
        assert "teams" in result
        assert len(result["teams"]) > 0

    def test_get_internal_domains(self, client: NotionInternalClient) -> None:
        result = client.get_internal_domains()
        assert result is not None
        assert "internalDomains" in result or "internalDomainsWithInfo" in result

    def test_get_member_email_domains(self, client: NotionInternalClient) -> None:
        result = client.get_member_email_domains()
        assert result is not None
        assert "emailDomains" in result

    def test_get_permission_groups(self, client: NotionInternalClient) -> None:
        result = client.get_permission_groups()
        assert result is not None
        assert "groupsWithMemberCount" in result


# --- AI ---

class TestAI:
    def test_get_available_models(self, client: NotionInternalClient) -> None:
        result = client.get_available_models()
        assert result is not None
        assert "models" in result

    def test_get_ai_usage(self, client: NotionInternalClient) -> None:
        result = client.get_ai_usage()
        assert result is not None
        assert "usage" in result or "limits" in result

    def test_get_custom_agents(self, client: NotionInternalClient) -> None:
        result = client.get_custom_agents()
        assert result is not None
        assert "agentIds" in result

    def test_get_ai_connectors(self, client: NotionInternalClient) -> None:
        result = client.get_ai_connectors()
        assert result is not None
        assert any(k in result for k in ("connectedConnectors", "availableConnectors"))

    def test_get_user_prompts(self, client: NotionInternalClient) -> None:
        result = client.get_user_prompts()
        assert result is not None
        assert "categories" in result or "recordMap" in result


# --- Content ---

class TestContent:
    def test_load_page_chunk(self, client: NotionInternalClient) -> None:
        result = client.load_page_chunk(TEST_PAGE_ID)
        assert result is not None
        assert "recordMap" in result

    def test_get_backlinks(self, client: NotionInternalClient) -> None:
        result = client.get_backlinks(TEST_PAGE_ID)
        assert result is not None
        assert "backlinks" in result

    def test_detect_language(self, client: NotionInternalClient) -> None:
        result = client.detect_language(TEST_PAGE_ID)
        assert result is not None
        assert "detectedLanguage" in result
        assert result["detectedLanguage"] == "ko"


# --- Workspace ---

class TestWorkspace:
    def test_get_space_usage(self, client: NotionInternalClient) -> None:
        result = client.get_space_usage()
        assert result is not None
        assert "blockUsage" in result

    def test_search_integrations(self, client: NotionInternalClient) -> None:
        result = client.search_integrations()
        assert result is not None
        assert "integrationIds" in result or "recordMap" in result
