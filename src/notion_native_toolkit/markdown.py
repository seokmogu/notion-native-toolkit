from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mistletoe import Document
from mistletoe.block_token import (
    BlockCode,
    CodeFence,
    Heading,
    List,
    ListItem,
    Paragraph,
    Quote,
    Table,
    TableCell,
    TableRow,
    ThematicBreak,
)
from mistletoe.span_token import Emphasis, InlineCode, LineBreak, Link, RawText, Strong


BLOCKS_NEEDING_SPACING = {"heading_1", "heading_2", "callout", "code"}

NOTION_MAX_TEXT_LENGTH = 2000

# Language-specific comment prefixes for code block chunking (FR-02)
_COMMENT_PREFIX: dict[str, str] = {
    "python": "#",
    "ruby": "#",
    "bash": "#",
    "shell": "#",
    "r": "#",
    "perl": "#",
    "yaml": "#",
    "toml": "#",
    "dockerfile": "#",
    "makefile": "#",
    "javascript": "//",
    "typescript": "//",
    "java": "//",
    "go": "//",
    "rust": "//",
    "c": "//",
    "cpp": "//",
    "csharp": "//",
    "kotlin": "//",
    "swift": "//",
    "dart": "//",
    "scala": "//",
    "php": "//",
    "sql": "--",
    "lua": "--",
    "haskell": "--",
    "html": "<!--",
    "xml": "<!--",
    "css": "/*",
}

_COMMENT_SUFFIX: dict[str, str] = {
    "html": "-->",
    "xml": "-->",
    "css": "*/",
}

# GitHub-style admonition mapping (FR-07)
_ADMONITION_MAP: dict[str, tuple[str, str]] = {
    "NOTE": ("\U0001f4dd", "info"),
    "TIP": ("\U0001f4a1", "info"),
    "WARNING": ("\u26a0\ufe0f", "warning"),
    "CAUTION": ("\u274c", "danger"),
    "IMPORTANT": ("\u2757", "important"),
}

# Extended emoji callout mapping (FR-07)
_EMOJI_CALLOUT_MAP: dict[str, str] = {
    "\U0001f4a1": "default",
    "\u26a0": "warning",
    "\u26a0\ufe0f": "warning",
    "\u2757": "warning",
    "\u274c": "warning",
    "\U0001f4cc": "default",
    "\u2705": "default",
    "\U0001f3af": "default",
    "\U0001f525": "warning",
    "\u2139\ufe0f": "default",
    "\U0001f6a8": "warning",
    "\U0001f4e2": "default",
}


def _chunk_code_block(
    code_content: str, language: str, max_length: int = NOTION_MAX_TEXT_LENGTH
) -> list[dict[str, Any]]:
    """Split a code block that exceeds max_length into multiple blocks with part labels."""
    if len(code_content) <= max_length:
        return [
            {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [
                        {"type": "text", "text": {"content": code_content}}
                    ],
                    "language": language,
                },
            }
        ]

    prefix = _COMMENT_PREFIX.get(language, "#")
    suffix = _COMMENT_SUFFIX.get(language, "")

    lines = code_content.split("\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_length = 0

    for line in lines:
        line_length = len(line) + 1  # +1 for newline
        if current_length + line_length > max_length - 80 and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(line)
        current_length += line_length

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    total = len(chunks)
    blocks: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks, 1):
        label_text = f"Part {i} of {total}"
        if suffix:
            label = f"{prefix} {label_text} {suffix}"
        else:
            label = f"{prefix} {label_text}"
        labeled_content = f"{label}\n{chunk}"
        blocks.append(
            {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [
                        {"type": "text", "text": {"content": labeled_content[:NOTION_MAX_TEXT_LENGTH]}}
                    ],
                    "language": language,
                },
            }
        )
    return blocks


