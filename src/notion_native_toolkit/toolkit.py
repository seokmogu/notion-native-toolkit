from __future__ import annotations

from .browser import NotionBrowserAutomation
from .client import NotionApiClient
from .credentials import resolve_credential
from .profiles import WorkspaceProfile, get_profile
from .writer import NotionWriter


class NotionToolkit:
    def __init__(self, profile: WorkspaceProfile):
        self.profile = profile
        token = resolve_credential(profile.api_token)
        self.browser = NotionBrowserAutomation(profile)
        self.client: NotionApiClient | None = None
        self.writer: NotionWriter | None = None
        if token:
            self.client = NotionApiClient(token=token)
            self.writer = NotionWriter(self.client)

    @classmethod
    def from_profile(cls, profile_name: str | None = None) -> NotionToolkit:
        return cls(get_profile(profile_name))

    def require_client(self) -> NotionApiClient:
        if self.client is None:
            raise ValueError(
                f"Profile '{self.profile.name}' does not have a usable API token"
            )
        return self.client

    def require_writer(self) -> NotionWriter:
        if self.writer is None:
            raise ValueError(
                f"Profile '{self.profile.name}' does not have a usable API token"
            )
        return self.writer
