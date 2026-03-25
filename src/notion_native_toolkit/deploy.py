"""Batch deployment engine for Markdown to Notion (FR-04, FR-06).

Deploys single files or directories of Markdown files to Notion pages
with idempotent page mapping and change detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mapping import (
    PageMapping,
    compute_content_hash,
    load_mapping,
    needs_update,
    save_mapping,
)
from .markdown import markdown_to_notion_blocks
from .resolver import resolve_blocks_links
from .writer import NotionWriter

logger = logging.getLogger(__name__)


@dataclass
class DeployResult:
    """Result of a single file deployment."""

    file_path: str
    page_id: str
    url: str
    title: str
    action: str  # "created", "updated", "skipped"
    block_count: int = 0
    pending_links: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DeployReport:
    """Summary of a batch deployment."""

    results: list[DeployResult] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    stale_pages: list[str] = field(default_factory=list)

    @property
    def created(self) -> int:
        return sum(1 for r in self.results if r.action == "created")

    @property
    def updated(self) -> int:
        return sum(1 for r in self.results if r.action == "updated")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.action == "skipped")

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "created": self.created,
                "updated": self.updated,
                "skipped": self.skipped,
                "errors": len(self.errors),
                "stale_pages": len(self.stale_pages),
            },
            "results": [
                {
                    "file": r.file_path,
                    "page_id": r.page_id,
                    "url": r.url,
                    "title": r.title,
                    "action": r.action,
                    "blocks": r.block_count,
                    "pending_links": r.pending_links,
                }
                for r in self.results
            ],
            "errors": self.errors,
            "stale_pages": self.stale_pages,
        }


@dataclass
class Section:
    """A section of a Markdown file split by H1 heading."""

    title: str
    content: str


def split_by_h1(content: str) -> list[Section]:
    """Split Markdown content into sections by H1 headings (FR-05).

    Returns a list of sections. Content before the first H1 becomes
    a section with the filename-derived title (handled by caller).
    """
    import re

    lines = content.split("\n")
    sections: list[Section] = []
    current_title = ""
    current_lines: list[str] = []

    for line in lines:
        match = re.match(r"^#\s+(.+)$", line)
        if match and not line.startswith("## "):
            # Save previous section if it has content
            if current_lines or current_title:
                section_content = "\n".join(current_lines).strip()
                if section_content or current_title:
                    sections.append(Section(title=current_title, content=section_content))
            current_title = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_lines or current_title:
        section_content = "\n".join(current_lines).strip()
        if section_content or current_title:
            sections.append(Section(title=current_title, content=section_content))

    return sections


def _extract_title(content: str, file_path: Path) -> str:
    """Extract title from first H1 heading, or use filename."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return file_path.stem.replace("-", " ").replace("_", " ").title()


def _strip_leading_h1(content: str) -> str:
    """Remove the first H1 heading from markdown content.

    Prevents duplicate title: Notion page title already contains the H1,
    so we strip it from the body content.
    """
    lines = content.split("\n")
    result: list[str] = []
    h1_removed = False
    for line in lines:
        if not h1_removed and line.strip().startswith("# ") and not line.strip().startswith("## "):
            h1_removed = True
            continue
        # Also skip blank lines immediately after the removed H1
        if h1_removed and not result and line.strip() == "":
            continue
        result.append(line)
    return "\n".join(result)


def _collect_md_files(target: Path) -> list[Path]:
    """Collect markdown files from a file or directory."""
    if target.is_file():
        if target.suffix.lower() == ".md":
            return [target]
        return []
    if target.is_dir():
        files = sorted(target.rglob("*.md"))
        return [f for f in files if f.is_file() and not f.name.startswith(".")]
    return []