def _sanitize_mermaid(content: str) -> str:
    """Sanitize mermaid diagram content for Notion compatibility."""
    content = re.sub(r'click\s+\w+\s+"[^"]*"', "", content)
    content = re.sub(r"%%\{init:.*?\}%%", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def _make_image_block(url: str, alt_text: str = "") -> dict[str, Any]:
    """Create a Notion image block from a URL (FR-01 P1)."""
    return {
        "object": "block",
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": url},
            "caption": [{"type": "text", "text": {"content": alt_text}}] if alt_text else [],
        },
    }


def _parse_admonition(quote_text: str) -> tuple[bool, str | None, str, str | None]:
    """Detect GitHub-style admonitions like [!NOTE], [!WARNING] etc. (FR-07)."""
    match = re.match(r"^\[!(\w+)\]\s*(.*)", quote_text, re.DOTALL)
    if match:
        admonition_type = match.group(1).upper()
        remaining = match.group(2).strip()
        if admonition_type in _ADMONITION_MAP:
            emoji, kind = _ADMONITION_MAP[admonition_type]
            return True, emoji, remaining, kind
    return False, None, quote_text, None


def extract_page_id(input_str: str) -> str:
    cleaned = input_str.strip()
    if "notion.so" in cleaned:
        compact = cleaned.replace("-", "")
        match = re.search(r"([a-f0-9]{32})", compact)
        if match:
            return match.group(1)
        match = re.search(r"([a-f0-9-]{36})", cleaned)
        if match:
            return match.group(1).replace("-", "")
    return cleaned.replace("-", "")


def resolve_link_path(
    source_file_path: str, link_target: str, project_root: Path
) -> str | None:
    if link_target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if not link_target.endswith(".md"):
        return None
    source_dir = Path(source_file_path).parent
    target_path = (source_dir / link_target).resolve()
    try:
        return str(target_path.relative_to(project_root))
    except ValueError:
        return None


def convert_link_to_notion_url(
    link_target: str,
    link_text: str,
    source_file_path: str,
    mapping: dict[str, Any],
    project_root: Path,
    pending_links: list[dict[str, str]],
) -> str:
    resolved_path = resolve_link_path(source_file_path, link_target, project_root)
    if resolved_path is None:
        return link_target
    page_mappings = mapping.get("page_mappings", {})
    if isinstance(page_mappings, dict) and resolved_path in page_mappings:
        entry = page_mappings[resolved_path]
        if isinstance(entry, dict):
            url = entry.get("url")
            if isinstance(url, str):
                return url
    pending_links.append(
        {
            "from_path": source_file_path,
            "to_path": resolved_path,
            "link_text": link_text,
        }
    )
    return link_target


def extract_text_content(token: Any) -> str:
    if isinstance(token, RawText):
        return token.content
    if hasattr(token, "children"):
        return "".join(extract_text_content(child) for child in token.children)
    return ""


