from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, cast

from .api_capture import capture_api_surface, diff_api_indexes, parse_capture_target
from .credentials import CredentialRef, store_keychain_secret
from .deploy import deploy
from .markdown import (
    extract_page_id,
    markdown_to_notion_blocks,
    notion_blocks_to_markdown,
)
from .profiles import (
    DEFAULT_KEYCHAIN_SERVICE,
    WorkspaceProfile,
    get_profile,
    init_config,
    list_profiles,
    load_config,
    upsert_profile,
)
from .ntn import NotionCliClient
from .repair import RepairOptions, parse_verify_command, run_repair
from .toolkit import NotionToolkit


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_json_object(path: str, option_name: str = "--payload") -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{option_name} must point to a JSON object")
    return cast(dict[str, Any], payload)


def _profile_or_fail(name: str) -> WorkspaceProfile:
    return get_profile(name)


def _official_cli(profile: str | None) -> NotionCliClient:
    if profile:
        return NotionToolkit.from_profile(profile).require_cli()
    return NotionCliClient()


def cmd_profile_init(args: argparse.Namespace) -> int:
    path = init_config(force=args.force)
    print(path)
    return 0


def cmd_profile_list(_args: argparse.Namespace) -> int:
    config = load_config()
    payload = []
    for profile in list_profiles():
        payload.append(
            {
                "name": profile.name,
                "workspace_url": profile.workspace_url,
                "default_parent_page_id": profile.default_parent_page_id,
                "default": profile.name == config.default_profile,
            }
        )
    _print_json(payload)
    return 0


def cmd_profile_show(args: argparse.Namespace) -> int:
    profile = _profile_or_fail(args.name)
    _print_json(profile.to_dict())
    return 0


def cmd_profile_add(args: argparse.Namespace) -> int:
    profile = WorkspaceProfile(
        name=args.name,
        workspace_url=args.workspace_url,
        default_parent_page_id=args.parent_page_id,
        browser_state_path=args.browser_state_path,
        notes=args.notes,
    )
    path = upsert_profile(profile, set_default=args.default)
    print(path)
    return 0


def cmd_profile_set_token(args: argparse.Namespace) -> int:
    profile = _profile_or_fail(args.name)
    if args.env:
        profile.api_token = CredentialRef(kind="env", value=args.env)
    elif args.keychain:
        if not args.value:
            raise ValueError("--value is required with --keychain")
        account = f"{profile.name}.api_token"
        store_keychain_secret(DEFAULT_KEYCHAIN_SERVICE, account, args.value)
        profile.api_token = CredentialRef(
            kind="keychain", service=DEFAULT_KEYCHAIN_SERVICE, account=account
        )
    elif args.value:
        profile.api_token = CredentialRef(kind="plain", value=args.value)
    else:
        raise ValueError("Provide --env, --value, or --keychain with --value")
    path = upsert_profile(profile)
    print(path)
    return 0


def cmd_profile_set_browser_login(args: argparse.Namespace) -> int:
    profile = _profile_or_fail(args.name)
    if args.email_env:
        profile.browser_email = CredentialRef(kind="env", value=args.email_env)
    elif args.email:
        if args.keychain:
            account = f"{profile.name}.browser_email"
            store_keychain_secret(DEFAULT_KEYCHAIN_SERVICE, account, args.email)
            profile.browser_email = CredentialRef(
                kind="keychain", service=DEFAULT_KEYCHAIN_SERVICE, account=account
            )
        else:
            profile.browser_email = CredentialRef(kind="plain", value=args.email)
    if args.password_env:
        profile.browser_password = CredentialRef(kind="env", value=args.password_env)
    elif args.password:
        if args.keychain:
            account = f"{profile.name}.browser_password"
            store_keychain_secret(DEFAULT_KEYCHAIN_SERVICE, account, args.password)
            profile.browser_password = CredentialRef(
                kind="keychain", service=DEFAULT_KEYCHAIN_SERVICE, account=account
            )
        else:
            profile.browser_password = CredentialRef(kind="plain", value=args.password)
    path = upsert_profile(profile)
    print(path)
    return 0


def cmd_markdown_to_blocks(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    content = input_path.read_text(encoding="utf-8")
    blocks, pending_links = markdown_to_notion_blocks(
        content, source_file_path=str(input_path)
    )
    payload = {"blocks": blocks, "pending_links": pending_links}
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        _print_json(payload)
    return 0


def _page_title(page: dict[str, object]) -> str:
    properties = page.get("properties")
    if not isinstance(properties, dict):
        return "Untitled"
    for key in ["title", "Name"]:
        value = properties.get(key)
        if isinstance(value, dict) and value.get("type") == "title":
            title_entries = value.get("title")
            if isinstance(title_entries, list):
                parts: list[str] = []
                for entry in title_entries:
                    if isinstance(entry, dict):
                        plain_text = entry.get("plain_text")
                        if isinstance(plain_text, str):
                            parts.append(plain_text)
                if parts:
                    return "".join(parts)
    return "Untitled"


def _strip_matching_leading_h1(content: str, title: str | None) -> str:
    if not title:
        return content
    lines = content.splitlines()
    if not lines:
        return content
    first = lines[0].strip()
    if first != f"# {title.strip()}":
        return content
    start = 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:]).lstrip("\n")


def _ensure_leading_h1(content: str, title: str | None) -> str:
    if not title:
        return content
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return content
        break
    return f"# {title.strip()}\n\n{content.lstrip()}"


def _parent_page_ref(parent_page_id: str) -> str:
    if parent_page_id.startswith(("page:", "database:", "data-source:")):
        return parent_page_id
    return f"page:{extract_page_id(parent_page_id)}"


def _fetch_block_tree(toolkit: NotionToolkit, block_id: str) -> list[dict[str, object]]:
    client = toolkit.require_client()
    children = client.fetch_children(block_id) or []
    hydrated: list[dict[str, object]] = []
    for child in children:
        block = dict(child)
        if child.get("has_children"):
            child_id = child.get("id")
            if isinstance(child_id, str):
                block["children"] = _fetch_block_tree(toolkit, child_id)
        hydrated.append(block)
    return hydrated


