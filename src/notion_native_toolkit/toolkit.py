from __future__ import annotations

from .browser import NotionBrowserAutomation
from .client import NotionApiClient
from .credentials import resolve_credential
from .internal import NotionInternalClient
from .profiles import WorkspaceProfile, get_profile
from .writer import NotionWriter


class NotionToolkit:
    def __init__(self, profile: WorkspaceProfile):
        self.profile = profile
        token = resolve_credential(profile.api_token)
        token_v2 = resolve_credential(profile.token_v2)
        self.browser = NotionBrowserAutomation(profile)
        self.client: NotionApiClient | None = None
        self.writer: NotionWriter | None = None
        self.internal: NotionInternalClient | None = None
        if token:
            self.client = NotionApiClient(token=token)
            self.writer = NotionWriter(self.client)
        if token_v2 and profile.space_id:
            self.internal = NotionInternalClient(
                token_v2=token_v2,
                space_id=profile.space_id,
                user_id=profile.user_id,
            )

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

    def require_internal(self) -> NotionInternalClient:
        """Get internal API client. Requires token_v2 and space_id in profile."""
        if self.internal is None:
            raise ValueError(
                f"Profile '{self.profile.name}' does not have token_v2 or space_id configured. "
                "Use 'notion-native profile set-internal <name> --token-v2 <token> --space-id <id>' to set up."
            )
        return self.internal
