from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from notion_native_toolkit.local_context import (
    DEFAULT_CODEX_ROOT,
    DEFAULT_PROJECT_ROOT,
    ContextScope,
    ContextScopeError,
)


@pytest.fixture()
def scope(tmp_path: Path) -> ContextScope:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "AGENTS.md").write_text("# Root guidance\n")
    repo = project_root / "demo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Demo guidance\n")
    (repo / "app.py").write_text("API_KEY=super-secret\nprint('hello')\n")
    (repo / ".env").write_text("TOKEN=secret\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "ignored.js").write_text("needle\n")

    codex_root = tmp_path / "codex"
    skills_root = codex_root / "skills" / "notion-native-toolkit"
    skills_root.mkdir(parents=True)
    (codex_root / "AGENTS.md").write_text("# Global guidance\n")
    (skills_root / "SKILL.md").write_text("# Skill guidance\n")
    return ContextScope(project_root=project_root, codex_root=codex_root)


def test_manifest_lists_projects_and_allowlisted_skills(scope: ContextScope) -> None:
    manifest = scope.get_scope_manifest()
    assert manifest["projects"] == [
        {"id": "demo", "has_agents": True, "is_git_repository": False}
    ]
    assert manifest["skills"] == ["notion-native-toolkit"]
    assert manifest["scope"] == scope.scope_identity()
    assert manifest["scope"]["mode"] == "custom"


def test_fixture_identity_is_explicit(scope: ContextScope) -> None:
    fixture = ContextScope(scope.project_root, scope.codex_root, scope_mode="fixture")
    identity = fixture.get_scope_manifest()["scope"]
    assert identity["mode"] == "fixture"
    assert identity["project_root"] == str(scope.project_root)
    assert identity["codex_instruction_root"] == str(scope.codex_root)
    assert identity["read_only"] is True


def test_arbitrary_roots_cannot_claim_approved_mode(scope: ContextScope) -> None:
    with pytest.raises(ContextScopeError, match="fixed approved roots"):
        ContextScope(scope.project_root, scope.codex_root, scope_mode="approved-projects")


def test_approved_identity_reports_fixed_roots_without_reading_them() -> None:
    scope = ContextScope(scope_mode="approved-projects")
    identity = scope.scope_identity()
    assert identity["mode"] == "approved-projects"
    assert identity["project_root"] == str(DEFAULT_PROJECT_ROOT)
    assert identity["codex_instruction_root"] == str(DEFAULT_CODEX_ROOT)
    assert identity["read_only"] is True
    with pytest.raises(ContextScopeError, match="relative path"):
        scope.read_project_excerpt("/project/README.md")


@pytest.mark.parametrize("mode", ["fixture", "unknown"])
def test_default_real_roots_reject_false_fixture_or_unknown_mode(mode: str) -> None:
    with pytest.raises(ContextScopeError):
        ContextScope(scope_mode=mode)


def test_agent_guidance_collects_root_to_target(scope: ContextScope) -> None:
    result = scope.read_agent_guidance("demo/app.py")
    assert result["path"] == "demo/app.py"
    assert [item["path"] for item in result["guidance"]] == [
        "AGENTS.md",
        "demo/AGENTS.md",
    ]


def test_read_skill_and_global_guidance(scope: ContextScope) -> None:
    assert scope.read_global_agent_guidance()["content"] == "# Global guidance\n"
    assert scope.read_skill("notion-native-toolkit")["content"] == "# Skill guidance\n"
    with pytest.raises(ContextScopeError, match="static instruction allowlist"):
        scope.read_skill("demo-skill")


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "demo/.env"])
def test_rejects_paths_outside_or_excluded_from_scope(
    scope: ContextScope, path: str
) -> None:
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt(path)