def cmd_markdown_from_page(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    page_id = extract_page_id(args.page)
    page = client.fetch_page(page_id)
    if page is None:
        raise RuntimeError(f"Failed to fetch page {page_id}")
    markdown = client.retrieve_markdown(page_id)
    if markdown is None:
        blocks = _fetch_block_tree(toolkit, page_id)
        markdown = notion_blocks_to_markdown(blocks, title=_page_title(page))
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


def cmd_page_create_from_markdown(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    markdown_path = Path(args.file)
    raw_content = markdown_path.read_text(encoding="utf-8")
    parent_page_id = args.parent_page_id or toolkit.profile.default_parent_page_id
    if not parent_page_id:
        raise ValueError(
            "A parent page id is required via --parent-page-id or the profile default"
        )
    if args.mode == "cli":
        cli = toolkit.require_cli()
        payload = cli.pages_create(
            _parent_page_ref(parent_page_id),
            _ensure_leading_h1(raw_content, args.title),
            json_output=True,
        )
        _print_json(payload)
        return 0

    client = toolkit.require_client()
    writer = toolkit.require_writer()
    content = _strip_matching_leading_h1(raw_content, args.title)
    pending_links: list[dict[str, str]] = []
    if args.mode == "native":
        page = client.create_page_markdown(
            parent_page_id=parent_page_id,
            title=args.title,
            markdown=content,
        )
        if page is None:
            raise RuntimeError("Native markdown page creation failed")
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise RuntimeError("Notion did not return a page id")
        url_value = page.get("url")
        payload = {
            "page_id": page_id,
            "url": url_value if isinstance(url_value, str) else "",
            "title": args.title,
            "pending_links": pending_links,
            "mode": args.mode,
        }
    else:
        blocks, pending_links = markdown_to_notion_blocks(
            content, source_file_path=str(markdown_path)
        )
        created = writer.create_page(
            parent_page_id=parent_page_id, title=args.title, blocks=blocks
        )
        payload = {
            "page_id": created.page_id,
            "url": created.url,
            "title": created.title,
            "pending_links": pending_links,
            "mode": args.mode,
        }
    _print_json(payload)
    return 0


def cmd_page_update_from_markdown(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    markdown_path = Path(args.file)
    raw_content = markdown_path.read_text(encoding="utf-8")
    page_id = extract_page_id(args.page_id)
    if args.mode == "cli":
        cli = toolkit.require_cli()
        payload = cli.pages_edit(
            page_id,
            _ensure_leading_h1(raw_content, args.title),
            allow_deleting_content=args.drop_child_pages,
            json_output=True,
        )
        _print_json(payload)
        return 0

    client = toolkit.require_client()
    writer = toolkit.require_writer()
    content = _strip_matching_leading_h1(raw_content, args.title)
    if args.title:
        updated = client.update_page_title(page_id, args.title)
        if updated is None:
            raise RuntimeError("Failed to update page title")
    if args.mode == "native":
        response = client.replace_markdown(page_id, content)
        if response is None:
            raise RuntimeError("Native markdown page update failed")
        _print_json({"page_id": page_id, "mode": args.mode, "title": args.title})
        return 0
    blocks, pending_links = markdown_to_notion_blocks(
        content, source_file_path=str(markdown_path)
    )
    writer.replace_page_content(
        page_id, blocks, preserve_child_pages=not args.drop_child_pages
    )
    _print_json(
        {
            "page_id": page_id,
            "updated_blocks": len(blocks),
            "pending_links": pending_links,
            "mode": args.mode,
            "title": args.title,
        }
    )
    return 0


def cmd_api_fetch_page(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    page_id = extract_page_id(args.page)
    payload = client.fetch_page(page_id)
    if payload is None:
        raise RuntimeError(f"Failed to fetch page {page_id}")
    _print_json(payload)
    return 0


def cmd_api_create_page(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to create a page without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    response = client.create_page(_load_json_object(args.payload))
    if response is None:
        raise RuntimeError("Failed to create page")
    _print_json(response)
    return 0


def cmd_api_update_page(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to update a page without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    page_id = extract_page_id(args.page_id)
    response = client.update_page(page_id, _load_json_object(args.payload))
    if response is None:
        raise RuntimeError(f"Failed to update page {page_id}")
    _print_json(response)
    return 0


def cmd_api_fetch_block(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_block(extract_page_id(args.block_id))
    if payload is None:
        raise RuntimeError(f"Failed to fetch block {args.block_id}")
    _print_json(payload)
    return 0


def cmd_api_list_block_children(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.fetch_children(extract_page_id(args.block_id))
    if rows is None:
        raise RuntimeError(f"Failed to fetch block children {args.block_id}")
    _print_json(rows)
    return 0


def cmd_api_append_block_children(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to append block children without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    children = json.loads(Path(args.children).read_text(encoding="utf-8"))
    if not isinstance(children, list):
        raise ValueError("--children must point to a JSON array")
    payload = client.append_children(
        extract_page_id(args.block_id),
        children,
        after=extract_page_id(args.after) if args.after else None,
    )
    if payload is None:
        raise RuntimeError(f"Failed to append block children {args.block_id}")
    _print_json(payload)
    return 0


def cmd_api_update_block(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to update a block without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    response = client.update_block(extract_page_id(args.block_id), payload)
    if response is None:
        raise RuntimeError(f"Failed to update block {args.block_id}")
    _print_json(response)
    return 0


def cmd_api_delete_block(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to delete a block without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.delete_block(extract_page_id(args.block_id))
    if payload is None:
        raise RuntimeError(f"Failed to delete block {args.block_id}")
    _print_json(payload)
    return 0


def cmd_api_query_meeting_notes(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    response = client.query_meeting_notes(payload)
    if response is None:
        raise RuntimeError("Meeting notes query failed")
    _print_json(response)
    return 0


def cmd_api_query_database(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = None
    if args.payload:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    rows = client.query_database(extract_page_id(args.database_id), payload=payload)
    if rows is None:
        raise RuntimeError("Database query failed")
    _print_json(rows)
    return 0


def cmd_api_fetch_database(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    database_id = extract_page_id(args.database_id)
    payload = client.fetch_database(database_id)
    if payload is None:
        raise RuntimeError(f"Failed to fetch database {database_id}")
    _print_json(payload)
    return 0


def cmd_api_create_database(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to create a database without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    response = client.create_database(_load_json_object(args.payload))
    if response is None:
        raise RuntimeError("Failed to create database")
    _print_json(response)
    return 0


def cmd_api_update_database(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to update a database without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    database_id = extract_page_id(args.database_id)
    response = client.update_database(database_id, _load_json_object(args.payload))
    if response is None:
        raise RuntimeError(f"Failed to update database {database_id}")
    _print_json(response)
    return 0


def cmd_api_fetch_data_source(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_data_source(extract_page_id(args.data_source_id))
    if payload is None:
        raise RuntimeError(f"Failed to fetch data source {args.data_source_id}")
    _print_json(payload)
    return 0


def cmd_api_query_data_source(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = None
    if args.payload:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    rows = client.query_data_source(
        extract_page_id(args.data_source_id), payload=payload
    )
    if rows is None:
        raise RuntimeError("Data source query failed")
    _print_json(rows)
    return 0


def cmd_api_list_data_source_templates(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.list_data_source_templates(extract_page_id(args.data_source_id))
    if rows is None:
        raise RuntimeError("Data source templates query failed")
    _print_json(rows)
    return 0


def cmd_api_list_comments(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.list_comments(extract_page_id(args.block_id))
    if rows is None:
        raise RuntimeError("Comment list query failed")
    _print_json(rows)
    return 0


def cmd_api_fetch_comment(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_comment(extract_page_id(args.comment_id))
    if payload is None:
        raise RuntimeError(f"Failed to fetch comment {args.comment_id}")
    _print_json(payload)
    return 0


def cmd_api_create_comment(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to create a comment without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.create_comment_markdown(
        args.markdown,
        parent_page_id=extract_page_id(args.parent_page_id)
        if args.parent_page_id
        else None,
        parent_block_id=extract_page_id(args.parent_block_id)
        if args.parent_block_id
        else None,
        discussion_id=args.discussion_id,
    )
    if payload is None:
        raise RuntimeError("Failed to create comment")
    _print_json(payload)
    return 0


def cmd_api_update_comment(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to update a comment without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.update_comment_markdown(
        extract_page_id(args.comment_id),
        args.markdown,
    )
    if payload is None:
        raise RuntimeError(f"Failed to update comment {args.comment_id}")
    _print_json(payload)
    return 0


def cmd_api_delete_comment(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to delete a comment without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.delete_comment(extract_page_id(args.comment_id))
    if payload is None:
        raise RuntimeError(f"Failed to delete comment {args.comment_id}")
    _print_json(payload)
    return 0


def cmd_api_search(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = None
    if args.payload:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    elif args.query:
        payload = {"query": args.query}
    rows = client.search(payload)
    if rows is None:
        raise RuntimeError("Search query failed")
    _print_json(rows)
    return 0


def cmd_api_list_users(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.list_users()
    if rows is None:
        raise RuntimeError("User list query failed")
    _print_json(rows)
    return 0


def cmd_api_fetch_user(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_user(extract_page_id(args.user_id))
    if payload is None:
        raise RuntimeError(f"Failed to fetch user {args.user_id}")
    _print_json(payload)
    return 0


def cmd_api_fetch_bot_user(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_bot_user()
    if payload is None:
        raise RuntimeError("Failed to fetch bot user")
    _print_json(payload)
    return 0


def cmd_api_list_custom_emojis(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.list_custom_emojis()
    if rows is None:
        raise RuntimeError("Custom emoji list query failed")
    _print_json(rows)
    return 0


def cmd_api_fetch_page_property(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_page_property(
        extract_page_id(args.page_id),
        args.property_id,
    )
    if payload is None:
        raise RuntimeError(f"Failed to fetch page property {args.property_id}")
    _print_json(payload)
    return 0


def cmd_api_list_views(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.list_views(
        database_id=extract_page_id(args.database_id) if args.database_id else None,
        data_source_id=extract_page_id(args.data_source_id)
        if args.data_source_id
        else None,
    )
    if rows is None:
        raise RuntimeError("View list query failed")
    _print_json(rows)
    return 0


def cmd_api_fetch_view(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_view(extract_page_id(args.view_id))
    if payload is None:
        raise RuntimeError(f"Failed to fetch view {args.view_id}")
    _print_json(payload)
    return 0


def cmd_api_create_view(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to create a view without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    response = client.create_view(payload)
    if response is None:
        raise RuntimeError("Failed to create view")
    _print_json(response)
    return 0


def cmd_api_update_view(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to update a view without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    response = client.update_view(extract_page_id(args.view_id), payload)
    if response is None:
        raise RuntimeError(f"Failed to update view {args.view_id}")
    _print_json(response)
    return 0


def cmd_api_delete_view(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to delete a view without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.delete_view(extract_page_id(args.view_id))
    if payload is None:
        raise RuntimeError(f"Failed to delete view {args.view_id}")
    _print_json(payload)
    return 0


def cmd_api_create_view_query(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to create a view query without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    response = client.create_view_query(extract_page_id(args.view_id), payload)
    if response is None:
        raise RuntimeError(f"Failed to create view query for {args.view_id}")
    _print_json(response)
    return 0


def cmd_api_fetch_view_query(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.fetch_view_query_results(
        extract_page_id(args.view_id),
        extract_page_id(args.query_id),
    )
    if rows is None:
        raise RuntimeError(f"Failed to fetch view query {args.query_id}")
    _print_json(rows)
    return 0


def cmd_api_delete_view_query(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to delete a view query without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.delete_view_query(
        extract_page_id(args.view_id),
        extract_page_id(args.query_id),
    )
    if payload is None:
        raise RuntimeError(f"Failed to delete view query {args.query_id}")
    _print_json(payload)
    return 0


def cmd_api_list_file_uploads(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    rows = client.list_file_uploads(status=args.status)
    if rows is None:
        raise RuntimeError("File upload list query failed")
    _print_json(rows)
    return 0


def cmd_api_fetch_file_upload(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.fetch_file_upload(extract_page_id(args.upload_id))
    if payload is None:
        raise RuntimeError(f"Failed to fetch file upload {args.upload_id}")
    _print_json(payload)
    return 0


def cmd_api_complete_file_upload(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to complete a file upload without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    payload = client.complete_file_upload(extract_page_id(args.upload_id))
    if payload is None:
        raise RuntimeError(f"Failed to complete file upload {args.upload_id}")
    _print_json(payload)
    return 0


def cmd_api_move_page(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to move a page without explicit --yes")
    toolkit = NotionToolkit.from_profile(args.profile)
    client = toolkit.require_client()
    parent_page_id = (
        extract_page_id(args.parent_page_id) if args.parent_page_id else None
    )
    parent_data_source_id = (
        extract_page_id(args.parent_data_source_id)
        if args.parent_data_source_id
        else None
    )
    payload = client.move_page(
        extract_page_id(args.page_id),
        parent_page_id=parent_page_id,
        parent_data_source_id=parent_data_source_id,
    )
    if payload is None:
        raise RuntimeError(f"Failed to move page {args.page_id}")
    _print_json(payload)
    return 0


def cmd_api_capture(args: argparse.Namespace) -> int:
    targets = [parse_capture_target(value) for value in args.endpoint]
    if args.profile:
        cli = NotionToolkit.from_profile(args.profile).require_cli()
    else:
        cli = NotionCliClient()
    report = capture_api_surface(
        client=cli,
        output_dir=Path(args.output_dir),
        targets=targets,
        include_docs=not args.no_docs,
        include_specs=not args.no_specs,
    )
    _print_json(report.to_dict())
    return 1 if report.errors else 0


def cmd_api_diff(args: argparse.Namespace) -> int:
    old_index = (
        Path(args.old_index)
        if args.old_index
        else Path(args.old_dir) / "api-index.json"
    )
    new_index = (
        Path(args.new_index)
        if args.new_index
        else Path(args.new_dir) / "api-index.json"
    )
    diff = diff_api_indexes(old_index, new_index)
    _print_json(diff.to_dict())
    return 1 if diff.has_changes else 0


def cmd_cli_doctor(args: argparse.Namespace) -> int:
    result = _official_cli(args.profile).doctor()
    _print_json(
        {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    return result.returncode


def cmd_cli_whoami(args: argparse.Namespace) -> int:
    payload = _official_cli(args.profile).whoami(json_output=not args.plain)
    if isinstance(payload, str):
        print(payload, end="")
    else:
        _print_json(payload)
    return 0


def cmd_cli_files_get(args: argparse.Namespace) -> int:
    payload = _official_cli(args.profile).files_get(
        args.upload_id,
        json_output=not args.plain,
    )
    if isinstance(payload, str):
        print(payload, end="")
    else:
        _print_json(payload)
    return 0


def cmd_cli_files_list(args: argparse.Namespace) -> int:
    payload = _official_cli(args.profile).files_list(json_output=not args.plain)
    if isinstance(payload, str):
        print(payload, end="")
    else:
        _print_json(payload)
    return 0


def cmd_cli_page_trash(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to trash a page without explicit --yes")
    result = _official_cli(args.profile).pages_trash(args.page_id, yes=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    return 0


def cmd_browser_login(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    state_path = asyncio.run(toolkit.browser.login(headed=args.headed))
    print(state_path)
    return 0


def cmd_browser_list_teamspaces(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    payload = asyncio.run(toolkit.browser.list_teamspaces(headed=args.headed))
    _print_json(payload)
    return 0


def cmd_browser_create_teamspace(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    asyncio.run(toolkit.browser.create_teamspace(name=args.name, headed=args.headed))
    return 0


def cmd_browser_paste_markdown(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    markdown_text = Path(args.file).read_text(encoding="utf-8")
    asyncio.run(
        toolkit.browser.paste_markdown(
            page_url=args.page_url, markdown_text=markdown_text, headed=args.headed
        )
    )
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    toolkit = NotionToolkit.from_profile(args.profile)
    parent_page_id = args.parent_page_id or toolkit.profile.default_parent_page_id
    if not parent_page_id:
        raise ValueError(
            "A parent page id is required via --parent-page-id or the profile default"
        )
    target = Path(args.target).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Target not found: {target}")

    cli_client = toolkit.require_cli() if args.backend == "cli" else None
    writer = (
        None if args.backend == "cli" and target.is_file() else toolkit.require_writer()
    )

    report = deploy(
        target=target,
        writer=writer,
        parent_page_id=parent_page_id,
        base_url=args.base_url,
        force=args.force,
        dry_run=args.dry_run,
        tree=getattr(args, "tree", False),
        landing_filename=getattr(args, "landing", "readme.md"),
        backend=args.backend,
        cli_client=cli_client,
    )
    _print_json(report.to_dict())
    return 0


def cmd_repair_run(args: argparse.Namespace) -> int:
    report = run_repair(
        RepairOptions(
            repo=Path(args.repo),
            check=args.check,
            verify_command=parse_verify_command(args.verify_command),
            allow_integration=args.allow_integration,
            max_iterations=args.max_iterations,
            codex_model=args.codex_model,
            sandbox=args.sandbox,
            approval_policy=args.approval_policy,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            max_log_chars=args.max_log_chars,
            dry_run=args.dry_run,
        )
    )
    _print_json(report.to_dict(max_chars=args.max_log_chars))
    return 0 if report.success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native Notion toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser("profile")
    profile_subparsers = profile_parser.add_subparsers(
        dest="profile_command", required=True
    )

    profile_init = profile_subparsers.add_parser("init")
    profile_init.add_argument("--force", action="store_true")
    profile_init.set_defaults(func=cmd_profile_init)

    profile_list = profile_subparsers.add_parser("list")
    profile_list.set_defaults(func=cmd_profile_list)

    profile_show = profile_subparsers.add_parser("show")
    profile_show.add_argument("name")
    profile_show.set_defaults(func=cmd_profile_show)

    profile_add = profile_subparsers.add_parser("add")
    profile_add.add_argument("name")
    profile_add.add_argument("--workspace-url")
    profile_add.add_argument("--parent-page-id")
    profile_add.add_argument("--browser-state-path")
    profile_add.add_argument("--notes")
    profile_add.add_argument("--default", action="store_true")
    profile_add.set_defaults(func=cmd_profile_add)

    profile_token = profile_subparsers.add_parser("set-token")
    profile_token.add_argument("name")
    profile_token.add_argument("--value")
    profile_token.add_argument("--env")
    profile_token.add_argument("--keychain", action="store_true")
    profile_token.set_defaults(func=cmd_profile_set_token)

    profile_browser_login = profile_subparsers.add_parser("set-browser-login")
    profile_browser_login.add_argument("name")
    profile_browser_login.add_argument("--email")
    profile_browser_login.add_argument("--password")
    profile_browser_login.add_argument("--email-env")
    profile_browser_login.add_argument("--password-env")
    profile_browser_login.add_argument("--keychain", action="store_true")
    profile_browser_login.set_defaults(func=cmd_profile_set_browser_login)

    markdown_parser = subparsers.add_parser("markdown")
    markdown_subparsers = markdown_parser.add_subparsers(
        dest="markdown_command", required=True
    )

    markdown_to = markdown_subparsers.add_parser("to-blocks")
    markdown_to.add_argument("--input", required=True)
    markdown_to.add_argument("--output")
    markdown_to.set_defaults(func=cmd_markdown_to_blocks)

    markdown_from_page = markdown_subparsers.add_parser("from-page")
    markdown_from_page.add_argument("--profile", required=True)
    markdown_from_page.add_argument("--page", required=True)
    markdown_from_page.add_argument("--output")
    markdown_from_page.set_defaults(func=cmd_markdown_from_page)

    page_parser = subparsers.add_parser("page")
    page_subparsers = page_parser.add_subparsers(dest="page_command", required=True)

    page_create = page_subparsers.add_parser("create-from-markdown")
    page_create.add_argument("--profile", required=True)
    page_create.add_argument("--title", required=True)
    page_create.add_argument("--parent-page-id")
    page_create.add_argument("--file", required=True)
    page_create.add_argument(
        "--mode", choices=["native", "blocks", "cli"], default="blocks"
    )
    page_create.set_defaults(func=cmd_page_create_from_markdown)

    page_update = page_subparsers.add_parser("update-from-markdown")
    page_update.add_argument("--profile", required=True)
    page_update.add_argument("--page-id", required=True)
    page_update.add_argument("--file", required=True)
    page_update.add_argument("--title")
    page_update.add_argument("--drop-child-pages", action="store_true")
    page_update.add_argument(
        "--mode", choices=["native", "blocks", "cli"], default="blocks"
    )
    page_update.set_defaults(func=cmd_page_update_from_markdown)

    api_parser = subparsers.add_parser("api")
    api_subparsers = api_parser.add_subparsers(dest="api_command", required=True)

    api_fetch_page = api_subparsers.add_parser("fetch-page")
    api_fetch_page.add_argument("--profile", required=True)
    api_fetch_page.add_argument("--page", "--page-id", dest="page", required=True)
    api_fetch_page.set_defaults(func=cmd_api_fetch_page)

    api_create_page = api_subparsers.add_parser("create-page")
    api_create_page.add_argument("--profile", required=True)
    api_create_page.add_argument("--payload", required=True)
    api_create_page.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for creating a page",
    )
    api_create_page.set_defaults(func=cmd_api_create_page)

    api_update_page = api_subparsers.add_parser("update-page")
    api_update_page.add_argument("--profile", required=True)
    api_update_page.add_argument("--page-id", required=True)
    api_update_page.add_argument("--payload", required=True)
    api_update_page.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for updating a page",
    )
    api_update_page.set_defaults(func=cmd_api_update_page)

    api_fetch_block = api_subparsers.add_parser("fetch-block")
    api_fetch_block.add_argument("--profile", required=True)
    api_fetch_block.add_argument("--block-id", required=True)
    api_fetch_block.set_defaults(func=cmd_api_fetch_block)

    api_list_block_children = api_subparsers.add_parser("list-block-children")
    api_list_block_children.add_argument("--profile", required=True)
    api_list_block_children.add_argument("--block-id", required=True)
    api_list_block_children.set_defaults(func=cmd_api_list_block_children)

    api_append_block_children = api_subparsers.add_parser("append-block-children")
    api_append_block_children.add_argument("--profile", required=True)
    api_append_block_children.add_argument("--block-id", required=True)
    api_append_block_children.add_argument("--children", required=True)
    api_append_block_children.add_argument("--after")
    api_append_block_children.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for appending block children",
    )
    api_append_block_children.set_defaults(func=cmd_api_append_block_children)

    api_update_block = api_subparsers.add_parser("update-block")
    api_update_block.add_argument("--profile", required=True)
    api_update_block.add_argument("--block-id", required=True)
    api_update_block.add_argument("--payload", required=True)
    api_update_block.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for updating a block",
    )
    api_update_block.set_defaults(func=cmd_api_update_block)

    api_delete_block = api_subparsers.add_parser("delete-block")
    api_delete_block.add_argument("--profile", required=True)
    api_delete_block.add_argument("--block-id", required=True)
    api_delete_block.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for deleting a block",
    )
    api_delete_block.set_defaults(func=cmd_api_delete_block)

    api_query_meeting_notes = api_subparsers.add_parser("query-meeting-notes")
    api_query_meeting_notes.add_argument("--profile", required=True)
    api_query_meeting_notes.add_argument("--payload", required=True)
    api_query_meeting_notes.set_defaults(func=cmd_api_query_meeting_notes)

    api_query_database = api_subparsers.add_parser("query-database")
    api_query_database.add_argument("--profile", required=True)
    api_query_database.add_argument("--database-id", required=True)
    api_query_database.add_argument("--payload")
    api_query_database.set_defaults(func=cmd_api_query_database)

    api_fetch_database = api_subparsers.add_parser("fetch-database")
    api_fetch_database.add_argument("--profile", required=True)
    api_fetch_database.add_argument("--database-id", required=True)
    api_fetch_database.set_defaults(func=cmd_api_fetch_database)

    api_create_database = api_subparsers.add_parser("create-database")
    api_create_database.add_argument("--profile", required=True)
    api_create_database.add_argument("--payload", required=True)
    api_create_database.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for creating a database",
    )
    api_create_database.set_defaults(func=cmd_api_create_database)

    api_update_database = api_subparsers.add_parser("update-database")
    api_update_database.add_argument("--profile", required=True)
    api_update_database.add_argument("--database-id", required=True)
    api_update_database.add_argument("--payload", required=True)
    api_update_database.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for updating a database",
    )
    api_update_database.set_defaults(func=cmd_api_update_database)

    api_fetch_data_source = api_subparsers.add_parser("fetch-data-source")
    api_fetch_data_source.add_argument("--profile", required=True)
    api_fetch_data_source.add_argument("--data-source-id", required=True)
    api_fetch_data_source.set_defaults(func=cmd_api_fetch_data_source)

    api_query_data_source = api_subparsers.add_parser("query-data-source")
    api_query_data_source.add_argument("--profile", required=True)
    api_query_data_source.add_argument("--data-source-id", required=True)
    api_query_data_source.add_argument("--payload")
    api_query_data_source.set_defaults(func=cmd_api_query_data_source)

    api_list_data_source_templates = api_subparsers.add_parser(
        "list-data-source-templates"
    )
    api_list_data_source_templates.add_argument("--profile", required=True)
    api_list_data_source_templates.add_argument("--data-source-id", required=True)
    api_list_data_source_templates.set_defaults(func=cmd_api_list_data_source_templates)

    api_list_comments = api_subparsers.add_parser("list-comments")
    api_list_comments.add_argument("--profile", required=True)
    api_list_comments.add_argument("--block-id", required=True)
    api_list_comments.set_defaults(func=cmd_api_list_comments)

    api_fetch_comment = api_subparsers.add_parser("fetch-comment")
    api_fetch_comment.add_argument("--profile", required=True)
    api_fetch_comment.add_argument("--comment-id", required=True)
    api_fetch_comment.set_defaults(func=cmd_api_fetch_comment)

    api_create_comment = api_subparsers.add_parser("create-comment")
    api_create_comment.add_argument("--profile", required=True)
    api_create_comment_parent = api_create_comment.add_mutually_exclusive_group(
        required=True
    )
    api_create_comment_parent.add_argument("--parent-page-id")
    api_create_comment_parent.add_argument("--parent-block-id")
    api_create_comment_parent.add_argument("--discussion-id")
    api_create_comment.add_argument("--markdown", required=True)
    api_create_comment.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for creating a comment",
    )
    api_create_comment.set_defaults(func=cmd_api_create_comment)

    api_update_comment = api_subparsers.add_parser("update-comment")
    api_update_comment.add_argument("--profile", required=True)
    api_update_comment.add_argument("--comment-id", required=True)
    api_update_comment.add_argument("--markdown", required=True)
    api_update_comment.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for updating a comment",
    )
    api_update_comment.set_defaults(func=cmd_api_update_comment)

    api_delete_comment = api_subparsers.add_parser("delete-comment")
    api_delete_comment.add_argument("--profile", required=True)
    api_delete_comment.add_argument("--comment-id", required=True)
    api_delete_comment.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for deleting a comment",
    )
    api_delete_comment.set_defaults(func=cmd_api_delete_comment)

    api_search = api_subparsers.add_parser("search")
    api_search.add_argument("--profile", required=True)
    api_search.add_argument("--query")
    api_search.add_argument("--payload")
    api_search.set_defaults(func=cmd_api_search)

    api_list_users = api_subparsers.add_parser("list-users")
    api_list_users.add_argument("--profile", required=True)
    api_list_users.set_defaults(func=cmd_api_list_users)

    api_fetch_user = api_subparsers.add_parser("fetch-user")
    api_fetch_user.add_argument("--profile", required=True)
    api_fetch_user.add_argument("--user-id", required=True)
    api_fetch_user.set_defaults(func=cmd_api_fetch_user)

    api_fetch_bot_user = api_subparsers.add_parser("fetch-bot-user")
    api_fetch_bot_user.add_argument("--profile", required=True)
    api_fetch_bot_user.set_defaults(func=cmd_api_fetch_bot_user)

    api_list_custom_emojis = api_subparsers.add_parser("list-custom-emojis")
    api_list_custom_emojis.add_argument("--profile", required=True)
    api_list_custom_emojis.set_defaults(func=cmd_api_list_custom_emojis)

    api_fetch_page_property = api_subparsers.add_parser("fetch-page-property")
    api_fetch_page_property.add_argument("--profile", required=True)
    api_fetch_page_property.add_argument("--page-id", required=True)
    api_fetch_page_property.add_argument("--property-id", required=True)
    api_fetch_page_property.set_defaults(func=cmd_api_fetch_page_property)

    api_list_views = api_subparsers.add_parser("list-views")
    api_list_views.add_argument("--profile", required=True)
    api_list_views.add_argument("--database-id")
    api_list_views.add_argument("--data-source-id")
    api_list_views.set_defaults(func=cmd_api_list_views)

    api_fetch_view = api_subparsers.add_parser("fetch-view")
    api_fetch_view.add_argument("--profile", required=True)
    api_fetch_view.add_argument("--view-id", required=True)
    api_fetch_view.set_defaults(func=cmd_api_fetch_view)

    api_create_view = api_subparsers.add_parser("create-view")
    api_create_view.add_argument("--profile", required=True)
    api_create_view.add_argument("--payload", required=True)
    api_create_view.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for creating a view",
    )
    api_create_view.set_defaults(func=cmd_api_create_view)

    api_update_view = api_subparsers.add_parser("update-view")
    api_update_view.add_argument("--profile", required=True)
    api_update_view.add_argument("--view-id", required=True)
    api_update_view.add_argument("--payload", required=True)
    api_update_view.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for updating a view",
    )
    api_update_view.set_defaults(func=cmd_api_update_view)

    api_delete_view = api_subparsers.add_parser("delete-view")
    api_delete_view.add_argument("--profile", required=True)
    api_delete_view.add_argument("--view-id", required=True)
    api_delete_view.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for deleting a view",
    )
    api_delete_view.set_defaults(func=cmd_api_delete_view)

    api_create_view_query = api_subparsers.add_parser("create-view-query")
    api_create_view_query.add_argument("--profile", required=True)
    api_create_view_query.add_argument("--view-id", required=True)
    api_create_view_query.add_argument("--payload", required=True)
    api_create_view_query.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for creating a view query",
    )
    api_create_view_query.set_defaults(func=cmd_api_create_view_query)

    api_fetch_view_query = api_subparsers.add_parser("fetch-view-query")
    api_fetch_view_query.add_argument("--profile", required=True)
    api_fetch_view_query.add_argument("--view-id", required=True)
    api_fetch_view_query.add_argument("--query-id", required=True)
    api_fetch_view_query.set_defaults(func=cmd_api_fetch_view_query)

    api_delete_view_query = api_subparsers.add_parser("delete-view-query")
    api_delete_view_query.add_argument("--profile", required=True)
    api_delete_view_query.add_argument("--view-id", required=True)
    api_delete_view_query.add_argument("--query-id", required=True)
    api_delete_view_query.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for deleting a view query",
    )
    api_delete_view_query.set_defaults(func=cmd_api_delete_view_query)

    api_list_file_uploads = api_subparsers.add_parser("list-file-uploads")
    api_list_file_uploads.add_argument("--profile", required=True)
    api_list_file_uploads.add_argument(
        "--status",
        choices=["pending", "uploaded", "expired", "failed"],
    )
    api_list_file_uploads.set_defaults(func=cmd_api_list_file_uploads)

    api_fetch_file_upload = api_subparsers.add_parser("fetch-file-upload")
    api_fetch_file_upload.add_argument("--profile", required=True)
    api_fetch_file_upload.add_argument("--upload-id", required=True)
    api_fetch_file_upload.set_defaults(func=cmd_api_fetch_file_upload)

    api_complete_file_upload = api_subparsers.add_parser("complete-file-upload")
    api_complete_file_upload.add_argument("--profile", required=True)
    api_complete_file_upload.add_argument("--upload-id", required=True)
    api_complete_file_upload.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for completing a multipart upload",
    )
    api_complete_file_upload.set_defaults(func=cmd_api_complete_file_upload)

    api_move_page = api_subparsers.add_parser("move-page")
    api_move_page.add_argument("--profile", required=True)
    api_move_page.add_argument("--page-id", required=True)
    api_move_page_parent = api_move_page.add_mutually_exclusive_group(required=True)
    api_move_page_parent.add_argument("--parent-page-id")
    api_move_page_parent.add_argument("--parent-data-source-id")
    api_move_page.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for moving a page",
    )
    api_move_page.set_defaults(func=cmd_api_move_page)

    api_capture = api_subparsers.add_parser(
        "capture",
        help="Capture the official ntn API index, docs, and reduced specs",
    )
    api_capture.add_argument(
        "--profile",
        help="Optional profile whose API token should be forwarded to ntn",
    )
    api_capture.add_argument(
        "--output-dir",
        default="docs/notion-api-capture",
        help="Directory for capture artifacts (default: docs/notion-api-capture)",
    )
    api_capture.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help=(
            "Endpoint to capture, repeatable. Formats: "
            "'POST:v1/comments', 'v1/comments:POST', or 'POST v1/comments'."
        ),
    )
    api_capture.add_argument(
        "--no-docs",
        action="store_true",
        help="Skip `ntn api <path> --docs` captures",
    )
    api_capture.add_argument(
        "--no-specs",
        action="store_true",
        help="Skip `ntn api <path> --spec` captures",
    )
    api_capture.set_defaults(func=cmd_api_capture)

    api_diff = api_subparsers.add_parser(
        "diff",
        help="Compare two captured official API indexes",
    )
    api_diff_old = api_diff.add_mutually_exclusive_group(required=True)
    api_diff_old.add_argument("--old-dir", help="Directory with old api-index.json")
    api_diff_old.add_argument("--old-index", help="Old api-index.json file")
    api_diff_new = api_diff.add_mutually_exclusive_group(required=True)
    api_diff_new.add_argument("--new-dir", help="Directory with new api-index.json")
    api_diff_new.add_argument("--new-index", help="New api-index.json file")
    api_diff.set_defaults(func=cmd_api_diff)

    cli_parser = subparsers.add_parser(
        "cli",
        help="Run selected official ntn CLI-backed utilities",
    )
    cli_subparsers = cli_parser.add_subparsers(dest="cli_command", required=True)

    cli_doctor = cli_subparsers.add_parser("doctor")
    cli_doctor.add_argument(
        "--profile",
        help="Optional profile whose API token should be forwarded to ntn",
    )
    cli_doctor.set_defaults(func=cmd_cli_doctor)

    cli_whoami = cli_subparsers.add_parser("whoami")
    cli_whoami.add_argument(
        "--profile",
        help="Optional profile whose API token should be forwarded to ntn",
    )
    cli_whoami.add_argument("--plain", action="store_true")
    cli_whoami.set_defaults(func=cmd_cli_whoami)

    cli_files_get = cli_subparsers.add_parser("files-get")
    cli_files_get.add_argument(
        "--profile",
        help="Optional profile whose API token should be forwarded to ntn",
    )
    cli_files_get.add_argument("--upload-id", required=True)
    cli_files_get.add_argument("--plain", action="store_true")
    cli_files_get.set_defaults(func=cmd_cli_files_get)

    cli_files_list = cli_subparsers.add_parser("files-list")
    cli_files_list.add_argument(
        "--profile",
        help="Optional profile whose API token should be forwarded to ntn",
    )
    cli_files_list.add_argument("--plain", action="store_true")
    cli_files_list.set_defaults(func=cmd_cli_files_list)

    cli_page_trash = cli_subparsers.add_parser("page-trash")
    cli_page_trash.add_argument("--profile", required=True)
    cli_page_trash.add_argument("--page-id", required=True)
    cli_page_trash.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation; forwards --yes to ntn pages trash",
    )
    cli_page_trash.set_defaults(func=cmd_cli_page_trash)

    browser_parser = subparsers.add_parser("browser")
    browser_subparsers = browser_parser.add_subparsers(
        dest="browser_command", required=True
    )

    browser_login = browser_subparsers.add_parser("login")
    browser_login.add_argument("--profile", required=True)
    browser_login.add_argument("--headed", action="store_true")
    browser_login.set_defaults(func=cmd_browser_login)

    browser_list = browser_subparsers.add_parser("list-teamspaces")
    browser_list.add_argument("--profile", required=True)
    browser_list.add_argument("--headed", action="store_true")
    browser_list.set_defaults(func=cmd_browser_list_teamspaces)

    browser_create = browser_subparsers.add_parser("create-teamspace")
    browser_create.add_argument("--profile", required=True)
    browser_create.add_argument("--name", required=True)
    browser_create.add_argument("--headed", action="store_true")
    browser_create.set_defaults(func=cmd_browser_create_teamspace)

    browser_paste = browser_subparsers.add_parser("paste-markdown")
    browser_paste.add_argument("--profile", required=True)
    browser_paste.add_argument("--page-url", required=True)
    browser_paste.add_argument("--file", required=True)
    browser_paste.add_argument("--headed", action="store_true")
    browser_paste.set_defaults(func=cmd_browser_paste_markdown)

    # deploy subcommand (FR-09)
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy Markdown files to Notion pages",
    )
    deploy_parser.add_argument(
        "target",
        help="Markdown file or directory to deploy",
    )
    deploy_parser.add_argument(
        "--profile",
        default=None,
        help="Workspace profile name (default: default profile)",
    )
    deploy_parser.add_argument(
        "--parent-page-id",
        help="Notion parent page ID (default: profile setting)",
    )
    deploy_parser.add_argument(
        "--base-url",
        help="Base URL for resolving relative paths (e.g., GitHub raw URL)",
    )
    deploy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Convert and show results without calling Notion API",
    )
    deploy_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-deploy all files ignoring content hash",
    )
    deploy_parser.add_argument(
        "--tree",
        action="store_true",
        help="Split by H1 headings into separate sub-pages",
    )
    deploy_parser.add_argument(
        "--landing",
        default="readme.md",
        help="Landing page filename (default: readme.md)",
    )
    deploy_parser.add_argument(
        "--backend",
        choices=["blocks", "cli"],
        default="blocks",
        help="Page content writer backend (default: blocks)",
    )
    deploy_parser.set_defaults(func=cmd_deploy)

    repair_parser = subparsers.add_parser(
        "repair",
        help="Run a Codex-backed self-repair loop for this repository",
    )
    repair_subparsers = repair_parser.add_subparsers(
        dest="repair_command",
        required=True,
    )

    repair_run = repair_subparsers.add_parser(
        "run",
        help="Run verification, invoke Codex on failure, then re-verify",
    )
    repair_run.add_argument(
        "--repo",
        default=".",
        help="Repository root to repair (default: current directory)",
    )
    repair_run.add_argument(
        "--check",
        choices=["unit", "all", "integration"],
        default="unit",
        help="Built-in verification command to run (default: unit)",
    )
    repair_run.add_argument(
        "--verify-command",
        help="Custom verification command, parsed with shell-like quoting",
    )
    repair_run.add_argument(
        "--allow-integration",
        action="store_true",
        help="Allow integration checks that can hit the real Notion API",
    )
    repair_run.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum Codex repair attempts after the initial check (default: 3)",
    )
    repair_run.add_argument(
        "--codex-model",
        help="Optional explicit Codex model. Omit to inherit Codex/OMX defaults.",
    )
    repair_run.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="workspace-write",
        help="Codex sandbox mode for repair attempts (default: workspace-write)",
    )
    repair_run.add_argument(
        "--approval-policy",
        choices=["untrusted", "on-failure", "on-request", "never"],
        default="never",
        help="Codex approval policy for non-interactive repair (default: never)",
    )
    repair_run.add_argument(
        "--output-dir",
        default=".omc/repair",
        help="Directory for JSON repair reports (default: .omc/repair)",
    )
    repair_run.add_argument(
        "--max-log-chars",
        type=int,
        default=20000,
        help="Maximum stdout/stderr characters stored per command (default: 20000)",
    )
    repair_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Codex execution but still run verification and write a report",
    )
    repair_run.set_defaults(func=cmd_repair_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
