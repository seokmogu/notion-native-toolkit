from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .credentials import CredentialRef, store_keychain_secret
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
from .toolkit import NotionToolkit


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _profile_or_fail(name: str) -> WorkspaceProfile:
    return get_profile(name)


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
    client = toolkit.require_client()
    writer = toolkit.require_writer()
    markdown_path = Path(args.file)
    content = markdown_path.read_text(encoding="utf-8")
    parent_page_id = args.parent_page_id or toolkit.profile.default_parent_page_id
    if not parent_page_id:
        raise ValueError(
            "A parent page id is required via --parent-page-id or the profile default"
        )
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
    client = toolkit.require_client()
    writer = toolkit.require_writer()
    markdown_path = Path(args.file)
    content = markdown_path.read_text(encoding="utf-8")
    page_id = extract_page_id(args.page_id)
    if args.mode == "native":
        response = client.replace_markdown(page_id, content)
        if response is None:
            raise RuntimeError("Native markdown page update failed")
        _print_json({"page_id": page_id, "mode": args.mode})
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
    page_create.add_argument("--mode", choices=["native", "blocks"], default="native")
    page_create.set_defaults(func=cmd_page_create_from_markdown)

    page_update = page_subparsers.add_parser("update-from-markdown")
    page_update.add_argument("--profile", required=True)
    page_update.add_argument("--page-id", required=True)
    page_update.add_argument("--file", required=True)
    page_update.add_argument("--drop-child-pages", action="store_true")
    page_update.add_argument("--mode", choices=["native", "blocks"], default="native")
    page_update.set_defaults(func=cmd_page_update_from_markdown)

    api_parser = subparsers.add_parser("api")
    api_subparsers = api_parser.add_subparsers(dest="api_command", required=True)

    api_fetch_page = api_subparsers.add_parser("fetch-page")
    api_fetch_page.add_argument("--profile", required=True)
    api_fetch_page.add_argument("--page", required=True)
    api_fetch_page.set_defaults(func=cmd_api_fetch_page)

    api_query_database = api_subparsers.add_parser("query-database")
    api_query_database.add_argument("--profile", required=True)
    api_query_database.add_argument("--database-id", required=True)
    api_query_database.add_argument("--payload")
    api_query_database.set_defaults(func=cmd_api_query_database)

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

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
