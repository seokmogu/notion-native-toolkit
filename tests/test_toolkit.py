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
    assert toolkit.browser.profile.name == "browser-only"
