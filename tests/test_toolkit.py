import json
from pathlib import Path

import pytest

from notion_native_toolkit.profiles import WorkspaceProfile
from notion_native_toolkit.toolkit import NotionToolkit


def test_browser_access_does_not_require_api_token() -> None:
    profile = WorkspaceProfile(
        name="browser-only",
        workspace_url="https://www.notion.so/demo",
    )
    toolkit = NotionToolkit(profile)
    assert toolkit.client is None
    assert toolkit.writer is None
    assert toolkit.cli.token is None
    assert toolkit.browser.profile.name == "browser-only"


def test_internal_client_uses_token_from_browser_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "token_v2",
                        "value": "token",
                        "domain": ".www.notion.so",
                        "path": "/",
                    },
                    {
                        "name": "notion_user_id",
                        "value": "user-id",
                        "domain": ".www.notion.so",
                        "path": "/",
                    },
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )
    profile = WorkspaceProfile(
        name="browser-state",
        browser_state_path=str(state_path),
        space_id="space-id",
    )

    toolkit = NotionToolkit(profile)

    assert toolkit.internal is not None
    assert toolkit.internal.token_v2 == "token"
    assert toolkit.internal.user_id == "user-id"
    toolkit.internal.close()


def test_require_internal_guides_to_approved_profile_fields() -> None:
    toolkit = NotionToolkit(WorkspaceProfile(name="missing-internal"))

    with pytest.raises(ValueError) as exc_info:
        toolkit.require_internal()

    message = str(exc_info.value)
    assert "space_id" in message
    assert "token_v2" in message
    assert "browser_state_path" in message
    assert "notion-native browser sync-chrome-cookies --help" in message
    assert "set-internal" not in message
    assert "--token-v2" not in message