def test_rejects_symlink_escape(scope: ContextScope, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (scope.project_root / "demo" / "escape").symlink_to(outside)
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/escape")


def test_excerpt_redacts_secret_assignments(scope: ContextScope) -> None:
    excerpt = scope.read_project_excerpt("demo/app.py")
    assert "super-secret" not in excerpt["content"]
    assert "API_KEY=[REDACTED]" in excerpt["content"]


def test_search_ignores_env_and_dependency_directories(scope: ContextScope) -> None:
    result = scope.search_project("needle")
    assert result["matches"] == []


def test_excerpt_limit_is_enforced(scope: ContextScope) -> None:
    with pytest.raises(ContextScopeError, match="line limit"):
        scope.read_project_excerpt("demo/app.py", 1, 999)


def test_instruction_parent_symlink_cannot_escape(scope, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    (external / "SKILL.md").write_text("DO_NOT_EXPOSE")
    parent = scope.codex_root / "skills" / "prd-reviewer"
    parent.symlink_to(external, target_is_directory=True)
    with pytest.raises(ContextScopeError):
        scope.read_skill("prd-reviewer")


@pytest.mark.parametrize(
    "path",
    ["demo//app.py", "demo/./app.py", "demo/%2e%2e/app.py", "demo/../demo/app.py"],
)
def test_rejects_ambiguous_path_spelling(scope, path):
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt(path)


@pytest.mark.parametrize(
    "name",
    [
        "auth.json",
        "cookies.json",
        "storage_state.json",
        "credentials.json",
        ".codex/auth.json",
    ],
)
def test_sensitive_filenames_rejected(scope, name):
    target = scope.project_root / "demo" / name
    target.parent.mkdir(exist_ok=True)
    target.write_text('{"value": "DO_NOT_EXPOSE"}')
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/" + name)


def test_redaction_happens_before_excerpt_and_search(scope):
    (scope.project_root / "demo" / "data.py").write_text(
        '"""\n-----BEGIN PRIVATE KEY-----\nDO_NOT_EXPOSE\n-----END PRIVATE KEY-----\n"""\n'
    )
    assert (
        "DO_NOT_EXPOSE"
        not in scope.read_project_excerpt("demo/data.py", 3, 3)["content"]
    )
    assert scope.search_project("DO_NOT_EXPOSE", "demo")["matches"] == []


def test_search_treats_cli_option_as_literal(scope):
    (scope.project_root / "demo" / "app.py").write_text("--hidden\n")
    matches = scope.search_project("--hidden", "demo")["matches"]
    assert len(matches) == 1
    assert matches[0]["text"] == "--hidden"


def test_large_single_line_is_not_an_unbounded_response(scope):
    (scope.project_root / "demo" / "long.txt").write_text("x" * 100_000)
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/long.txt", 1, 1)


def test_git_status_reports_rename_and_hidden_change(scope):
    repo = scope.project_root / "demo"

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init")
    git("add", "app.py")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    git("mv", "app.py", "renamed.py")
    result = scope.git_status("demo")
    assert any(
        c.get("previous_path") == "app.py" and c["path"] == "renamed.py"
        for c in result["changes"]
    )
    assert result["hidden_changes"] > 0
    assert result["clean"] is False
    assert ".env" not in str(result["changes"])


def test_git_external_metadata_pointer_rejected(scope, tmp_path):
    (scope.project_root / "demo" / ".git").write_text("gitdir: /not/allowed")
    with pytest.raises(ContextScopeError):
        scope.git_status("demo")


def test_source_symlink_inside_root_and_hardlink_are_denied(scope):
    repo = scope.project_root / "demo"
    (repo / "alias.py").symlink_to(repo / "app.py")
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/alias.py")
    os.link(repo / "app.py", repo / "hard.py")
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/hard.py")


def test_root_symlink_and_fifo_are_denied(scope, tmp_path):
    root_alias = tmp_path / "root-alias"
    root_alias.symlink_to(scope.project_root, target_is_directory=True)
    with pytest.raises(ContextScopeError):
        ContextScope(root_alias, scope.codex_root).read_project_excerpt("demo/app.py")
    os.mkfifo(scope.project_root / "demo" / "fifo.py")
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/fifo.py")


def test_sibling_guidance_is_not_hydrated(scope):
    sibling = scope.project_root / "sibling"
    sibling.mkdir()
    (sibling / "AGENTS.md").write_text("SIBLING_SENTINEL")
    assert "SIBLING_SENTINEL" not in str(scope.read_agent_guidance("demo/app.py"))


def test_search_limit_reports_partial(scope):
    (scope.project_root / "demo" / "many.txt").write_text("needle\n" * 100)
    result = scope.search_project("needle", "demo")
    assert len(result["matches"]) == 20
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "payload",
    [
        'DATABASE_URL = "postgresql://fixture:DO_NOT_EXPOSE@localhost/example"',
        'TOKEN = """\nDO_NOT_EXPOSE\n"""',
        '{"password":\n"DO_NOT_EXPOSE"}',
    ],
)
def test_redacts_dsn_and_multiline_secrets(scope, payload):
    (scope.project_root / "demo" / "settings.py").write_text(payload)
    assert (
        "DO_NOT_EXPOSE" not in scope.read_project_excerpt("demo/settings.py")["content"]
    )
    assert scope.search_project("DO_NOT_EXPOSE", "demo")["matches"] == []


def test_digest_does_not_leak_raw_secret_fingerprint(scope):
    target = scope.project_root / "demo" / "settings.py"
    target.write_text('PASSWORD = "first"')
    first = scope.read_project_excerpt("demo/settings.py")
    target.write_text('PASSWORD = "second"')
    second = scope.read_project_excerpt("demo/settings.py")
    assert first["sha256"] == second["sha256"]
    assert first["digest_basis"] == "redacted-utf8"


@pytest.mark.parametrize(
    "payload", ['API_KEY = (\n    "PAREN_SYNTHETIC"\n)', 'TOKEN =\n\n"PAREN_SYNTHETIC"']
)
def test_complex_credential_assignments_fail_closed(scope, payload):
    (scope.project_root / "demo" / "settings.py").write_text(payload)
    with pytest.raises(ContextScopeError):
        scope.read_project_excerpt("demo/settings.py")
    assert scope.search_project("PAREN_SYNTHETIC", "demo")["matches"] == []


def test_task_context_has_consistent_guidance_and_version(scope):
    first = scope.build_task_context("demo/app.py", ["notion-native-toolkit"])
    assert first["global_guidance"]["content"] == "# Global guidance\n"
    assert len(first["project_guidance"]["guidance"]) == 2
    assert first["skills"][0]["path"] == "notion-native-toolkit/SKILL.md"
    assert "super-secret" not in str(first)
    assert first == scope.build_task_context("demo/app.py", ["notion-native-toolkit"])
    (scope.project_root / "demo" / "AGENTS.md").write_text("New guidance")
    assert (
        scope.build_task_context("demo/app.py", ["notion-native-toolkit"])[
            "context_sha256"
        ]
        != first["context_sha256"]
    )
    with pytest.raises(ContextScopeError):
        scope.build_task_context("demo/app.py", ["notion-native-toolkit"] * 6)
