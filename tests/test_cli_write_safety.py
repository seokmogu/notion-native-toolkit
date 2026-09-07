from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any

import pytest

from notion_native_toolkit import cli


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (
            cli.cmd_page_create_from_markdown,
            lambda mode: Namespace(
                yes=False,
                profile="test",
                file="missing.md",
                parent_page_id=None,
                title="Title",
                mode=mode,
            ),
        ),
        (
            cli.cmd_page_update_from_markdown,
            lambda mode: Namespace(
                yes=False,
                profile="test",
                file="missing.md",
                page_id="page-id",
                title=None,
                drop_child_pages=False,
                mode=mode,
            ),
        ),
    ],
)
@pytest.mark.parametrize("mode", ["native", "blocks", "cli"])
def test_page_markdown_write_rejects_without_yes_before_profile_or_file_access(
    monkeypatch: pytest.MonkeyPatch,
    command: Any,
    args: Any,
    mode: str,
) -> None:
    calls: list[str] = []

    def fail_profile(_name: str) -> None:
        calls.append("profile")
        raise AssertionError("profile must not be loaded")

    def fail_read_text(_path: object, **_kwargs: object) -> str:
        calls.append("file")
        raise AssertionError("markdown file must not be read")

    monkeypatch.setattr(cli.NotionToolkit, "from_profile", fail_profile)
    monkeypatch.setattr(cli.Path, "read_text", fail_read_text)

    with pytest.raises(ValueError, match="without explicit --yes"):
        command(args(mode))

    assert calls == []


def test_page_markdown_parser_requires_explicit_yes_and_preserves_defaults() -> None:
    parser = cli.build_parser()

    create = parser.parse_args(
        [
            "page",
            "create-from-markdown",
            "--profile",
            "test",
            "--title",
            "Title",
            "--file",
            "page.md",
            "--yes",
        ]
    )
    update = parser.parse_args(
        [
            "page",
            "update-from-markdown",
            "--profile",
            "test",
            "--page-id",
            "page-id",
            "--file",
            "page.md",
        ]
    )

    assert create.yes is True
    assert create.mode == "blocks"
    assert update.yes is False
    assert update.mode == "blocks"
    assert update.drop_child_pages is False


class _FakeCli:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def pages_create(self, parent: str, markdown: str, *, json_output: bool) -> dict[str, str]:
        self.calls.append(("cli-create", (parent, markdown, json_output)))
        return {"id": "created"}

    def pages_edit(
        self,
        page_id: str,
        markdown: str,
        *,
        allow_deleting_content: bool,
        json_output: bool,
    ) -> dict[str, str]:
        self.calls.append(
            (
                "cli-update",
                (page_id, markdown, allow_deleting_content, json_output),
            )
        )
        return {"id": page_id}


class _FakeClient:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def create_page_markdown(
        self, *, parent_page_id: str, title: str, markdown: str
    ) -> dict[str, str]:
        self.calls.append(("native-create", (parent_page_id, title, markdown)))
        return {"id": "created", "url": "https://example.test/created"}

    def update_page_title(self, page_id: str, title: str) -> dict[str, str]:
        self.calls.append(("title", (page_id, title)))
        return {"id": page_id}

    def replace_markdown(self, page_id: str, markdown: str) -> dict[str, str]:
        self.calls.append(("native-update", (page_id, markdown)))
        return {"id": page_id}


class _FakeWriter:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def create_page(
        self, *, parent_page_id: str, title: str, blocks: list[dict[str, object]]
    ) -> SimpleNamespace:
        self.calls.append(("blocks-create", (parent_page_id, title, blocks)))
        return SimpleNamespace(
            page_id="created", url="https://example.test/created", title=title
        )

    def replace_page_content(
        self,
        page_id: str,
        blocks: list[dict[str, object]],
        *,
        preserve_child_pages: bool,
    ) -> None:
        self.calls.append(("blocks-update", (page_id, blocks, preserve_child_pages)))


@pytest.mark.parametrize("mode", ["native", "blocks", "cli"])
def test_page_create_from_markdown_dispatches_with_yes_using_fakes(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    calls: list[tuple[str, object]] = []
    fake_toolkit = SimpleNamespace(
        profile=SimpleNamespace(default_parent_page_id="parent-id"),
        require_cli=lambda: _FakeCli(calls),
        require_client=lambda: _FakeClient(calls),
        require_writer=lambda: _FakeWriter(calls),
    )
    monkeypatch.setattr(
        cli.NotionToolkit, "from_profile", lambda _name: fake_toolkit
    )
    monkeypatch.setattr(cli.Path, "read_text", lambda _path, **_kwargs: "Body")
    monkeypatch.setattr(
        cli,
        "markdown_to_notion_blocks",
        lambda *_args, **_kwargs: ([{"type": "paragraph"}], []),
    )

    assert (
        cli.cmd_page_create_from_markdown(
            Namespace(
                yes=True,
                profile="test",
                file="page.md",
                parent_page_id=None,
                title="Title",
                mode=mode,
            )
        )
        == 0
    )

    assert calls[0][0] == f"{mode}-create"


@pytest.mark.parametrize("mode", ["native", "blocks", "cli"])
def test_page_update_from_markdown_dispatches_with_yes_using_fakes(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    calls: list[tuple[str, object]] = []
    fake_toolkit = SimpleNamespace(
        profile=SimpleNamespace(default_parent_page_id="parent-id"),
        require_cli=lambda: _FakeCli(calls),
        require_client=lambda: _FakeClient(calls),
        require_writer=lambda: _FakeWriter(calls),
    )
    monkeypatch.setattr(
        cli.NotionToolkit, "from_profile", lambda _name: fake_toolkit
    )
    monkeypatch.setattr(cli.Path, "read_text", lambda _path, **_kwargs: "Body")
    monkeypatch.setattr(
        cli,
        "markdown_to_notion_blocks",
        lambda *_args, **_kwargs: ([{"type": "paragraph"}], []),
    )

    assert (
        cli.cmd_page_update_from_markdown(
            Namespace(
                yes=True,
                profile="test",
                file="page.md",
                page_id="page-id",
                title=None,
                drop_child_pages=False,
                mode=mode,
            )
        )
        == 0
    )

    assert calls[0][0] == f"{mode}-update"
