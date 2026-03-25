"""Page mapping management for idempotent Notion deployments (FR-04).

Maintains a page_mapping.json file that tracks deployed pages,
enabling URL preservation across re-deployments.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PageEntry:
    """A single page mapping entry."""

    page_id: str
    url: str
    title: str
    last_deployed: str = ""
    content_hash: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageEntry:
        return cls(
            page_id=str(data.get("page_id", "")),
            url=str(data.get("url", "")),
            title=str(data.get("title", "")),
            last_deployed=str(data.get("last_deployed", "")),
            content_hash=str(data.get("content_hash", "")),
        )


@dataclass
class PageMapping:
    """Manages the page_mapping.json file for a deployment directory."""

    entries: dict[str, PageEntry] = field(default_factory=dict)

    def get(self, relative_path: str) -> PageEntry | None:
        return self.entries.get(relative_path)

    def set(
        self,
        relative_path: str,
        page_id: str,
        url: str,
        title: str,
        content_hash: str,
    ) -> PageEntry:
        entry = PageEntry(
            page_id=page_id,
            url=url,
            title=title,
            last_deployed=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
        )
        self.entries[relative_path] = entry
        return entry

    def remove(self, relative_path: str) -> PageEntry | None:
        return self.entries.pop(relative_path, None)

    def list_paths(self) -> list[str]:
        return sorted(self.entries.keys())

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {path: entry.to_dict() for path, entry in sorted(self.entries.items())}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageMapping:
        entries: dict[str, PageEntry] = {}
        for path, entry_data in data.items():
            if isinstance(entry_data, dict):
                entries[path] = PageEntry.from_dict(entry_data)
        return cls(entries=entries)


MAPPING_FILENAME = "page_mapping.json"


def load_mapping(directory: Path) -> PageMapping:
    """Load page_mapping.json from a directory, or return empty mapping."""
    mapping_path = directory / MAPPING_FILENAME
    if not mapping_path.exists():
        return PageMapping()
    try:
        data = json.loads(mapping_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("Invalid page_mapping.json format, starting fresh")
            return PageMapping()
        return PageMapping.from_dict(data)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load page_mapping.json: %s", e)
        return PageMapping()


def save_mapping(directory: Path, mapping: PageMapping) -> Path:
    """Save page_mapping.json to a directory."""
    mapping_path = directory / MAPPING_FILENAME
    mapping_path.write_text(
        json.dumps(mapping.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return mapping_path


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of file content for change detection."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def needs_update(entry: PageEntry | None, content: str) -> bool:
    """Check if a page needs to be updated based on content hash."""
    if entry is None:
        return True
    current_hash = compute_content_hash(content)
    return entry.content_hash != current_hash
