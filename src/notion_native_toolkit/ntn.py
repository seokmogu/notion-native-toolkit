from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class NotionCliResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class NotionCliError(RuntimeError):
    def __init__(self, result: NotionCliResult):
        message = result.stderr.strip() or result.stdout.strip() or "ntn command failed"
        super().__init__(message)
        self.result = result


class NotionCliClient:
    """Small subprocess wrapper around Notion's official `ntn` CLI.

    The toolkit still owns higher-level deployment and internal API flows. This
    wrapper lets callers opt into the official CLI for public API probing,
    Markdown page IO, and file-upload lifecycle handling.
    """

    def __init__(
        self,
        executable: str = "ntn",
        token: str | None = None,
        notion_version: str | None = None,
        workspace_id: str | None = None,
        timeout: float = 60.0,
        env: dict[str, str] | None = None,
    ):
        self.executable = executable
        self.token = token
        self.notion_version = notion_version
        self.workspace_id = workspace_id
        self.timeout = timeout
        self.env = env

    def resolve_executable(self) -> str | None:
        if os.path.isabs(self.executable):
            return self.executable if os.access(self.executable, os.X_OK) else None
        return shutil.which(self.executable)

    def is_available(self) -> bool:
        return self.resolve_executable() is not None

    def _command_env(self) -> dict[str, str]:
        env = dict(self.env) if self.env is not None else dict(os.environ)
        if self.token:
            env["NOTION_API_TOKEN"] = self.token
        if self.notion_version:
            env["NOTION_API_VERSION"] = self.notion_version
        if self.workspace_id:
            env["NOTION_WORKSPACE_ID"] = self.workspace_id
        return env

    def run(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> NotionCliResult:
        if input_text is not None and input_bytes is not None:
            raise ValueError("Pass only one of input_text or input_bytes")
        executable = self.resolve_executable()
        if executable is None:
            raise FileNotFoundError(f"Could not find ntn executable: {self.executable}")

        command = [executable, *args]
        stdin = input_bytes if input_bytes is not None else None
        if input_text is not None:
            stdin = input_text.encode("utf-8")

        completed = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            check=False,
            env=self._command_env(),
            timeout=self.timeout,
        )
        result = NotionCliResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
        )
        if check and result.returncode != 0:
            raise NotionCliError(result)
        return result

    def version(self) -> str:
        return self.run(["--version"]).stdout.strip()

    def doctor(self) -> NotionCliResult:
        return self.run(["doctor"], check=False)

    def whoami(self, *, json_output: bool = True) -> dict[str, Any] | str:
        args = ["whoami"]
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn whoami --json did not return a JSON object")
        return payload

    def api(
        self,
        path: str,
        *,
        method: str | None = None,
        data: dict[str, Any] | None = None,
        json_output: bool = True,
    ) -> object:
        args = ["api", path]
        if method is not None:
            args.extend(["-X", method.upper()])
        if data is not None:
            args.extend(["--data", json.dumps(data, ensure_ascii=False)])
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        return json.loads(result.stdout)

    def api_list(self, *, json_output: bool = True) -> object:
        args = ["api", "ls"]
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        return json.loads(result.stdout)

    def api_docs(self, path: str, *, method: str | None = None) -> str:
        args = ["api", path, "--docs"]
        if method is not None:
            args.extend(["-X", method.upper()])
        return self.run(args).stdout

    def api_spec(self, path: str, *, method: str | None = None) -> dict[str, Any] | str:
        args = ["api", path, "--spec"]
        if method is not None:
            args.extend(["-X", method.upper()])
        result = self.run(args)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout
        if not isinstance(payload, dict):
            return result.stdout
        return payload

    def pages_get(
        self, page_id: str, *, json_output: bool = False
    ) -> dict[str, Any] | str:
        args = ["pages", "get", page_id]
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn pages get --json did not return a JSON object")
        return payload

    def pages_create(
        self,
        parent: str | None,
        markdown: str,
        *,
        json_output: bool = True,
    ) -> dict[str, Any] | str:
        args = ["pages", "create"]
        if parent:
            args.extend(["--parent", parent])
        if json_output:
            args.append("--json")
        result = self.run(args, input_text=markdown)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn pages create --json did not return a JSON object")
        return payload

    def pages_edit(
        self,
        page_id: str,
        markdown: str,
        *,
        allow_deleting_content: bool = False,
        json_output: bool = True,
    ) -> dict[str, Any] | str:
        args = ["pages", "edit", page_id]
        if allow_deleting_content:
            args.append("--allow-deleting-content")
        if json_output:
            args.append("--json")
        result = self.run(args, input_text=markdown)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn pages edit --json did not return a JSON object")
        return payload

    def pages_trash(self, page_id: str, *, yes: bool = True) -> NotionCliResult:
        args = ["pages", "trash", page_id]
        if yes:
            args.append("--yes")
        return self.run(args)

    def datasources_query(
        self,
        data_source_id: str,
        *,
        limit: int | None = None,
        start_cursor: str | None = None,
        sorts: list[str] | None = None,
        filter_payload: dict[str, Any] | str | None = None,
        json_output: bool = True,
    ) -> object:
        args = ["datasources", "query", data_source_id]
        if limit is not None:
            args.extend(["--limit", str(limit)])
        if start_cursor:
            args.extend(["--start-cursor", start_cursor])
        for sort in sorts or []:
            args.extend(["--sort", sort])
        if filter_payload is not None:
            if isinstance(filter_payload, str):
                filter_json = filter_payload
            else:
                filter_json = json.dumps(filter_payload, ensure_ascii=False)
            args.extend(["--filter", filter_json])
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        return json.loads(result.stdout)

    def datasources_resolve(
        self,
        database_id: str,
        *,
        json_output: bool = True,
    ) -> object:
        args = ["datasources", "resolve", database_id]
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        return json.loads(result.stdout)

    def files_create(
        self,
        content: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        json_output: bool = True,
    ) -> dict[str, Any] | str:
        args = ["files", "create"]
        if filename:
            args.extend(["--filename", filename])
        if content_type:
            args.extend(["--content-type", content_type])
        if json_output:
            args.append("--json")
        result = self.run(args, input_bytes=content)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn files create --json did not return a JSON object")
        return payload

    def files_create_external(
        self,
        url: str,
        *,
        filename: str | None = None,
        json_output: bool = True,
    ) -> dict[str, Any] | str:
        args = ["files", "create", "--external-url", url]
        if filename:
            args.extend(["--filename", filename])
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn files create --json did not return a JSON object")
        return payload

    def files_get(
        self,
        upload_id: str,
        *,
        json_output: bool = True,
    ) -> dict[str, Any] | str:
        args = ["files", "get", upload_id]
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("ntn files get --json did not return a JSON object")
        return payload

    def files_list(self, *, json_output: bool = True) -> object:
        args = ["files", "list"]
        if json_output:
            args.append("--json")
        result = self.run(args)
        if not json_output:
            return result.stdout
        return json.loads(result.stdout)
