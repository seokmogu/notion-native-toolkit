from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


CommandRunner = Callable[[list[str], Path], "CommandResult"]


@dataclass
class CommandResult:
    command: list[str]
    cwd: str
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self, *, max_chars: int) -> dict[str, object]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": _trim(self.stdout, max_chars),
            "stderr": _trim(self.stderr, max_chars),
        }


@dataclass
class RepairAttempt:
    iteration: int
    verification: CommandResult
    codex: CommandResult | None = None

    def to_dict(self, *, max_chars: int) -> dict[str, object]:
        payload: dict[str, object] = {
            "iteration": self.iteration,
            "verification": self.verification.to_dict(max_chars=max_chars),
        }
        if self.codex is not None:
            payload["codex"] = self.codex.to_dict(max_chars=max_chars)
        return payload


@dataclass
class RepairReport:
    started_at: str
    completed_at: str
    repo: str
    success: bool
    dirty_status_before: list[str]
    verification_command: list[str]
    attempts: list[RepairAttempt] = field(default_factory=list)
    report_path: str | None = None

    def to_dict(self, *, max_chars: int = 20000) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "repo": self.repo,
            "success": self.success,
            "dirty_status_before": self.dirty_status_before,
            "verification_command": self.verification_command,
            "attempts": [
                attempt.to_dict(max_chars=max_chars) for attempt in self.attempts
            ],
            "report_path": self.report_path,
        }


@dataclass
class RepairOptions:
    repo: Path
    check: str = "unit"
    verify_command: list[str] | None = None
    allow_integration: bool = False
    max_iterations: int = 3
    codex_model: str | None = None
    sandbox: str = "workspace-write"
    approval_policy: str = "never"
    output_dir: Path | None = None
    max_log_chars: int = 20000
    dry_run: bool = False


def run_repair(
    options: RepairOptions,
    *,
    runner: CommandRunner | None = None,
) -> RepairReport:
    repo = options.repo.resolve()
    run = runner or _run_command
    started_at = _timestamp()
    verify_command = options.verify_command or default_verify_command(
        options.check,
        allow_integration=options.allow_integration,
    )
    output_dir = options.output_dir or Path(".omc") / "repair"
    if not output_dir.is_absolute():
        output_dir = repo / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dirty_status = _git_status(repo, run)
    attempts: list[RepairAttempt] = []

    verification = run(verify_command, repo)
    attempts.append(RepairAttempt(iteration=0, verification=verification))

    success = verification.ok
    for iteration in range(1, options.max_iterations + 1):
        if success:
            break
        prompt = build_codex_prompt(
            repo=repo,
            verification=verification,
            dirty_status=dirty_status,
            verify_command=verify_command,
            max_chars=options.max_log_chars,
        )
        codex_command = build_codex_command(prompt, options)
        if options.dry_run:
            codex_result = CommandResult(
                command=codex_command,
                cwd=str(repo),
                returncode=0,
                stdout="dry-run: codex exec skipped",
            )
        else:
            codex_result = run(codex_command, repo)
        verification = run(verify_command, repo)
        attempts.append(
            RepairAttempt(
                iteration=iteration,
                verification=verification,
                codex=codex_result,
            )
        )
        success = verification.ok
        if not codex_result.ok and not success:
            break

    report = RepairReport(
        started_at=started_at,
        completed_at=_timestamp(),
        repo=str(repo),
        success=success,
        dirty_status_before=dirty_status,
        verification_command=verify_command,
        attempts=attempts,
    )
    report_path = output_dir / f"repair-{_filename_timestamp()}.json"
    report.report_path = str(report_path)
    report_path.write_text(
        json.dumps(
            report.to_dict(max_chars=options.max_log_chars),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def default_verify_command(check: str, *, allow_integration: bool = False) -> list[str]:
    if check == "unit":
        return [
            "uv",
            "run",
            "--with",
            "pytest",
            "pytest",
            "-q",
            "-m",
            "not integration",
        ]
    if check == "all":
        if not allow_integration:
            return [
                "uv",
                "run",
                "--with",
                "pytest",
                "pytest",
                "-q",
                "-m",
                "not integration",
            ]
        return ["uv", "run", "--with", "pytest", "pytest", "-q"]
    if check == "integration":
        if not allow_integration:
            raise ValueError(
                "--allow-integration is required for integration repair checks"
            )
        return [
            "uv",
            "run",
            "--with",
            "pytest",
            "pytest",
            "-q",
            "tests/test_internal_integration.py",
        ]
    raise ValueError(f"Unknown repair check: {check}")


def parse_verify_command(command: str | None) -> list[str] | None:
    if command is None:
        return None
    parsed = shlex.split(command)
    if not parsed:
        raise ValueError("--verify-command cannot be empty")
    return parsed


def build_codex_command(prompt: str, options: RepairOptions) -> list[str]:
    command = [
        "codex",
        "exec",
        "-C",
        str(options.repo.resolve()),
        "--sandbox",
        options.sandbox,
        "--ask-for-approval",
        options.approval_policy,
    ]
    if options.codex_model:
        command.extend(["--model", options.codex_model])
    command.append(prompt)
    return command


def build_codex_prompt(
    *,
    repo: Path,
    verification: CommandResult,
    dirty_status: list[str],
    verify_command: list[str],
    max_chars: int,
) -> str:
    dirty_text = (
        "\n".join(dirty_status) if dirty_status else "(clean before repair run)"
    )
    output = "\n".join(
        part
        for part in [
            "STDOUT:",
            _trim(verification.stdout, max_chars),
            "STDERR:",
            _trim(verification.stderr, max_chars),
        ]
        if part
    )
    return f"""You are repairing / verifying the notion-native-toolkit repository.

Goal:
- Fix the failing verification command without changing unrelated behavior.
- Keep existing dirty worktree changes unless they are directly necessary for the fix.
- Do not read, print, or persist secrets, cookies, .env files, token_v2 values, or browser state.
- Do not run integration tests unless explicitly needed by the failure.
- After editing, run this verification command before finishing:
  {shlex.join(verify_command)}

Repository:
{repo}

Dirty status before repair:
{dirty_text}

Failing verification:
command: {shlex.join(verification.command)}
exit_code: {verification.returncode}

{output}
"""


def _run_command(command: list[str], cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=command,
            cwd=str(cwd),
            returncode=127,
            stderr=str(exc),
        )
    return CommandResult(
        command=command,
        cwd=str(cwd),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _git_status(repo: Path, runner: CommandRunner) -> list[str]:
    result = runner(["git", "status", "--short"], repo)
    if not result.ok:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _filename_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _trim(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return f"{value[:max_chars]}\n... truncated {omitted} chars ..."
