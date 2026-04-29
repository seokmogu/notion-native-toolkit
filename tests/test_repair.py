from __future__ import annotations

from pathlib import Path

import pytest

from notion_native_toolkit.repair import (
    CommandResult,
    RepairOptions,
    build_codex_command,
    default_verify_command,
    parse_verify_command,
    run_repair,
)


def test_default_unit_check_uses_ephemeral_pytest() -> None:
    assert default_verify_command("unit") == [
        "uv",
        "run",
        "--with",
        "pytest",
        "pytest",
        "-q",
        "-m",
        "not integration",
    ]


def test_integration_check_requires_explicit_allow() -> None:
    with pytest.raises(ValueError, match="allow-integration"):
        default_verify_command("integration")


def test_parse_verify_command_keeps_quoted_marker() -> None:
    assert parse_verify_command("uv run pytest -q -m 'not integration'") == [
        "uv",
        "run",
        "pytest",
        "-q",
        "-m",
        "not integration",
    ]


def test_codex_command_inherits_model_by_default(tmp_path: Path) -> None:
    command = build_codex_command(
        "fix it",
        RepairOptions(repo=tmp_path),
    )

    assert "--model" not in command
    assert command[:3] == ["codex", "exec", "-C"]
    assert "--sandbox" in command
    assert command[-1] == "fix it"


def test_codex_command_includes_explicit_model(tmp_path: Path) -> None:
    command = build_codex_command(
        "fix it",
        RepairOptions(repo=tmp_path, codex_model="gpt-5.5"),
    )

    assert command[command.index("--model") + 1] == "gpt-5.5"


def test_repair_stops_when_initial_verification_passes(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> CommandResult:
        calls.append(command)
        if command[:3] == ["git", "status", "--short"]:
            return CommandResult(command=command, cwd=str(cwd), returncode=0)
        return CommandResult(command=command, cwd=str(cwd), returncode=0, stdout="ok")

    report = run_repair(
        RepairOptions(
            repo=tmp_path, verify_command=["pytest"], output_dir=tmp_path / "repair"
        ),
        runner=runner,
    )

    assert report.success is True
    assert len(report.attempts) == 1
    assert not any(command[:2] == ["codex", "exec"] for command in calls)
    assert report.report_path is not None
    assert Path(report.report_path).exists()


def test_repair_invokes_codex_then_rechecks(tmp_path: Path) -> None:
    verify_count = 0
    codex_count = 0

    def runner(command: list[str], cwd: Path) -> CommandResult:
        nonlocal verify_count, codex_count
        if command[:3] == ["git", "status", "--short"]:
            return CommandResult(
                command=command,
                cwd=str(cwd),
                returncode=0,
                stdout=" M src/notion_native_toolkit/client.py\n",
            )
        if command[:2] == ["codex", "exec"]:
            codex_count += 1
            return CommandResult(
                command=command, cwd=str(cwd), returncode=0, stdout="patched"
            )
        verify_count += 1
        return CommandResult(
            command=command,
            cwd=str(cwd),
            returncode=1 if verify_count == 1 else 0,
            stderr="assertion failed",
        )

    report = run_repair(
        RepairOptions(
            repo=tmp_path,
            verify_command=["pytest"],
            max_iterations=2,
            output_dir=tmp_path / "repair",
        ),
        runner=runner,
    )

    assert report.success is True
    assert codex_count == 1
    assert verify_count == 2
    assert len(report.attempts) == 2
    assert report.dirty_status_before == [" M src/notion_native_toolkit/client.py"]
