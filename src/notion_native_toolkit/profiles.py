from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .credentials import CredentialRef


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "notion-native-toolkit"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "workspaces.json"
DEFAULT_KEYCHAIN_SERVICE = "notion-native-toolkit"


@dataclass(slots=True)
class WorkspaceProfile:
    name: str
    workspace_url: str | None = None
    default_parent_page_id: str | None = None
    api_token: CredentialRef | None = None
    browser_email: CredentialRef | None = None
    browser_password: CredentialRef | None = None
    browser_state_path: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.workspace_url is not None:
            payload["workspace_url"] = self.workspace_url
        if self.default_parent_page_id is not None:
            payload["default_parent_page_id"] = self.default_parent_page_id
        if self.api_token is not None:
            payload["api_token"] = self.api_token.to_dict()
        if self.browser_email is not None:
            payload["browser_email"] = self.browser_email.to_dict()
        if self.browser_password is not None:
            payload["browser_password"] = self.browser_password.to_dict()
        if self.browser_state_path is not None:
            payload["browser_state_path"] = self.browser_state_path
        if self.notes is not None:
            payload["notes"] = self.notes
        return payload

    @classmethod
    def from_dict(cls, name: str, payload: dict[str, object]) -> WorkspaceProfile:
        return cls(
            name=name,
            workspace_url=_read_optional_str(payload, "workspace_url"),
            default_parent_page_id=_read_optional_str(
                payload, "default_parent_page_id"
            ),
            api_token=CredentialRef.from_dict(
                _read_optional_dict(payload, "api_token")
            ),
            browser_email=CredentialRef.from_dict(
                _read_optional_dict(payload, "browser_email")
            ),
            browser_password=CredentialRef.from_dict(
                _read_optional_dict(payload, "browser_password")
            ),
            browser_state_path=_read_optional_str(payload, "browser_state_path"),
            notes=_read_optional_str(payload, "notes"),
        )


@dataclass(slots=True)
class WorkspaceConfig:
    default_profile: str | None
    profiles: dict[str, WorkspaceProfile]

    def to_dict(self) -> dict[str, object]:
        return {
            "default_profile": self.default_profile,
            "profiles": {
                name: profile.to_dict() for name, profile in self.profiles.items()
            },
        }


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _read_optional_dict(payload: dict[str, object], key: str) -> dict[str, str] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    result: dict[str, str] = {}
    for inner_key, inner_value in value.items():
        if not isinstance(inner_key, str) or not isinstance(inner_value, str):
            raise ValueError(f"{key} entries must be string pairs")
        result[inner_key] = inner_value
    return result


def config_path() -> Path:
    override = os.getenv("NOTION_NATIVE_TOOLKIT_CONFIG")
    return Path(override).expanduser() if override else DEFAULT_CONFIG_PATH


def default_browser_state_path(profile_name: str) -> str:
    return str(
        (DEFAULT_CONFIG_DIR / "browser-state" / f"{profile_name}.json").expanduser()
    )


def load_config() -> WorkspaceConfig:
    path = config_path()
    if not path.exists():
        return WorkspaceConfig(default_profile=None, profiles={})
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be an object")
    raw_profiles = data.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ValueError("profiles must be an object")
    profiles: dict[str, WorkspaceProfile] = {}
    for name, payload in raw_profiles.items():
        if not isinstance(name, str) or not isinstance(payload, dict):
            raise ValueError("Invalid profile entry")
        profiles[name] = WorkspaceProfile.from_dict(name, payload)
    default_profile = data.get("default_profile")
    if default_profile is not None and not isinstance(default_profile, str):
        raise ValueError("default_profile must be a string")
    return WorkspaceConfig(default_profile=default_profile, profiles=profiles)


def save_config(config: WorkspaceConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    return path


def init_config(force: bool = False) -> Path:
    path = config_path()
    if path.exists() and not force:
        return path
    config = WorkspaceConfig(default_profile=None, profiles={})
    return save_config(config)


def get_profile(name: str | None) -> WorkspaceProfile:
    config = load_config()
    effective_name = name or config.default_profile
    if effective_name is None:
        raise ValueError("No profile specified and no default profile configured")
    profile = config.profiles.get(effective_name)
    if profile is None:
        raise ValueError(f"Unknown profile: {effective_name}")
    if not profile.browser_state_path:
        profile.browser_state_path = default_browser_state_path(profile.name)
    return profile


def upsert_profile(profile: WorkspaceProfile, set_default: bool = False) -> Path:
    config = load_config()
    if not profile.browser_state_path:
        profile.browser_state_path = default_browser_state_path(profile.name)
    config.profiles[profile.name] = profile
    if set_default or config.default_profile is None:
        config.default_profile = profile.name
    return save_config(config)


def list_profiles() -> list[WorkspaceProfile]:
    config = load_config()
    return [config.profiles[name] for name in sorted(config.profiles)]