def deploy_file(
    file_path: Path,
    project_root: Path,
    writer: NotionWriter,
    parent_page_id: str,
    mapping: PageMapping,
    base_url: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    tree: bool = False,
) -> DeployResult:
    """Deploy a single Markdown file to Notion.

    Args:
        file_path: Path to the Markdown file.
        project_root: Root directory for relative path resolution.
        writer: NotionWriter instance for API calls.
        parent_page_id: Notion parent page ID.
        mapping: PageMapping for idempotent deployment.
        base_url: Base URL for resolving relative paths to absolute URLs.
        force: Force re-deploy even if content unchanged.
        dry_run: Convert but don't call Notion API.

    Returns:
        DeployResult with deployment outcome.
    """
    relative_path = str(file_path.relative_to(project_root))
    content = file_path.read_text(encoding="utf-8")
    title = _extract_title(content, file_path)
    content_hash = compute_content_hash(content)
    body_content = _strip_leading_h1(content)

    existing = mapping.get(relative_path)

    # Check if update is needed
    if not force and existing is not None and not needs_update(existing, content):
        return DeployResult(
            file_path=relative_path,
            page_id=existing.page_id,
            url=existing.url,
            title=title,
            action="skipped",
        )

    # FR-05: Tree mode - split by H1 and create sub-pages
    if tree:
        return _deploy_tree(
            file_path=file_path,
            relative_path=relative_path,
            content=content,
            content_hash=content_hash,
            title=title,
            project_root=project_root,
            writer=writer,
            parent_page_id=parent_page_id,
            mapping=mapping,
            base_url=base_url,
            dry_run=dry_run,
            existing=existing,
        )

    # Convert markdown to Notion blocks (H1 stripped to avoid title duplication)
    pending_links: list[dict[str, str]] = []
    blocks, md_pending = markdown_to_notion_blocks(
        body_content,
        source_file_path=str(file_path),
        mapping={"page_mappings": mapping.to_dict()},
        project_root=project_root,
    )
    pending_links.extend(md_pending)

    # Resolve relative links in blocks
    resolve_blocks_links(
        blocks,
        source_file=file_path,
        project_root=project_root,
        mapping=mapping,
        base_url=base_url,
        pending_links=pending_links,
        image_uploader=writer,
    )

    if dry_run:
        action = "would_create" if existing is None else "would_update"
        return DeployResult(
            file_path=relative_path,
            page_id=existing.page_id if existing else "",
            url=existing.url if existing else "",
            title=title,
            action=action,
            block_count=len(blocks),
            pending_links=pending_links,
        )

    if existing is None:
        # Create new page
        created = writer.create_page(
            parent_page_id=parent_page_id,
            title=title,
            blocks=blocks,
        )
        mapping.set(relative_path, created.page_id, created.url, title, content_hash)
        return DeployResult(
            file_path=relative_path,
            page_id=created.page_id,
            url=created.url,
            title=title,
            action="created",
            block_count=len(blocks),
            pending_links=pending_links,
        )
    else:
        # Update existing page (clear + append)
        writer.replace_page_content(existing.page_id, blocks)
        mapping.set(relative_path, existing.page_id, existing.url, title, content_hash)
        return DeployResult(
            file_path=relative_path,
            page_id=existing.page_id,
            url=existing.url,
            title=title,
            action="updated",
            block_count=len(blocks),
            pending_links=pending_links,
        )