def convert_inline_text(
    token: Any,
    source_file_path: str | None = None,
    mapping: dict[str, Any] | None = None,
    project_root: Path | None = None,
    pending_links: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    rich_text: list[dict[str, Any]] = []
    if isinstance(token, RawText):
        if token.content:
            rich_text.append(
                {"type": "text", "text": {"content": token.content[:2000]}}
            )
    elif isinstance(token, Strong):
        for child in token.children:
            text = extract_text_content(child)
            if text:
                rich_text.append(
                    {
                        "type": "text",
                        "text": {"content": text[:2000]},
                        "annotations": {"bold": True},
                    }
                )
    elif isinstance(token, Emphasis):
        for child in token.children:
            text = extract_text_content(child)
            if text:
                rich_text.append(
                    {
                        "type": "text",
                        "text": {"content": text[:2000]},
                        "annotations": {"italic": True},
                    }
                )
    elif isinstance(token, InlineCode):
        rich_text.append(
            {
                "type": "text",
                "text": {"content": token.children[0].content[:2000]},
                "annotations": {"code": True},
            }
        )
    elif isinstance(token, Link):
        text = extract_text_content(token)
        if text:
            link_url = token.target
            # Anchor-only links (#...) are not supported by Notion - keep text only
            if link_url.startswith("#"):
                rich_text.append(
                    {"type": "text", "text": {"content": text[:2000]}}
                )
            else:
                if (
                    source_file_path
                    and mapping
                    and project_root
                    and pending_links is not None
                ):
                    link_url = convert_link_to_notion_url(
                        token.target,
                        text,
                        source_file_path,
                        mapping,
                        project_root,
                        pending_links,
                    )
                rich_text.append(
                    {
                        "type": "text",
                        "text": {"content": text[:2000], "link": {"url": link_url}},
                    }
                )
    elif isinstance(token, LineBreak):
        rich_text.append({"type": "text", "text": {"content": "\n"}})
    elif hasattr(token, "children"):
        for child in token.children:
            rich_text.extend(
                convert_inline_text(
                    child, source_file_path, mapping, project_root, pending_links
                )
            )
    return rich_text


def is_callout(quote_text: str) -> tuple[bool, str | None, str, str | None]:
    if not quote_text:
        return False, None, quote_text, None

    # 1. GitHub-style admonition: [!NOTE], [!WARNING], etc.
    is_admonition, emoji, text, kind = _parse_admonition(quote_text)
    if is_admonition:
        return True, emoji, text, kind

    # 2. Extended emoji detection (multi-byte emoji first)
    for emoji_key in sorted(_EMOJI_CALLOUT_MAP, key=len, reverse=True):
        if quote_text.startswith(emoji_key):
            remaining = quote_text[len(emoji_key):].lstrip()
            return True, emoji_key, remaining, _EMOJI_CALLOUT_MAP[emoji_key]

    # 3. Single-char symbol callouts
    symbol_map = {
        "!": "default",
        "?": "default",
        ">": "default",
        "*": "default",
        "+": "default",
        "-": "default",
        "~": "default",
        "=": "default",
        ":": "default",
        ";": "default",
        "#": "default",
        "$": "default",
        "%": "default",
        "&": "default",
    }
    first_char = quote_text[0]
    if first_char in symbol_map:
        return True, first_char, quote_text[1:].lstrip(), symbol_map[first_char]

    return False, None, quote_text, None


def _convert_list_items(
    list_token: Any,
    source_file_path: str | None = None,
    mapping: dict[str, Any] | None = None,
    project_root: Path | None = None,
    pending_links: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Convert a List token to Notion blocks, with recursive nested list support (FR-01 P2)."""
    result_blocks: list[dict[str, Any]] = []
    for item in list_token.children:
        if not isinstance(item, ListItem):
            continue
        rich_text: list[dict[str, Any]] = []
        is_checkbox = False
        is_checked = False
        child_blocks: list[dict[str, Any]] = []

        for child in item.children:
            if isinstance(child, Paragraph):
                text_content = extract_text_content(child)
                checkbox_match = re.match(r"^\[([ xX])]\s*(.*)", text_content)
                if checkbox_match:
                    is_checkbox = True
                    is_checked = checkbox_match.group(1).lower() == "x"
                    remaining_text = checkbox_match.group(2)
                    rich_text = [
                        {
                            "type": "text",
                            "text": {"content": remaining_text[:NOTION_MAX_TEXT_LENGTH]},
                        }
                    ]
                else:
                    for inline_child in child.children:
                        rich_text.extend(
                            convert_inline_text(
                                inline_child,
                                source_file_path,
                                mapping,
                                project_root,
                                pending_links,
                            )
                        )
            elif isinstance(child, List):
                # Recursively convert nested lists to children
                child_blocks.extend(
                    _convert_list_items(
                        child, source_file_path, mapping, project_root, pending_links
                    )
                )

        if not rich_text:
            continue

        if is_checkbox:
            block: dict[str, Any] = {
                "object": "block",
                "type": "to_do",
                "to_do": {"rich_text": rich_text, "checked": is_checked},
            }
            if child_blocks:
                block["to_do"]["children"] = child_blocks
        else:
            list_type = (
                "bulleted_list_item"
                if not list_token.start
                else "numbered_list_item"
            )
            block = {
                "object": "block",
                "type": list_type,
                list_type: {"rich_text": rich_text},
            }
            if child_blocks:
                block[list_type]["children"] = child_blocks

        result_blocks.append(block)
    return result_blocks


def markdown_to_notion_blocks(
    markdown_content: str,
    source_file_path: str | None = None,
    mapping: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    document = Document(markdown_content)
    blocks: list[dict[str, Any]] = []
    pending_links: list[dict[str, str]] = []
    for token in document.children:
        block: dict[str, Any] | None = None
        if isinstance(token, Heading):
            level = min(token.level, 3)
            heading_type = f"heading_{level}"
            rich_text: list[dict[str, Any]] = []
            for child in token.children:
                rich_text.extend(
                    convert_inline_text(
                        child, source_file_path, mapping, project_root, pending_links
                    )
                )
            if rich_text:
                block = {
                    "object": "block",
                    "type": heading_type,
                    heading_type: {"rich_text": rich_text},
                }
        elif isinstance(token, (CodeFence, BlockCode)):
            language = getattr(token, "language", "plain text") or "plain text"
            language_map = {
                "cypher": "sql",
                "sh": "bash",
                "yml": "yaml",
                "js": "javascript",
                "ts": "typescript",
                "py": "python",
            }
            code_content = "".join(
                extract_text_content(child) for child in token.children
            )
            mapped_language = language_map.get(language.lower(), language.lower())
            # FR-02: Mermaid sanitization (never split)
            if mapped_language == "mermaid":
                code_content = _sanitize_mermaid(code_content)
                block = {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [
                            {"type": "text", "text": {"content": code_content[:NOTION_MAX_TEXT_LENGTH]}}
                        ],
                        "language": mapped_language,
                    },
                }
            elif len(code_content) > NOTION_MAX_TEXT_LENGTH:
                # FR-02: Split oversized code blocks with part labels
                code_blocks = _chunk_code_block(code_content, mapped_language)
                blocks.extend(code_blocks)
                continue
            else:
                block = {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [
                            {"type": "text", "text": {"content": code_content}}
                        ],
                        "language": mapped_language,
                    },
                }
        elif isinstance(token, Quote):
            # Collect first paragraph as main text, rest as children
            first_paragraph_text: list[dict[str, Any]] = []
            child_blocks: list[dict[str, Any]] = []
            first_para_done = False
            for child in token.children:
                if isinstance(child, Paragraph) and not first_para_done:
                    for inline_child in child.children:
                        first_paragraph_text.extend(
                            convert_inline_text(
                                inline_child,
                                source_file_path,
                                mapping,
                                project_root,
                                pending_links,
                            )
                        )
                    first_para_done = True
                elif isinstance(child, Paragraph):
                    p_rich: list[dict[str, Any]] = []
                    for inline_child in child.children:
                        p_rich.extend(
                            convert_inline_text(
                                inline_child,
                                source_file_path,
                                mapping,
                                project_root,
                                pending_links,
                            )
                        )
                    if p_rich:
                        child_blocks.append(
                            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": p_rich}}
                        )
                elif isinstance(child, List):
                    for item in child.children:
                        if not isinstance(item, ListItem):
                            continue
                        li_rich: list[dict[str, Any]] = []
                        for li_child in item.children:
                            if isinstance(li_child, Paragraph):
                                for ic in li_child.children:
                                    li_rich.extend(
                                        convert_inline_text(ic, source_file_path, mapping, project_root, pending_links)
                                    )
                        if li_rich:
                            list_type = "bulleted_list_item" if not child.start else "numbered_list_item"
                            child_blocks.append(
                                {"object": "block", "type": list_type, list_type: {"rich_text": li_rich}}
                            )
            full_text = "".join(
                item.get("text", {}).get("content", "") for item in first_paragraph_text
            )
            callout, emoji, without_emoji, _kind = is_callout(full_text)
            if callout:
                callout_block: dict[str, Any] = {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [
                            {"type": "text", "text": {"content": without_emoji[:NOTION_MAX_TEXT_LENGTH]}}
                        ],
                        "icon": {"type": "emoji", "emoji": emoji or "\U0001f4a1"},
                    },
                }
                if child_blocks:
                    callout_block["callout"]["children"] = child_blocks
                block = callout_block
            elif first_paragraph_text:
                block = {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": first_paragraph_text},
                }
        elif isinstance(token, List):
            list_blocks = _convert_list_items(
                token, source_file_path, mapping, project_root, pending_links
            )
            blocks.extend(list_blocks)
            continue
        elif isinstance(token, Table):

            def process_table_row(row: Any) -> list[list[dict[str, Any]]]:
                cells: list[list[dict[str, Any]]] = []
                for cell in row.children:
                    if not isinstance(cell, TableCell):
                        continue
                    cell_rich_text: list[dict[str, Any]] = []
                    for child in cell.children:
                        cell_rich_text.extend(
                            convert_inline_text(
                                child,
                                source_file_path,
                                mapping,
                                project_root,
                                pending_links,
                            )
                        )
                    processed: list[dict[str, Any]] = []
                    for item in cell_rich_text:
                        if item.get("type") == "text":
                            content = item.get("text", {}).get("content", "")
                            if isinstance(content, str):
                                item = {
                                    **item,
                                    "text": {
                                        **item["text"],
                                        "content": re.sub(r"<br\s*/?>", "\n", content),
                                    },
                                }
                        processed.append(item)
                    cells.append(
                        processed or [{"type": "text", "text": {"content": ""}}]
                    )
                return cells

            table_rows: list[list[list[dict[str, Any]]]] = []
            table_width = 0
            if getattr(token, "header", None):
                header_cells = process_table_row(token.header)
                if header_cells:
                    table_rows.append(header_cells)
                    table_width = max(table_width, len(header_cells))
            for row in token.children:
                if isinstance(row, TableRow):
                    cells = process_table_row(row)
                    if cells:
                        table_rows.append(cells)
                        table_width = max(table_width, len(cells))
            for row_cells in table_rows:
                while len(row_cells) < table_width:
                    row_cells.append([{"type": "text", "text": {"content": ""}}])
            if table_rows and table_width > 0:
                block = {
                    "object": "block",
                    "type": "table",
                    "table": {
                        "table_width": table_width,
                        "has_column_header": True,
                        "has_row_header": False,
                        "children": [
                            {"type": "table_row", "table_row": {"cells": row_cells}}
                            for row_cells in table_rows
                        ],
                    },
                }
        elif isinstance(token, ThematicBreak):
            block = {"object": "block", "type": "divider", "divider": {}}
        elif isinstance(token, Paragraph):
            # FR-01 P1: Detect image-only paragraphs: ![alt](url)
            if (
                len(token.children) == 1
                and hasattr(token.children[0], "src")
                and hasattr(token.children[0], "title")
            ):
                img_token = token.children[0]
                img_url = getattr(img_token, "src", "")
                img_alt = extract_text_content(img_token) if hasattr(img_token, "children") else ""
                if img_url:
                    block = _make_image_block(img_url, img_alt)
                else:
                    continue
            else:
                rich_text: list[dict[str, Any]] = []
                for child in token.children:
                    rich_text.extend(
                        convert_inline_text(
                            child, source_file_path, mapping, project_root, pending_links
                        )
                    )
                if rich_text:
                    block = {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": rich_text},
                    }
        if block is not None:
            blocks.append(block)
            block_type = block.get("type")
            if isinstance(block_type, str) and block_type in BLOCKS_NEEDING_SPACING:
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": ""}}]
                        },
                    }
                )
    return blocks, pending_links


def rich_text_to_markdown(rich_text: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in rich_text:
        item_type = item.get("type")
        if item_type == "text":
            text_payload = item.get("text", {})
            if not isinstance(text_payload, dict):
                continue
            content = text_payload.get("content", "")
            if not isinstance(content, str):
                continue
            link_payload = text_payload.get("link")
            annotations = item.get("annotations", {})
            if not isinstance(annotations, dict):
                annotations = {}
            text = content
            if annotations.get("code"):
                text = f"`{text}`"
            if annotations.get("bold"):
                text = f"**{text}**"
            if annotations.get("italic"):
                text = f"*{text}*"
            if isinstance(link_payload, dict):
                url = link_payload.get("url")
                if isinstance(url, str):
                    text = f"[{text}]({url})"
            parts.append(text)
        elif item_type == "mention":
            mention = item.get("mention", {})
            if not isinstance(mention, dict):
                continue
            mention_type = mention.get("type")
            if mention_type == "date":
                date_payload = mention.get("date", {})
                if isinstance(date_payload, dict):
                    start = date_payload.get("start")
                    if isinstance(start, str):
                        parts.append(start)
            elif mention_type == "page":
                page_payload = mention.get("page", {})
                if isinstance(page_payload, dict):
                    page_id = page_payload.get("id")
                    if isinstance(page_id, str):
                        parts.append(f"[Page:{page_id}]")
        elif item_type == "equation":
            equation = item.get("equation", {})
            if isinstance(equation, dict):
                expression = equation.get("expression")
                if isinstance(expression, str):
                    parts.append(f"${expression}$")
    return "".join(parts)


def _indent(text: str, prefix: str) -> str:
    return "\n".join(
        prefix + line if line else prefix.rstrip() for line in text.splitlines()
    )


def _table_to_markdown(block: dict[str, Any]) -> str:
    table = block.get("table", {})
    if not isinstance(table, dict):
        return "[Unsupported table]"
    children = table.get("children", [])
    if not isinstance(children, list) or not children:
        return "| |\n|---|"
    rows: list[list[str]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        row_payload = child.get("table_row", {})
        if not isinstance(row_payload, dict):
            continue
        cells = row_payload.get("cells", [])
        if not isinstance(cells, list):
            continue
        row: list[str] = []
        for cell in cells:
            if isinstance(cell, list):
                row.append(
                    rich_text_to_markdown(
                        [item for item in cell if isinstance(item, dict)]
                    )
                )
        rows.append(row)
    if not rows:
        return "| |\n|---|"
    header = rows[0]
    output = [f"| {' | '.join(header)} |", f"|{'|'.join(['---'] * len(header))}|"]
    for row in rows[1:]:
        padded = row + [""] * (len(header) - len(row))
        output.append(f"| {' | '.join(padded)} |")
    return "\n".join(output)


def block_to_markdown(block: dict[str, Any], indent: int = 0) -> str:
    block_type = block.get("type")
    prefix = "  " * indent
    if block_type == "paragraph":
        payload = block.get("paragraph", {})
        if isinstance(payload, dict):
            return f"{prefix}{rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
    if block_type == "heading_1":
        payload = block.get("heading_1", {})
        if isinstance(payload, dict):
            return f"{prefix}# {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
    if block_type == "heading_2":
        payload = block.get("heading_2", {})
        if isinstance(payload, dict):
            return f"{prefix}## {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
    if block_type == "heading_3":
        payload = block.get("heading_3", {})
        if isinstance(payload, dict):
            return f"{prefix}### {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
    if block_type == "bulleted_list_item":
        payload = block.get("bulleted_list_item", {})
        if isinstance(payload, dict):
            lines = [
                f"{prefix}- {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
            ]
            children = payload.get("children", [])
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        child_text = block_to_markdown(child, indent + 1)
                        if child_text:
                            lines.append(child_text)
            return "\n".join(lines)
    if block_type == "numbered_list_item":
        payload = block.get("numbered_list_item", {})
        if isinstance(payload, dict):
            return f"{prefix}1. {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
    if block_type == "to_do":
        payload = block.get("to_do", {})
        if isinstance(payload, dict):
            checked = payload.get("checked", False)
            marker = "x" if checked else " "
            return f"{prefix}- [{marker}] {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
    if block_type == "toggle":
        payload = block.get("toggle", {})
        if isinstance(payload, dict):
            lines = [
                f"{prefix}- {rich_text_to_markdown(payload.get('rich_text', []))}".rstrip()
            ]
            children = payload.get("children", [])
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        child_text = block_to_markdown(child, indent + 1)
                        if child_text:
                            lines.append(child_text)
            return "\n".join(lines)
    if block_type == "code":
        payload = block.get("code", {})
        if isinstance(payload, dict):
            language = payload.get("language", "plain text")
            if not isinstance(language, str):
                language = "plain text"
            code = rich_text_to_markdown(payload.get("rich_text", []))
            return f"{prefix}```{language}\n{code}\n{prefix}```"
    if block_type == "quote":
        payload = block.get("quote", {})
        if isinstance(payload, dict):
            text = rich_text_to_markdown(payload.get("rich_text", []))
            return _indent(text, f"{prefix}> ")
    if block_type == "callout":
        payload = block.get("callout", {})
        if isinstance(payload, dict):
            icon = payload.get("icon", {})
            emoji = "💡"
            if isinstance(icon, dict):
                emoji_value = icon.get("emoji")
                if isinstance(emoji_value, str) and emoji_value:
                    emoji = emoji_value
            text = rich_text_to_markdown(payload.get("rich_text", []))
            lines = [f"{prefix}> {emoji} {text}".rstrip()]
            children = payload.get("children", [])
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        child_text = block_to_markdown(child, indent)
                        if child_text:
                            lines.append(_indent(child_text, f"{prefix}> "))
            return "\n".join(lines)
    if block_type == "divider":
        return f"{prefix}---"
    if block_type == "table":
        return _indent(_table_to_markdown(block), prefix)
    if block_type == "bookmark":
        payload = block.get("bookmark", {})
        if isinstance(payload, dict):
            url = payload.get("url")
            if isinstance(url, str):
                return f"{prefix}[{url}]({url})"
    if block_type == "embed":
        payload = block.get("embed", {})
        if isinstance(payload, dict):
            url = payload.get("url")
            if isinstance(url, str):
                return f"{prefix}[Embed]({url})"
    if block_type == "image":
        payload = block.get("image", {})
        if isinstance(payload, dict):
            external = payload.get("external", {})
            file_payload = payload.get("file", {})
            if isinstance(external, dict) and isinstance(external.get("url"), str):
                return f"{prefix}![image]({external['url']})"
            if isinstance(file_payload, dict) and isinstance(
                file_payload.get("url"), str
            ):
                return f"{prefix}![image]({file_payload['url']})"
    if block_type == "child_page":
        payload = block.get("child_page", {})
        if isinstance(payload, dict):
            title = payload.get("title")
            if isinstance(title, str):
                return f"{prefix}## {title}"
    if block_type == "link_to_page":
        payload = block.get("link_to_page", {})
        if isinstance(payload, dict):
            if payload.get("type") == "page_id" and isinstance(
                payload.get("page_id"), str
            ):
                return f"{prefix}[Linked page](https://www.notion.so/{payload['page_id'].replace('-', '')})"
            if payload.get("type") == "database_id" and isinstance(
                payload.get("database_id"), str
            ):
                return f"{prefix}[Linked database](https://www.notion.so/{payload['database_id'].replace('-', '')})"
    return f"{prefix}[Unsupported block: {block_type}]"


def notion_blocks_to_markdown(
    blocks: list[dict[str, Any]], title: str | None = None
) -> str:
    lines: list[str] = []
    if title:
        lines.extend([f"# {title}", ""])
    for block in blocks:
        text = block_to_markdown(block)
        if text:
            lines.append(text)
    return "\n\n".join(line for line in lines if line is not None).strip() + "\n"
