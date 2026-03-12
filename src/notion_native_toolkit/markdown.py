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
    callout_map = {
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
        "💡": "default",
        "⚠": "warning",
        "❗": "warning",
        "📌": "default",
        "✅": "default",
        "❌": "warning",
        "🎯": "default",
        "🔥": "warning",
    }
    if quote_text:
        first_char = quote_text[0]
        if first_char in callout_map:
            return True, first_char, quote_text[1:].lstrip(), callout_map[first_char]
    return False, None, quote_text, None


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
            block = {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [
                        {"type": "text", "text": {"content": code_content[:2000]}}
                    ],
                    "language": mapped_language,
                },
            }
        elif isinstance(token, Quote):
            rich_text: list[dict[str, Any]] = []
            for child in token.children:
                if isinstance(child, Paragraph):
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
            full_text = "".join(
                item.get("text", {}).get("content", "") for item in rich_text
            )
            callout, emoji, without_emoji, _kind = is_callout(full_text)
            if callout:
                block = {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [
                            {"type": "text", "text": {"content": without_emoji[:2000]}}
                        ],
                        "icon": {"type": "emoji", "emoji": emoji or "💡"},
                    },
                }
            elif rich_text:
                block = {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": rich_text},
                }
        elif isinstance(token, List):
            for item in token.children:
                if not isinstance(item, ListItem):
                    continue
                rich_text: list[dict[str, Any]] = []
                is_checkbox = False
                is_checked = False
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
                                    "text": {"content": remaining_text[:2000]},
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
                if not rich_text:
                    continue
                if is_checkbox:
                    blocks.append(
                        {
                            "object": "block",
                            "type": "to_do",
                            "to_do": {"rich_text": rich_text, "checked": is_checked},
                        }
                    )
                else:
                    list_type = (
                        "bulleted_list_item"
                        if not token.start
                        else "numbered_list_item"
                    )
                    blocks.append(
                        {
                            "object": "block",
                            "type": list_type,
                            list_type: {"rich_text": rich_text},
                        }
                    )
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