def _deploy_landing(
    file_path: Path,
    project_root: Path,
    writer: NotionWriter,
    parent_page_id: str,
    mapping: PageMapping,
    base_url: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> DeployResult:
    """Deploy README.md content directly onto the parent page (landing page).

    Instead of creating a new child page, this writes the content
    directly into the target parent page.
    """
    relative_path = str(file_path.relative_to(project_root))
    content = file_path.read_text(encoding="utf-8")
    title = _extract_title(content, file_path)
    content_hash = compute_content_hash(content)
    body_content = _strip_leading_h1(content)

    existing = mapping.get(relative_path)

    # Check if update is needed
    if not force and existing is not None and not needs_update(existing, content):
        return DeployResult(
            file_path=relative_path,
            page_id=existing.page_id,
            url=existing.url,
            title=title,
            action="skipped",
        )

    # Convert markdown to Notion blocks (H1 stripped to avoid title duplication)
    pending_links: list[dict[str, str]] = []
    blocks, md_pending = markdown_to_notion_blocks(
        body_content,
        source_file_path=str(file_path),
        mapping={"page_mappings": mapping.to_dict()},
        project_root=project_root,
    )
    pending_links.extend(md_pending)

    # Resolve relative links in blocks
    resolve_blocks_links(
        blocks,
        source_file=file_path,
        project_root=project_root,
        mapping=mapping,
        base_url=base_url,
        pending_links=pending_links,
        image_uploader=writer,
    )

    if dry_run:
        return DeployResult(
            file_path=relative_path,
            page_id=parent_page_id,
            url=f"https://www.notion.so/{parent_page_id.replace('-', '')}",
            title=title,
            action="would_update_landing",
            block_count=len(blocks),
            pending_links=pending_links,
        )

    # Collect existing child page IDs before clearing
    existing_children = writer.client.fetch_children(parent_page_id) or []
    child_page_ids = [
        block["id"]
        for block in existing_children
        if block.get("type") == "child_page" and isinstance(block.get("id"), str)
    ]

    # Clear ALL content including child_page blocks (they go to trash)
    writer.replace_page_content(parent_page_id, blocks, preserve_child_pages=False)

    # Restore child pages from trash → they reappear at the bottom
    for cpid in child_page_ids:
        writer.client.call("PATCH", f"pages/{cpid}", {"archived": False})

    # Fetch the page URL
    page = writer.client.fetch_page(parent_page_id)
    url = ""
    if page is not None:
        url_value = page.get("url")
        if isinstance(url_value, str):
            url = url_value

    mapping.set(relative_path, parent_page_id, url, title, content_hash)
    return DeployResult(
        file_path=relative_path,
        page_id=parent_page_id,
        url=url,
        title=title,
        action="landing",
        block_count=len(blocks),
        pending_links=pending_links,
    )


def _deploy_tree(
    file_path: Path,
    relative_path: str,
    content: str,
    content_hash: str,
    title: str,
    project_root: Path,
    writer: NotionWriter,
    parent_page_id: str,
    mapping: PageMapping,
    base_url: str | None,
    dry_run: bool,
    existing: Any,
) -> DeployResult:
    """Deploy a single file in tree mode: split by H1 into sub-pages (FR-05)."""
    sections = split_by_h1(content)

    # If no H1 headings found, fall back to single-page mode
    if len(sections) <= 1:
        pending_links: list[dict[str, str]] = []
        blocks, md_pending = markdown_to_notion_blocks(
            content, source_file_path=str(file_path),
            mapping={"page_mappings": mapping.to_dict()},
            project_root=project_root,
        )
        pending_links.extend(md_pending)
        resolve_blocks_links(
            blocks, source_file=file_path, project_root=project_root,
            mapping=mapping, base_url=base_url, pending_links=pending_links,
            image_uploader=writer,
        )
        if dry_run:
            action = "would_create" if existing is None else "would_update"
            return DeployResult(
                file_path=relative_path,
                page_id=existing.page_id if existing else "",
                url=existing.url if existing else "",
                title=title, action=action,
                block_count=len(blocks), pending_links=pending_links,
            )
        if existing is None:
            created = writer.create_page(parent_page_id=parent_page_id, title=title, blocks=blocks)
            mapping.set(relative_path, created.page_id, created.url, title, content_hash)
            return DeployResult(
                file_path=relative_path, page_id=created.page_id, url=created.url,
                title=title, action="created", block_count=len(blocks), pending_links=pending_links,
            )
        else:
            writer.replace_page_content(existing.page_id, blocks)
            mapping.set(relative_path, existing.page_id, existing.url, title, content_hash)
            return DeployResult(
                file_path=relative_path, page_id=existing.page_id, url=existing.url,
                title=title, action="updated", block_count=len(blocks), pending_links=pending_links,
            )

    # Multiple H1 sections: create parent page + sub-pages
    all_pending: list[dict[str, str]] = []
    total_blocks = 0

    # Create or reuse parent page
    parent_key = relative_path
    parent_existing = mapping.get(parent_key)

    if dry_run:
        action = "would_create" if parent_existing is None else "would_update"
        for section in sections:
            sec_blocks, sec_pending = markdown_to_notion_blocks(
                section.content, source_file_path=str(file_path),
                mapping={"page_mappings": mapping.to_dict()}, project_root=project_root,
            )
            total_blocks += len(sec_blocks)
            all_pending.extend(sec_pending)
        return DeployResult(
            file_path=relative_path,
            page_id=parent_existing.page_id if parent_existing else "",
            url=parent_existing.url if parent_existing else "",
            title=title, action=action,
            block_count=total_blocks, pending_links=all_pending,
        )

    # Create parent page (TOC-like, with links to sub-pages)
    if parent_existing is None:
        parent_created = writer.create_page(
            parent_page_id=parent_page_id, title=title, blocks=[],
        )
        parent_pid = parent_created.page_id
        parent_url = parent_created.url
        mapping.set(parent_key, parent_pid, parent_url, title, content_hash)
    else:
        parent_pid = parent_existing.page_id
        parent_url = parent_existing.url
        writer.clear_page_content(parent_pid, preserve_child_pages=True)
        mapping.set(parent_key, parent_pid, parent_url, title, content_hash)

    # Deploy each section as a sub-page
    for i, section in enumerate(sections):
        sec_title = section.title or f"{title} - Part {i + 1}"
        sec_key = f"{relative_path}#section-{i}"
        sec_existing = mapping.get(sec_key)

        sec_pending: list[dict[str, str]] = []
        sec_blocks, md_pending = markdown_to_notion_blocks(
            section.content, source_file_path=str(file_path),
            mapping={"page_mappings": mapping.to_dict()}, project_root=project_root,
        )
        sec_pending.extend(md_pending)
        resolve_blocks_links(
            sec_blocks, source_file=file_path, project_root=project_root,
            mapping=mapping, base_url=base_url, pending_links=sec_pending,
            image_uploader=writer,
        )
        total_blocks += len(sec_blocks)
        all_pending.extend(sec_pending)

        if sec_existing is None:
            sec_created = writer.create_page(
                parent_page_id=parent_pid, title=sec_title, blocks=sec_blocks,
            )
            mapping.set(sec_key, sec_created.page_id, sec_created.url, sec_title, content_hash)
        else:
            writer.replace_page_content(sec_existing.page_id, sec_blocks)
            mapping.set(sec_key, sec_existing.page_id, sec_existing.url, sec_title, content_hash)

    return DeployResult(
        file_path=relative_path, page_id=parent_pid, url=parent_url,
        title=title, action="created" if parent_existing is None else "updated",
        block_count=total_blocks, pending_links=all_pending,
    )


def _dir_title(dir_path: Path) -> str:
    """Generate a Notion page title from a directory name."""
    name = dir_path.name
    return name.replace("-", " ").replace("_", " ").title()


def _get_or_create_dir_page(
    dir_path: Path,
    project_root: Path,
    parent_page_id: str,
    writer: NotionWriter,
    mapping: PageMapping,
    dry_run: bool = False,
) -> str:
    """Get existing or create new Notion page for a directory.

    Returns the Notion page ID for this directory.
    """
    dir_key = str(dir_path.relative_to(project_root)) + "/"
    existing = mapping.get(dir_key)
    if existing is not None:
        return existing.page_id

    title = _dir_title(dir_path)

    if dry_run:
        return f"dry-run-{dir_key}"

    created = writer.create_page(
        parent_page_id=parent_page_id,
        title=title,
        blocks=[],
    )
    mapping.set(dir_key, created.page_id, created.url, title, "")
    logger.info("DIR_PAGE: %s -> %s", dir_key, created.url)
    return created.page_id


def _deploy_dir(
    dir_path: Path,
    project_root: Path,
    parent_page_id: str,
    writer: NotionWriter,
    mapping: PageMapping,
    report: DeployReport,
    base_url: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    is_root: bool = False,
    landing_filename: str = "readme.md",
) -> None:
    """Deploy a single directory level to Notion (recursive).

    Algorithm (bottom-up for link resolution):
    1. Recurse into subdirectories first (creates their pages + populates mapping)
    2. Deploy MD files in this directory (README excluded)
    3. Deploy README.md as landing (last, so all links are resolvable)
    """
    # Classify immediate contents
    readme_file: Path | None = None
    md_files: list[Path] = []
    subdirs: list[Path] = []

    for item in sorted(dir_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            # Only include directories that contain MD files
            has_md = any(item.rglob("*.md"))
            if has_md:
                subdirs.append(item)
        elif item.is_file() and item.suffix.lower() == ".md":
            if item.name.lower() == landing_filename.lower():
                readme_file = item
            else:
                md_files.append(item)

    # Step 1: Recurse into subdirectories (bottom-up)
    for subdir in subdirs:
        subdir_page_id = _get_or_create_dir_page(
            subdir, project_root, parent_page_id, writer, mapping, dry_run
        )
        _deploy_dir(
            dir_path=subdir,
            project_root=project_root,
            parent_page_id=subdir_page_id,
            writer=writer,
            mapping=mapping,
            report=report,
            base_url=base_url,
            force=force,
            dry_run=dry_run,
            is_root=False,
            landing_filename=landing_filename,
        )

    # Step 2: Deploy MD files (README excluded)
    for md_file in md_files:
        try:
            result = deploy_file(
                file_path=md_file,
                project_root=project_root,
                writer=writer,
                parent_page_id=parent_page_id,
                mapping=mapping,
                base_url=base_url,
                force=force,
                dry_run=dry_run,
            )
            report.results.append(result)
            logger.info("%s: %s -> %s", result.action.upper(), result.file_path, result.url)
        except Exception as e:
            report.errors.append({"file": str(md_file), "error": str(e)})
            logger.error("Failed to deploy %s: %s", md_file, e)

    # Step 2.5: Re-deploy pages that had pending links (now all sibling URLs exist in mapping)
    pages_with_pending = [
        r for r in report.results
        if r.pending_links and r.file_path != (readme_file.name if readme_file else "")
    ]
    if pages_with_pending and not dry_run:
        for result in pages_with_pending:
            try:
                file_path = project_root / result.file_path
                if not file_path.exists():
                    continue
                re_result = deploy_file(
                    file_path=file_path,
                    project_root=project_root,
                    writer=writer,
                    parent_page_id=parent_page_id,
                    mapping=mapping,
                    base_url=base_url,
                    force=True,
                    dry_run=False,
                )
                # Update the result in report
                for i, r in enumerate(report.results):
                    if r.file_path == re_result.file_path:
                        report.results[i] = re_result
                        break
                logger.info("RELINK: %s -> pending=%d", re_result.file_path, len(re_result.pending_links))
            except Exception as e:
                logger.warning("Relink failed for %s: %s", result.file_path, e)

    # Step 3: Deploy README.md as landing (last - all links now resolvable)
    if readme_file is not None:
        try:
            if is_root:
                # Root README → write directly to the target parent page
                result = _deploy_landing(
                    file_path=readme_file,
                    project_root=project_root,
                    writer=writer,
                    parent_page_id=parent_page_id,
                    mapping=mapping,
                    base_url=base_url,
                    force=force,
                    dry_run=dry_run,
                )
            else:
                # Subdir README → write as landing to the directory's Notion page
                result = _deploy_landing(
                    file_path=readme_file,
                    project_root=project_root,
                    writer=writer,
                    parent_page_id=parent_page_id,
                    mapping=mapping,
                    base_url=base_url,
                    force=force,
                    dry_run=dry_run,
                )
            report.results.append(result)
            logger.info("LANDING: %s -> %s", result.file_path, result.url)
        except Exception as e:
            report.errors.append({"file": str(readme_file), "error": str(e)})
            logger.error("Failed to deploy landing %s: %s", readme_file, e)


def deploy(
    target: Path,
    writer: NotionWriter,
    parent_page_id: str,
    base_url: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    tree: bool = False,
    landing_filename: str = "readme.md",
) -> DeployReport:
    """Deploy a file or directory of Markdown files to Notion.

    Automatically detects directory structure and maps it to Notion page hierarchy:
    - Directory → Notion page (container)
    - README.md → Landing content on that page
    - Other .md → Child pages
    - Subdirectories → Nested Notion pages

    Args:
        target: Path to a Markdown file or directory.
        writer: NotionWriter instance.
        parent_page_id: Notion parent page ID for new pages.
        base_url: Base URL for resolving relative paths.
        force: Force re-deploy all files.
        dry_run: Convert without calling Notion API.
        tree: Split single files by H1 into sub-pages.

    Returns:
        DeployReport with results and summary.
    """
    report = DeployReport()
    target = target.resolve()

    # Single file deployment
    if target.is_file():
        project_root = target.parent
        mapping = load_mapping(project_root)
        try:
            result = deploy_file(
                file_path=target,
                project_root=project_root,
                writer=writer,
                parent_page_id=parent_page_id,
                mapping=mapping,
                base_url=base_url,
                force=force,
                dry_run=dry_run,
                tree=tree,
            )
            report.results.append(result)
        except Exception as e:
            report.errors.append({"file": str(target), "error": str(e)})
        if not dry_run:
            save_mapping(project_root, mapping)
        return report

    # Directory deployment - hierarchical by default
    project_root = target
    md_files = _collect_md_files(target)
    if not md_files:
        logger.warning("No markdown files found in %s", target)
        return report

    mapping = load_mapping(project_root)

    # Detect stale pages
    current_relative_paths = set()
    for f in md_files:
        try:
            current_relative_paths.add(str(f.relative_to(project_root)))
        except ValueError:
            pass
    # Also track directory keys
    for f in md_files:
        try:
            rel = f.relative_to(project_root)
            for parent in rel.parents:
                if parent != Path("."):
                    current_relative_paths.add(str(parent) + "/")
        except ValueError:
            pass

    for mapped_path in mapping.list_paths():
        if mapped_path not in current_relative_paths:
            report.stale_pages.append(mapped_path)
            logger.warning("Stale mapping: %s no longer exists", mapped_path)

    # Deploy directory tree (bottom-up recursive)
    _deploy_dir(
        dir_path=target,
        project_root=project_root,
        parent_page_id=parent_page_id,
        writer=writer,
        mapping=mapping,
        report=report,
        base_url=base_url,
        force=force,
        dry_run=dry_run,
        is_root=True,
        landing_filename=landing_filename,
    )

    # Save mapping
    if not dry_run:
        save_mapping(project_root, mapping)
        logger.info("Saved page_mapping.json with %d entries", len(mapping.entries))

    return report
