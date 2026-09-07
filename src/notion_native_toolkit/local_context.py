"""Read-only workspace context with descriptor-safe bounded reads.

Source redaction is best-effort; it cannot classify confidential business data.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .context_files import (
    ContextScopeError,
    list_entries,
    open_beneath,
    read_text,
    split_path,
)

DEFAULT_PROJECT_ROOT = Path("/Users/seokmogu/project")
DEFAULT_CODEX_ROOT = Path("/Users/seokmogu/.codex")
MAX_EXCERPT_LINES = 200
MAX_FILE_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 65536
MAX_SEARCH_RESULTS = 20
MAX_SEARCH_QUERY_CHARS = 200
MAX_SCAN_ENTRIES = 5000
MAX_SCAN_BYTES = 8_000_000
MAX_INSTRUCTION_BYTES = 65536
MAX_GUIDANCE_FILES = 8

_ALLOWED_SKILL_IDS = (
    "hatch-pet",
    "humanize-korean",
    "launch-worxphere-vdi",
    "local-google-api-oauth",
    "notion-collection-auditor",
    "notion-native-toolkit",
    "notion-readable-meeting-minutes",
    "notion-readable-page-editor",
    "onboard-agent-skill",
    "prd-reviewer",
    "prd-writer",
    "reuse-first-engineering",
    "symphony-lite",
    "user-story-writer",
    "worxboard-operator",
    "worxphere-meeting-context-review",
    "worxphere-meeting-minutes",
    "wxpr-admin-design",
    "wxpr-design-review",
)
_EXCLUDED_PARTS = {
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    "cache",
    "credentials",
    "secrets",
    "sessions",
    "backups",
    "logs",
    "data",
    "artifacts",
}
_SENSITIVE_NAME = re.compile(
    r"(?i)(?:^|[_.-])(?:auth|cookies?|credentials?|secrets?|tokens?|passwords?|"
    r"storage[_-]?state|browser[_-]?state|id_rsa|id_ed25519)(?:[_.-]|$)"
)
_TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cpp",
    ".cs",
    ".rb",
    ".swift",
    ".vue",
    ".svelte",
    ".xml",
    ".ini",
    ".cfg",
}
_SECRET_ASSIGNMENT = re.compile(
    r"""(?im)((?:[\w.-]{0,80}(?:token|secret|api[_-]?key|password|cookie)[\w.-]{0,80}|authorization)["']?[ \t]*[:=][ \t]*)([^\n]+)"""
)
_KEY_BLOCK = re.compile(
    r"-----BEGIN [^\n]*PRIVATE KEY-----.*?(?:-----END [^\n]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b"
)


_MULTILINE_SECRET = re.compile(
    r"([\w.-]{0,80}(?:token|secret|api[_-]?key|password|cookie|private[_-]?key)[\w.-]{0,80}[ \t]*=[ \t]*)(\"\"\"|''')(.*?)(\2)",
    re.IGNORECASE | re.DOTALL,
)
_NEXT_LINE_SECRET = re.compile(
    r"([\w.-]{0,80}(?:token|secret|api[_-]?key|password|cookie)[\w.-]{0,80}[\"']?[ \t]*[:=][ \t]*\n)([^\n]+)",
    re.IGNORECASE,
)
_DSN = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_COMPLEX_SECRET = re.compile(
    r"(?im)[\w.-]{0,80}(?:token|secret|api[_-]?key|password|cookie|private[_-]?key)[\w.-]{0,80}[\"']?[ \t]*[:=][ \t]*([^\n]*)"
)


def _redact(text: str) -> str:
    # Redact the full document BEFORE slicing/searching and preserve line numbers.
    text = _KEY_BLOCK.sub(lambda m: "[REDACTED]" + "\n" * m[0].count("\n"), text)
    text = _MULTILINE_SECRET.sub(
        lambda m: m[1] + "[REDACTED]" + "\n" * m[0].count("\n"), text
    )
    text = _NEXT_LINE_SECRET.sub(r"\1[REDACTED]", text)
    text = _DSN.sub(r"\1[REDACTED]@", text)
    for match in _COMPLEX_SECRET.finditer(text):
        rhs = match[1].strip()
        # Expressions spanning lines are deliberately not interpreted by regex.
        # Reject the document rather than allow a later excerpt to reveal a value.
        already_redacted_next_line = text[match.end() :].startswith("\n[REDACTED]")
        if (not rhs and not already_redacted_next_line) or rhs.endswith(
            ("(", "[", "{", "\\")
        ):
            raise ContextScopeError(
                "Complex credential assignment cannot be safely exported"
            )
    text = "\n".join(
        _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", line)
        if any(
            key in line.lower()
            for key in ("token", "secret", "key", "password", "cookie", "authorization")
        )
        else line
        for line in text.split("\n")
    )
    return _TOKEN.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", text))


def _denied(parts: tuple[str, ...]) -> bool:
    return any(
        p.startswith(".") or p.lower() in _EXCLUDED_PARTS or _SENSITIVE_NAME.search(p)
        for p in parts
    )


def _source(parts: tuple[str, ...]) -> bool:
    return (
        bool(parts)
        and not _denied(parts)
        and (
            Path(parts[-1]).suffix.lower() in _TEXT_SUFFIXES
            or parts[-1] in {"Dockerfile", "Makefile", "LICENSE"}
        )
    )


@dataclass(frozen=True, slots=True)
class ContextScope:
    project_root: Path = DEFAULT_PROJECT_ROOT
    codex_root: Path = DEFAULT_CODEX_ROOT
    max_excerpt_lines: int = MAX_EXCERPT_LINES
    max_search_results: int = MAX_SEARCH_RESULTS
    scope_mode: str = "custom"

    def __post_init__(self) -> None:
        if self.scope_mode not in ("fixture", "approved-projects", "custom"):
            raise ContextScopeError("Invalid local context scope mode")
        if self.scope_mode == "approved-projects" and (
            self.project_root != DEFAULT_PROJECT_ROOT
            or self.codex_root != DEFAULT_CODEX_ROOT
        ):
            raise ContextScopeError("Approved-projects mode requires the fixed approved roots")
        if self.scope_mode == "fixture" and (
            self.project_root == DEFAULT_PROJECT_ROOT
            or self.codex_root == DEFAULT_CODEX_ROOT
        ):
            raise ContextScopeError("Fixture mode may not point at the real approved roots")
        if (
            not 1 <= self.max_excerpt_lines <= MAX_EXCERPT_LINES
            or not 1 <= self.max_search_results <= MAX_SEARCH_RESULTS
        ):
            raise ContextScopeError("Context limits exceed the server maximum")

    def scope_identity(self) -> dict[str, Any]:
        """Describe configured roots; this metadata never expands file access."""
        return {
            "mode": self.scope_mode,
            "project_root": str(self.project_root),
            "codex_instruction_root": str(self.codex_root),
            "read_only": True,
            "path_semantics": {
                "inputs": "Relative paths only; absolute paths are rejected.",
                "dot": "'.' refers to project_root, not the filesystem root.",
                "first_call": "Read get_scope_manifest before read/search; do not reuse cached scope.",
                "root_claim": "Only report the returned project_root. Fixture/custom is not the approved project root.",
                "codex_access": "Dedicated global-guidance and allowlisted skill tools only; not arbitrary .codex files.",
            },
        }

    def _parts(self, path: str, *, root_ok: bool = False) -> tuple[str, ...]:
        parts = split_path(path, root_ok=root_ok)
        if _denied(parts):
            raise ContextScopeError("Path is excluded from the local context scope")
        return parts

    def _payload(
        self, root: Path, parts: tuple[str, ...], *, instruction: bool = False
    ) -> dict[str, Any]:
        text, _raw = read_text(
            root, parts, MAX_INSTRUCTION_BYTES if instruction else MAX_FILE_BYTES
        )
        if any(len(line.encode()) > MAX_RESPONSE_BYTES for line in text.splitlines()):
            raise ContextScopeError("Source line exceeds response byte limit")
        redacted = _redact(text)
        return {
            "path": "/".join(parts),
            "content": redacted,
            "sha256": sha256(redacted.encode()).hexdigest(),
            "digest_basis": "redacted-utf8",
        }

    def get_scope_manifest(self) -> dict[str, Any]:
        """Bounded top-level discovery; each directory is a candidate project."""
        projects = []
        for name, mode in list_entries(self.project_root, (), 1000):
            if not stat.S_ISDIR(mode) or _denied((name,)):
                continue
            try:
                entries = dict(list_entries(self.project_root, (name,), 1000))
            except ContextScopeError:
                continue
            projects.append(
                {
                    "id": name,
                    "has_agents": stat.S_ISREG(entries.get("AGENTS.md", 0)),
                    "is_git_repository": stat.S_ISDIR(entries.get(".git", 0)),
                }
            )
        skills = []
        for name in _ALLOWED_SKILL_IDS:
            try:
                with open_beneath(self.codex_root, ("skills", name, "SKILL.md")):
                    skills.append(name)
            except ContextScopeError:
                continue
        return {
            "scope": self.scope_identity(),
            "roots": {
                "project": "Approved workspace sources (read-only)",
                "codex-instructions": "Global AGENTS.md and fixed skill IDs only",
            },
            "projects": projects,
            "skills": skills,
            "limits": {
                "max_excerpt_lines": self.max_excerpt_lines,
                "max_search_results": self.max_search_results,
                "max_response_bytes": MAX_RESPONSE_BYTES,
                "max_scan_entries": MAX_SCAN_ENTRIES,
            },
            "limitations": "No runtime, data, hidden or credential files. Redaction is best-effort.",
        }

    def read_agent_guidance(self, path: str) -> dict[str, Any]:
        """Read only target ancestry, outer-to-inner. Do not follow instruction links."""
        parts = self._parts(path, root_ok=True)
        directory = parts
        try:
            with open_beneath(self.project_root, parts, directory=True):
                pass
        except ContextScopeError:
            with open_beneath(self.project_root, parts):
                directory = parts[:-1]
        guidance = []
        total = 0
        for length in range(len(directory) + 1):
            ancestor = directory[:length]
            entries = dict(list_entries(self.project_root, ancestor, 1000))
            if "AGENTS.md" not in entries:
                continue
            item = self._payload(
                self.project_root, ancestor + ("AGENTS.md",), instruction=True
            )
            total += len(item["content"].encode())
            if len(guidance) >= MAX_GUIDANCE_FILES or total > MAX_RESPONSE_BYTES:
                raise ContextScopeError(
                    "AGENTS chain exceeds limits; no partial guidance returned"
                )
            guidance.append(item)
        return {
            "path": "/".join(parts) or ".",
            "guidance": guidance,
            "order": "outer-to-inner",
        }

    def read_global_agent_guidance(self) -> dict[str, Any]:
        return self._payload(self.codex_root, ("AGENTS.md",), instruction=True)

    def read_skill(self, skill_id: str) -> dict[str, Any]:
        if skill_id not in _ALLOWED_SKILL_IDS:
            raise ContextScopeError(
                "Requested skill is not in the static instruction allowlist"
            )
        item = self._payload(
            self.codex_root, ("skills", skill_id, "SKILL.md"), instruction=True
        )
        item["path"] = f"{skill_id}/SKILL.md"
        item["limitations"] = (
            "Entrypoint only; referenced scripts/resources and local tools are not supplied."
        )
        return item

    def build_task_context(
        self, path: str, skill_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Hydrate a reproducible instruction packet without reading task source."""
        selected = skill_ids or []
        if len(selected) > 5 or len(set(selected)) != len(selected):
            raise ContextScopeError("Select at most five distinct skill IDs")
        packet = {
            "schema_version": 1,
            "global_guidance": self.read_global_agent_guidance(),
            "project_guidance": self.read_agent_guidance(path),
            "skills": [self.read_skill(skill_id) for skill_id in selected],
            "limitations": "Instructions only; host system/developer rules, live conversation, skill references and tool privileges are not copied.",
        }
        encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True).encode()
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise ContextScopeError(
                "Instruction packet exceeds byte limit; select fewer skills"
            )
        return {
            **packet,
            "context_sha256": sha256(encoded).hexdigest(),
            "digest_basis": "redacted-utf8",
        }

    def read_project_excerpt(
        self, path: str, start_line: int = 1, end_line: int | None = None
    ) -> dict[str, Any]:
        parts = self._parts(path)
        if not _source(parts):
            raise ContextScopeError("Only approved text source files may be read")
        end = (
            end_line
            if end_line is not None
            else start_line + self.max_excerpt_lines - 1
        )
        if (
            isinstance(start_line, bool)
            or isinstance(end, bool)
            or start_line < 1
            or not start_line <= end < start_line + self.max_excerpt_lines
        ):
            raise ContextScopeError("Requested excerpt exceeds the line limit")
        item = self._payload(self.project_root, parts)
        lines = item["content"].splitlines()
        if start_line > max(1, len(lines)):
            raise ContextScopeError("start_line is past end of file")
        selected = "\n".join(lines[start_line - 1 : end])
        if len(selected.encode()) > MAX_RESPONSE_BYTES:
            raise ContextScopeError(
                "Excerpt exceeds response byte limit; narrow the range"
            )
        item.update(
            content=selected,
            start_line=start_line,
            end_line=min(end, len(lines)),
            total_lines=len(lines),
            truncated=end < len(lines),
        )
        return item

    def search_project(self, query: str, path: str = ".") -> dict[str, Any]:
        """Literal search using the same safe file reader; bounded traversal/output."""
        if (
            not query
            or len(query) > MAX_SEARCH_QUERY_CHARS
            or any(ord(c) < 32 for c in query)
        ):
            raise ContextScopeError("Search query must be 1-200 printable characters")
        base = self._parts(path, root_ok=True)
        with open_beneath(self.project_root, base, directory=True):
            pass
        stack = [base]
        matches: list[dict[str, Any]] = []
        scanned = consumed = 0
        deadline = time.monotonic() + 5
        truncated = False
        while stack:
            current = stack.pop()
            if (
                len(current) > 64
                or time.monotonic() >= deadline
                or scanned >= MAX_SCAN_ENTRIES
                or consumed >= MAX_SCAN_BYTES
            ):
                truncated = True
                break
            try:
                entries = list_entries(
                    self.project_root, current, min(1000, MAX_SCAN_ENTRIES - scanned)
                )
            except ContextScopeError:
                truncated = True
                continue
            for name, mode in entries:
                scanned += 1
                parts = current + (name,)
                if _denied(parts):
                    continue
                if stat.S_ISDIR(mode):
                    stack.append(parts)
                    continue
                if not stat.S_ISREG(mode) or not _source(parts):
                    continue
                if time.monotonic() >= deadline or consumed >= MAX_SCAN_BYTES:
                    truncated = True
                    break
                try:
                    text, raw = read_text(
                        self.project_root,
                        parts,
                        min(MAX_FILE_BYTES, MAX_SCAN_BYTES - consumed),
                    )
                except ContextScopeError:
                    truncated = True
                    continue
                consumed += len(raw)
                if any(
                    len(line.encode()) > MAX_RESPONSE_BYTES
                    for line in text.splitlines()
                ):
                    truncated = True
                    continue
                try:
                    redacted = _redact(text)
                except ContextScopeError:
                    truncated = True
                    continue
                for line_num, line in enumerate(redacted.splitlines(), 1):
                    if query not in line:
                        continue
                    if len(line.encode()) > 2000:
                        truncated = True
                        continue
                    matches.append(
                        {
                            "path": "/".join(parts),
                            "line": line_num,
                            "text": line,
                            "sha256": sha256(redacted.encode()).hexdigest(),
                            "digest_basis": "redacted-utf8",
                        }
                    )
                    if len(matches) >= self.max_search_results:
                        truncated = True
                        break
                if len(matches) >= self.max_search_results:
                    break
            if len(matches) >= self.max_search_results:
                break
        return {
            "query": _redact(query),
            "scope": "/".join(base) or ".",
            "matches": matches,
            "truncated": truncated,
            "scanned_entries": scanned,
        }

    def git_status(self, project: str) -> dict[str, Any]:
        """Fixed status only. External worktree pointers/includes are unsupported."""
        parts = self._parts(project)
        with (
            open_beneath(self.project_root, parts, directory=True) as repo_fd,
            open_beneath(
                self.project_root, parts + (".git",), directory=True
            ) as git_fd,
        ):
            entries = dict(list_entries(self.project_root, parts + (".git",), 1000))
            if any(stat.S_ISLNK(mode) for mode in entries.values()) or any(
                n in entries for n in ("commondir", "gitdir", "config.worktree")
            ):
                raise ContextScopeError("External Git metadata is unsupported")
            config, _ = read_text(self.project_root, parts + (".git", "config"), 65536)
            parser = configparser.RawConfigParser(strict=False)
            try:
                parser.read_string(config)
            except configparser.Error as exc:
                raise ContextScopeError("Unsupported Git configuration") from exc
            if any(
                s.lower().startswith(("include", "extensions", "filter"))
                for s in parser.sections()
            ):
                raise ContextScopeError(
                    "Git includes/extensions/filters are not allowed"
                )
            # macOS /dev/fd paths cannot be used as Git directories. A fixed
            # child launcher pins cwd by fd without preexec_fn in a threaded server.
            launcher = "import os,sys; os.fchdir(int(sys.argv[1])); os.execv('/usr/bin/git', ['git'] + sys.argv[2:])"
            command = [
                sys.executable,
                "-c",
                launcher,
                str(repo_fd),
                "--no-pager",
                "--no-optional-locks",
                "--git-dir=.git",
                "--work-tree=.",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.bare=false",
                "-c",
                "core.untrackedCache=false",
                "status",
                "--porcelain=v2",
                "--branch",
                "--ignore-submodules=all",
                "--untracked-files=normal",
                "-z",
            ]
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": "/dev/null",
                "LANG": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_TERMINAL_PROMPT": "0",
            }
            raw = _bounded_command(command, env, (repo_fd, git_fd))
            after_config, _ = read_text(
                self.project_root, parts + (".git", "config"), 65536
            )
            if after_config != config:
                raise ContextScopeError("Git configuration changed during status")
        records = iter(raw.decode("utf-8", errors="strict").split("\0"))
        changes = []
        branch = head = ""
        hidden = 0
        for record in records:
            if record.startswith("# branch.head "):
                branch = record[14:]
            elif record.startswith("# branch.oid "):
                head = record[13:]
            elif record.startswith(("1 ", "2 ", "u ", "? ")):
                prefix = record[0]
                values = record.split(" ", {"1": 8, "2": 9, "u": 10, "?": 1}[prefix])
                name = values[-1]
                previous = next(records, "") if prefix == "2" else None
                if _denied(tuple(name.split("/"))) or (
                    previous and _denied(tuple(previous.split("/")))
                ):
                    hidden += 1
                    continue
                item = {
                    "status": "untracked" if prefix == "?" else values[1],
                    "path": name,
                }
                if previous:
                    item["previous_path"] = previous
                changes.append(item)
        return {
            "project": "/".join(parts),
            "branch": _redact(branch),
            "head": head,
            "changes": changes,
            "hidden_changes": hidden,
            "clean": not changes and not hidden,
            "limitations": "Submodule contents are not inspected.",
        }


def _bounded_command(
    command: list[str], env: dict[str, str], fds: tuple[int, ...]
) -> bytes:
    """Bound subprocess memory and time; never return path-containing stderr."""
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        pass_fds=fds,
    ) as process:
        output = bytearray()
        deadline = time.monotonic() + 5
        try:
            assert process.stdout is not None
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ContextScopeError("Git status timed out")
                    block = os.read(process.stdout.fileno(), 8192)
                    if not block:
                        break
                    output.extend(block)
                    if len(output) > MAX_RESPONSE_BYTES:
                        raise ContextScopeError("Git status exceeds output limit")
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if process.returncode:
                raise ContextScopeError("Git status failed")
            return bytes(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
