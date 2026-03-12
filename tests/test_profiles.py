from notion_native_toolkit.credentials import CredentialRef
from notion_native_toolkit.profiles import (
    WorkspaceProfile,
    init_config,
    load_config,
    upsert_profile,
)


def test_profile_round_trip(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "workspaces.json"
    monkeypatch.setenv("NOTION_NATIVE_TOOLKIT_CONFIG", str(config_path))
    init_config(force=True)
    profile = WorkspaceProfile(
        name="alpha",
        workspace_url="https://www.notion.so/alpha",
        default_parent_page_id="parent123",
        api_token=CredentialRef(kind="env", value="NOTION_ALPHA_TOKEN"),
    )
    upsert_profile(profile, set_default=True)
    config = load_config()
    assert config.default_profile == "alpha"
    saved = config.profiles["alpha"]
    assert saved.workspace_url == "https://www.notion.so/alpha"
    assert saved.default_parent_page_id == "parent123"
    assert saved.api_token is not None
    assert saved.api_token.kind == "env"
    assert saved.api_token.value == "NOTION_ALPHA_TOKEN"
