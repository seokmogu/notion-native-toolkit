"""Relative path resolution for Markdown links and images (FR-03).

Converts relative paths in Markdown to:
1. Notion page URLs (via page_mapping)
2. Absolute URLs (via base_url)
3. Tracks unresolved links as pending
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .mapping import PageMapping

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"}
MARKDOWN_EXTENSION = ".md"


def is_relative_path(url: str) -> bool:
    """Check if a URL is a relative path (not absolute or protocol-based)."""
    if url.startswith(("http://", "https://", "mailto:", "#", "/")):
        return False
    return True


def resolve_relative_link(
    link_target: str,
    source_file: Path,
    project_root: Path,
    mapping: PageMapping | None = None,
    base_url: str | None = None,
    pending_links: list[dict[str, str]] | None = None,
) -> str:
    """Resolve a relative link to an absolute URL.

    Resolution priority (FR-03):
    1. page_mapping.json lookup for .md files
    2. base_url construction for all files
    3. Track as pending if unresolvable
    """
    if not is_relative_path(link_target):
        return link_target

    # Strip anchor for path resolution, preserve for final URL
    anchor = ""
    if "#" in link_target:
        link_target, anchor = link_target.rsplit("#", 1)
        anchor = f"#{anchor}"

    # Resolve to project-relative path
    source_dir = source_file.parent
    target_path = (source_dir / link_target).resolve()
    try:
        relative_path = str(target_path.relative_to(project_root.resolve()))
    except ValueError:
        relative_path = link_target

    target_suffix = Path(link_target).suffix.lower()

    # Priority 1: page_mapping lookup for .md files
    if target_suffix == MARKDOWN_EXTENSION and mapping is not None:
        entry = mapping.get(relative_path)
        if entry is not None and entry.url:
            return entry.url + anchor

    # Priority 2: base_url construction
    if base_url is not None:
        clean_base = base_url.rstrip("/")
        return f"{clean_base}/{relative_path}{anchor}"

    # Priority 3: Track as pending
    if pending_links is not None:
        pending_links.append(
            {
                "source": str(source_file),
                "target": relative_path,
                "original": link_target + anchor,
            }
        )

    return link_target + anchor


def is_image_link(url: str) -> bool:
    """Check if a URL points to an image file."""
    path = url.split("?")[0].split("#")[0]
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def resolve_image_url(
    image_path: str,
    source_file: Path,
    project_root: Path,
    base_url: str | None = None,
) -> tuple[str, Path | None]:
    """Resolve an image path to a URL and local file path.

    Returns:
        (resolved_url, local_path_or_none)
        - If base_url is set, returns (absolute_url, None)
        - If local file exists, returns (original_path, local_path) for upload
        - Otherwise returns (original_path, None)
    """
    if not is_relative_path(image_path):
        return image_path, None

    source_dir = source_file.parent
    local_path = (source_dir / image_path).resolve()

    try:
        relative_path = str(local_path.relative_to(project_root.resolve()))
    except ValueError:
        relative_path = image_path

    if base_url is not None:
        clean_base = base_url.rstrip("/")
        return f"{clean_base}/{relative_path}", None

    if local_path.exists() and local_path.is_file():
        return image_path, local_path

    return image_path, None


def resolve_blocks_links(
    blocks: list[dict[str, Any]],
    source_file: Path,
    project_root: Path,
    mapping: PageMapping | None = None,
    base_url: str | None = None,
    pending_links: list[dict[str, str]] | None = None,
    image_uploader: Any | None = None,
) -> list[dict[str, Any]]:
    """Walk through Notion blocks and resolve relative links in-place.

    Handles:
    - text links in rich_text arrays
    - image blocks with relative URLs
    - local image upload via image_uploader (NotionWriter instance)
    """
    for block in blocks:
        block_type = block.get("type", "")
        payload = block.get(block_type, {})
        if not isinstance(payload, dict):
            continue

        # Resolve rich_text links
        rich_text = payload.get("rich_text", [])
        if isinstance(rich_text, list):
            for item in rich_text:
                if not isinstance(item, dict):
                    continue
                text_payload = item.get("text", {})
                if not isinstance(text_payload, dict):
                    continue
                link = text_payload.get("link")
                if isinstance(link, dict):
                    url = link.get("url", "")
                    if isinstance(url, str) and is_relative_path(url):
                        resolved = resolve_relative_link(
                            url, source_file, project_root,
                            mapping, base_url, pending_links,
                        )
                        link["url"] = resolved

        # Resolve image blocks
        if block_type == "image":
            external = payload.get("external", {})
            if isinstance(external, dict):
                url = external.get("url", "")
                if isinstance(url, str) and is_relative_path(url):
                    resolved_url, local_path = resolve_image_url(
                        url, source_file, project_root, base_url,
                    )
                    if local_path is not None and image_uploader is not None:
                        # Upload local image to Notion
                        try:
                            image_bytes = local_path.read_bytes()
                            upload_id = image_uploader.upload_image(
                                image_bytes, local_path.name
                            )
                            if upload_id:
                                # Replace entire image payload with file_upload format
                                payload.clear()
                                payload["type"] = "file_upload"
                                payload["file_upload"] = {"id": upload_id}
                                logger.info("Uploaded image: %s", local_path.name)
                            else:
                                # Upload failed - convert to caption text
                                caption = payload.get("caption", [])
                                alt = caption[0]["text"]["content"] if caption else local_path.name
                                block["type"] = "paragraph"
                                block["paragraph"] = {
                                    "rich_text": [{"type": "text", "text": {"content": f"[Image: {alt}]"}}]
                                }
                                block.pop("image", None)
                        except Exception as e:
                            logger.warning("Image upload failed for %s: %s", local_path, e)
                            caption = payload.get("caption", [])
                            alt = caption[0]["text"]["content"] if caption else local_path.name
                            block["type"] = "paragraph"
                            block["paragraph"] = {
                                "rich_text": [{"type": "text", "text": {"content": f"[Image: {alt}]"}}]
                            }
                            block.pop("image", None)
                    elif local_path is not None:
                        # No uploader - convert relative image to caption text
                        caption = payload.get("caption", [])
                        alt = caption[0]["text"]["content"] if caption else local_path.name
                        block["type"] = "paragraph"
                        block["paragraph"] = {
                            "rich_text": [{"type": "text", "text": {"content": f"[Image: {alt}]"}}]
                        }
                        block.pop("image", None)
                    else:
                        external["url"] = resolved_url

        # Recurse into children
        children = payload.get("children", [])
        if isinstance(children, list) and children:
            resolve_blocks_links(
                children, source_file, project_root,
                mapping, base_url, pending_links,
            )

    return blocks
