import json
from pathlib import Path

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
