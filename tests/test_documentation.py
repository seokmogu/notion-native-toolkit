from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from notion_native_toolkit.cli import build_parser
from notion_native_toolkit.profiles import WorkspaceProfile

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTATION = (
    ROOT / "README.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "sdk-reference.md",
    ROOT / "docs" / "authentication.md",
    ROOT / "docs" / "cli-reference.md",
    ROOT / "docs" / "mcp-reference.md",
    ROOT / "docs" / "development.md",
    ROOT / "docs" / "orchestration.md",
)

FENCED_BLOCK = re.compile(
    r"(?ms)^```(?P<language>[^\n]*)\n(?P<source>.*?)^```[ \t]*$"
)
INLINE_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\s*(?:<(?P<bracket>[^>]+)>|(?P<target>[^)\s]+))")


def _python_examples(markdown: str) -> list[str]:
    examples = []
    for match in FENCED_BLOCK.finditer(markdown):
        parts = match.group("language").strip().lower().split(maxsplit=1)
        language = parts[0] if parts else ""
        if language in {"python", "py", "python3"}:
            examples.append(match.group("source"))
    return examples


def _imports_markdown_to_notion_blocks(source: str) -> bool:
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "markdown_to_notion_blocks" for alias in node.names)
        for node in ast.walk(tree)
    )


def _local_link_targets(markdown: str) -> list[str]:
    return [
        match.group("bracket") or match.group("target")
        for match in INLINE_LINK.finditer(markdown)
    ]


def test_readme_is_short_enough_for_a_project_entrypoint() -> None:
    readme = ROOT / "README.md"
    assert len(readme.read_text(encoding="utf-8").splitlines()) <= 200


def test_unlabelled_fences_are_not_python_examples() -> None:
    assert _python_examples("```\narchitecture text\n```\n") == []


def test_documented_profile_json_round_trips_through_actual_schema() -> None:
    markdown = (ROOT / "docs" / "authentication.md").read_text(encoding="utf-8")
    checked = 0
    for block in FENCED_BLOCK.finditer(markdown):
        if block.group("language").strip() != "json":
            continue
        payload = json.loads(block.group("source"))
        for name, values in payload.get("profiles", {}).items():
            profile = WorkspaceProfile.from_dict(name, values)
            assert profile.to_dict() == values
            assert profile.token_v2 is not None
            assert profile.token_v2.kind == "env"
            assert profile.token_v2.value
            checked += 1
    assert checked >= 1


def test_documented_cli_examples_match_the_actual_parser() -> None:
    parser = build_parser()
    checked = 0
    for document in DOCUMENTATION:
        for block in FENCED_BLOCK.finditer(document.read_text(encoding="utf-8")):
            if block.group("language").strip() not in {"bash", "sh", "shell"}:
                continue
            source = block.group("source").replace("\\\n", " ")
            for line in source.splitlines():
                args = shlex.split(line, comments=True)
                if args[:2] == ["uv", "run"]:
                    args = args[2:]
                if not args or args[0] != "notion-native":
                    continue
                checked += 1
                if "--help" in args:
                    continue
                try:
                    parsed = parser.parse_args(args[1:])
                except SystemExit as exc:
                    raise AssertionError(
                        f"Invalid CLI example in {document.name}: {args}"
                    ) from exc
                if parsed.command == "page":
                    assert parsed.yes, f"Page-write example needs --yes: {args}"
    assert checked >= 5


def test_local_markdown_links_in_the_documentation_set_resolve() -> None:
    missing: list[str] = []
    for document in DOCUMENTATION:
        markdown = document.read_text(encoding="utf-8")
        for raw_target in _local_link_targets(markdown):
            parsed = urlsplit(raw_target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (document.parent / unquote(parsed.path)).resolve()
            try:
                target.relative_to(ROOT)
            except ValueError:
                missing.append(f"{document.relative_to(ROOT)} -> {raw_target}")
                continue
            if not target.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {raw_target}")
    assert not missing, "unresolved local Markdown links:\n" + "\n".join(missing)


@pytest.mark.parametrize("document", DOCUMENTATION[1:])
def test_python_fences_in_reference_docs_compile(document: Path) -> None:
    for source in _python_examples(document.read_text(encoding="utf-8")):
        ast.parse(source, filename=str(document))


def test_readme_has_one_executable_markdown_conversion_example() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    candidates = [
        source
        for source in _python_examples(readme)
        if _imports_markdown_to_notion_blocks(source)
        and "heading_2" in source
        and "bulleted_list_item" in source
    ]
    assert len(candidates) == 1
    ast.parse(candidates[0], filename="README.md")

    network_guard = """
import socket
import sys

class NetworkDisabled:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("network access is disabled for README examples")

socket.socket = NetworkDisabled
socket.create_connection = NetworkDisabled
sys.path.insert(0, sys.argv[1])
exec(compile(sys.stdin.read(), "README.md", "exec"), {"__name__": "__main__"})
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", network_guard, str(ROOT / "src")],
        cwd=ROOT,
        input=candidates[0],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['heading_2', 'bulleted_list_item']"
