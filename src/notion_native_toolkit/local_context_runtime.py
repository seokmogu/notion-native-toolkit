"""Private local launcher for the synthetic local-context MCP fixture.

This module deliberately has no configuration-file or remote-service behavior.
It asks for transient credentials on the controlling terminal, gives the broker
its bearer only through its environment, and gives cloudflared its tunnel token
only through a private file.  The default scope is always generated fixture
content; it never points at a user's home directory or project checkout.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_native_toolkit.context_files import ContextScopeError, open_beneath

_RUNTIME_PREFIX = ".notion-context-runtime-"
_APPROVED_PROJECT_ROOT = Path("/Users/seokmogu/project")
_APPROVED_CODEX_ROOT = Path("/Users/seokmogu/.codex")
_BROKER_PROGRAM = """\
import os
from pathlib import Path
from notion_native_toolkit.local_context import ContextScope
from notion_native_toolkit.local_context_mcp import create_mcp

scope = ContextScope(
    project_root=Path(os.environ["LOCAL_CONTEXT_PROJECT_ROOT"]),
    codex_root=Path(os.environ["LOCAL_CONTEXT_CODEX_ROOT"]),
    scope_mode=os.environ["LOCAL_CONTEXT_SCOPE_MODE"],
)
create_mcp(scope).run(transport="streamable-http")
"""


class RuntimeLaunchError(RuntimeError):
    """A launcher failure whose message is safe to show on the terminal."""


class ShutdownRequested(RuntimeError):
    """The foreground owner received an orderly shutdown signal."""


@dataclass(frozen=True, slots=True)
class RuntimeArtifacts:
    """Private generated paths; none is a source-tree path."""

    root: Path
    project_root: Path
    codex_root: Path
    token_file: Path
    fixture_relative_path: str = "fixture"


def _validate_port(value: int) -> int:
    if not 1 <= value <= 65535:
        raise RuntimeLaunchError("Port must be between 1 and 65535")
    return value


def _validate_allowed_host(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or any(character in value for character in ("*", "/", "\\", "?", "#", ","))
        or any(character.isspace() or ord(character) < 33 for character in value)
    ):
        raise RuntimeLaunchError("Allowed host must be one exact host header value")
    return value


def _read_secret(prompt: str, validator: Callable[[str], bool]) -> str:
    try:
        value = getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise RuntimeLaunchError("Credential input was unavailable") from exc
    if not validator(value):
        raise RuntimeLaunchError("Credential input is invalid")
    return value


def _valid_tunnel_token(value: str) -> bool:
    if not 64 <= len(value) <= 8192 or not value.isascii():
        return False
    try:
        payload = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
    except (ValueError, UnicodeError):
        return False
    return isinstance(payload, dict) and all(
        isinstance(payload.get(key), str) and bool(payload[key]) for key in ("a", "t", "s")
    )


def _valid_bearer(value: str) -> bool:
    return (
        len(value) >= 32
        and value.isascii()
        and not any(character.isspace() for character in value)
    )


def _read_locked_file(value: str, maximum_bytes: int) -> bytes:
    """Read one user-owned 0600 regular file without following any path link."""

    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeLaunchError("Credential handoff file is invalid")
    try:
        with open_beneath(path.parent, (path.name,)) as fd:
            before = os.fstat(fd)
            if before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600:
                raise RuntimeLaunchError("Credential handoff file is invalid")
            if before.st_size > maximum_bytes:
                raise RuntimeLaunchError("Credential handoff file is invalid")
            content = bytearray()
            while len(content) <= maximum_bytes:
                chunk = os.read(fd, min(65536, maximum_bytes + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
            after = os.fstat(fd)
    except (ContextScopeError, OSError) as exc:
        raise RuntimeLaunchError("Credential handoff file is invalid") from exc
    if (
        len(content) > maximum_bytes
        or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    ):
        raise RuntimeLaunchError("Credential handoff file is invalid")
    return bytes(content)


def _encrypted_field(value: object) -> bytes:
    if not isinstance(value, str):
        raise RuntimeLaunchError("Encrypted credential handoff is invalid")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise RuntimeLaunchError("Encrypted credential handoff is invalid") from exc
    if not decoded or len(decoded) > 1024:
        raise RuntimeLaunchError("Encrypted credential handoff is invalid")
    return decoded


def _decrypt_oaep(private_key: str, ciphertext: bytes) -> str:
    """Decrypt one RSA-OAEP/SHA-256 field without placing data in argv or logs."""

    try:
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-decrypt",
                "-inkey",
                private_key,
                "-pkeyopt",
                "rsa_padding_mode:oaep",
                "-pkeyopt",
                "rsa_oaep_md:sha256",
                "-pkeyopt",
                "rsa_mgf1_md:sha256",
            ],
            input=ciphertext,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeLaunchError("Encrypted credential handoff could not be decrypted") from exc
    if result.returncode != 0 or len(result.stdout) > 8192:
        raise RuntimeLaunchError("Encrypted credential handoff could not be decrypted")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeLaunchError("Encrypted credential handoff could not be decrypted") from exc


def load_encrypted_credentials(
    envelope_path: str, key_path: str
) -> dict[str, str]:
    """Decrypt a locked ciphertext-only envelope without emitting any field.

    The optional origin-client pair is returned only for a caller that has a
    separately approved direct-origin probe.  The fixture launcher itself does
    not consume, export, or pass those values to a child process.
    """

    _read_locked_file(key_path, 16 * 1024)
    raw_envelope = _read_locked_file(envelope_path, 8 * 1024)
    try:
        envelope = json.loads(raw_envelope.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeLaunchError("Encrypted credential handoff is invalid") from exc
    required_fields = {
        "schema_version",
        "tunnel_token",
        "broker_bearer",
    }
    optional_origin_fields = {"origin_client_id", "origin_client_secret"}
    envelope_fields = set(envelope) if isinstance(envelope, dict) else set()
    if (
        not isinstance(envelope, dict)
        or (
            envelope_fields != required_fields
            and envelope_fields != required_fields | optional_origin_fields
        )
        or type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != 1
    ):
        raise RuntimeLaunchError("Encrypted credential handoff is invalid")
    credentials = {
        name: _decrypt_oaep(key_path, _encrypted_field(envelope[name]))
        for name in required_fields - {"schema_version"}
    }
    if not _valid_tunnel_token(credentials["tunnel_token"]) or not _valid_bearer(
        credentials["broker_bearer"]
    ):
        raise RuntimeLaunchError("Encrypted credential handoff is invalid")
    if optional_origin_fields <= set(envelope):
        for name in optional_origin_fields:
            value = _decrypt_oaep(key_path, _encrypted_field(envelope[name]))
            if not value or len(value.encode("utf-8")) > 8192:
                raise RuntimeLaunchError("Encrypted credential handoff is invalid")
            credentials[name] = value
    return credentials


def _credentials(
    encrypted_credentials: str | None, handoff_key: str | None
) -> tuple[str, str]:
    if bool(encrypted_credentials) != bool(handoff_key):
        raise RuntimeLaunchError("Encrypted credentials and handoff key must be supplied together")
    if encrypted_credentials and handoff_key:
        credentials = load_encrypted_credentials(encrypted_credentials, handoff_key)
        return credentials["tunnel_token"], credentials["broker_bearer"]
    return (
        _read_secret("Cloudflare tunnel token (hidden): ", _valid_tunnel_token),
        _read_secret("MCP broker bearer (hidden): ", _valid_bearer),
    )


def _runtime_parent(value: str) -> Path:
    parent = Path(value)
    if not parent.is_absolute() or ".." in parent.parts:
        raise RuntimeLaunchError("Runtime directory must be an absolute existing directory")
    try:
        with open_beneath(parent, (), directory=True):
            pass
    except (ContextScopeError, OSError) as exc:
        raise RuntimeLaunchError("Runtime directory must be an absolute existing directory") from exc
    return parent


def _mkdir_at(parent_fd: int, name: str) -> int:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    os.fchmod(fd, 0o700)
    return fd


def _write_at(parent_fd: int, name: str, value: str, mode: int = 0o600) -> None:
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode,
        dir_fd=parent_fd,
    )
    try:
        encoded = value.encode("utf-8")
        written = 0
        while written < len(encoded):
            written += os.write(fd, encoded[written:])
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _create_private_runtime(parent: Path) -> RuntimeArtifacts:
    """Create a collision-safe, no-follow fixture scope beneath ``parent``."""

    with open_beneath(parent, (), directory=True) as parent_fd:
        for _ in range(16):
            name = _RUNTIME_PREFIX + secrets.token_hex(12)
            try:
                runtime_fd = _mkdir_at(parent_fd, name)
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeLaunchError("Could not create a private runtime directory")

    root = parent / name
    try:
        project_fd = _mkdir_at(runtime_fd, "fixture-root")
        codex_fd = _mkdir_at(runtime_fd, "codex-root")
        fixture_fd = _mkdir_at(project_fd, "fixture")
        try:
            marker = secrets.token_urlsafe(24)
            _write_at(project_fd, "AGENTS.md", "Synthetic fixture root guidance.\n")
            _write_at(fixture_fd, "AGENTS.md", "Synthetic fixture guidance.\n")
            _write_at(fixture_fd, "source-marker.txt", f"fixture-marker:{marker}\n")
            _write_at(codex_fd, "AGENTS.md", "Synthetic Codex fixture guidance.\n")
        finally:
            os.close(fixture_fd)
            os.close(codex_fd)
            os.close(project_fd)
    finally:
        os.close(runtime_fd)
    return RuntimeArtifacts(
        root=root,
        project_root=root / "fixture-root",
        codex_root=root / "codex-root",
        token_file=root / "tunnel-token",
    )


def _write_tunnel_token(artifacts: RuntimeArtifacts, token: str) -> None:
    with open_beneath(artifacts.root, (), directory=True) as runtime_fd:
        _write_at(runtime_fd, artifacts.token_file.name, token)


def _remove_runtime(artifacts: RuntimeArtifacts) -> None:
    """Remove only the known files and directories this invocation created."""

    try:
        with open_beneath(artifacts.root, (), directory=True) as root_fd:
            for directory, files in (
                ("fixture-root/fixture", ("AGENTS.md", "source-marker.txt")),
                ("fixture-root", ("AGENTS.md",)),
                ("codex-root", ("AGENTS.md",)),
                ("", ("tunnel-token",)),
            ):
                if directory:
                    parts = tuple(directory.split("/"))
                    fd = os.open(
                        parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
                    )
                    try:
                        if len(parts) == 2:
                            nested_fd = os.open(
                                parts[1],
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd,
                            )
                            os.close(fd)
                            fd = nested_fd
                        for file_name in files:
                            try:
                                os.unlink(file_name, dir_fd=fd)
                            except FileNotFoundError:
                                pass
                    finally:
                        os.close(fd)
                else:
                    for file_name in files:
                        try:
                            os.unlink(file_name, dir_fd=root_fd)
                        except FileNotFoundError:
                            pass
            fixture_root_fd = os.open(
                "fixture-root", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
            )
            try:
                os.rmdir("fixture", dir_fd=fixture_root_fd)
            finally:
                os.close(fixture_root_fd)
            os.rmdir("fixture-root", dir_fd=root_fd)
            os.rmdir("codex-root", dir_fd=root_fd)
    except (ContextScopeError, FileNotFoundError, OSError):
        # Cleanup is best effort. It never recurses beyond this owned directory.
        return
    try:
        artifacts.root.rmdir()
    except OSError:
        return


def _verify_cloudflared() -> str:
    binary = shutil.which("cloudflared")
    if not binary:
        raise RuntimeLaunchError("cloudflared is not installed")
    try:
        result = subprocess.run(
            [binary, "tunnel", "run", "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeLaunchError("cloudflared token-file support could not be verified") from exc
    if result.returncode != 0 or b"--token-file" not in (result.stdout + result.stderr):
        raise RuntimeLaunchError("cloudflared token-file support could not be verified")
    return binary


def _scope_roots(
    artifacts: RuntimeArtifacts, real_context: bool
) -> tuple[Path, Path]:
    if real_context:
        return _APPROVED_PROJECT_ROOT, _APPROVED_CODEX_ROOT
    return artifacts.project_root, artifacts.codex_root


def _validate_real_scope_roots(project_root: Path, codex_root: Path) -> None:
    """Confirm the fixed roots are physically safe before handing them to a child."""

    try:
        for root in (project_root, codex_root):
            with open_beneath(root, (), directory=True):
                pass
    except (ContextScopeError, OSError) as exc:
        raise RuntimeLaunchError("Approved context roots are unavailable") from exc


def _broker_environment(
    project_root: Path,
    codex_root: Path,
    port: int,
    allowed_host: str,
    bearer: str,
    scope_mode: str = "custom",
) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LOCAL_CONTEXT_TRANSPORT": "streamable-http",
        "LOCAL_CONTEXT_PORT": str(port),
        "LOCAL_CONTEXT_ALLOWED_HOST": allowed_host,
        "LOCAL_CONTEXT_BEARER_SECRET": bearer,
        "LOCAL_CONTEXT_PROJECT_ROOT": str(project_root),
        "LOCAL_CONTEXT_CODEX_ROOT": str(codex_root),
        "LOCAL_CONTEXT_SCOPE_MODE": scope_mode,
    }


def _http_post(port: int, payload: dict[str, Any], bearer: str | None) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.status, response.read(200_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(200_000)
    except (OSError, ValueError):
        return 0, b""


def _mcp_result(body: bytes) -> dict[str, Any] | None:
    try:
        for line in body.decode("utf-8").splitlines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                result = payload.get("result")
                return result if isinstance(result, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return None


def _probe_broker(port: int, bearer: str) -> bool:
    """Require unauthenticated denial plus authenticated MCP initialization/tools."""

    if _http_post(port, {}, None)[0] != 401:
        return False
    initialize = _mcp_result(
        _http_post(
            port,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "local-context-runtime", "version": "1"},
                },
            },
            bearer,
        )[1]
    )
    if not initialize or initialize.get("serverInfo", {}).get("name") != "local-context-broker":
        return False
    tools = _mcp_result(
        _http_post(
            port,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            bearer,
        )[1]
    )
    return bool(
        tools
        and any(
            isinstance(tool, dict) and tool.get("name") == "get_scope_manifest"
            for tool in tools.get("tools", [])
        )
    )


def _wait_for_broker(
    process: subprocess.Popen[bytes],
    port: int,
    bearer: str,
    stopped: Callable[[], bool],
) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if stopped():
            raise ShutdownRequested()
        if process.poll() is not None:
            raise RuntimeLaunchError("Broker stopped before it became healthy")
        if _probe_broker(port, bearer):
            return
        time.sleep(0.1)
    raise RuntimeLaunchError("Broker did not become healthy")


def _terminate_children(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def _shutdown_signals() -> Any:
    requested = False

    def request_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal requested
        requested = True

    previous = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        yield lambda: requested
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _monitor_children(
    broker: subprocess.Popen[bytes], tunnel: subprocess.Popen[bytes], stopped: Callable[[], bool]
) -> None:
    while not stopped():
        if broker.poll() is not None:
            raise RuntimeLaunchError("Broker stopped; tunnel will be stopped")
        if tunnel.poll() is not None:
            raise RuntimeLaunchError("Tunnel stopped; broker will be stopped")
        time.sleep(0.2)


def launch(
    runtime_dir: str,
    port: int,
    allowed_host: str,
    encrypted_credentials: str | None = None,
    handoff_key: str | None = None,
    real_context: bool = False,
) -> None:
    """Run a broker using fixture scope unless the fixed approved scope is explicit."""

    parent = _runtime_parent(runtime_dir)
    port = _validate_port(port)
    allowed_host = _validate_allowed_host(allowed_host)
    cloudflared = _verify_cloudflared()
    tunnel_token, bearer = _credentials(encrypted_credentials, handoff_key)
    if real_context:
        _validate_real_scope_roots(_APPROVED_PROJECT_ROOT, _APPROVED_CODEX_ROOT)
    artifacts = _create_private_runtime(parent)
    project_root, codex_root = _scope_roots(artifacts, real_context)
    scope_label = "approved-projects" if real_context else "fixture"
    processes: list[subprocess.Popen[bytes]] = []
    try:
        _write_tunnel_token(artifacts, tunnel_token)
        with _shutdown_signals() as stopped:
            if stopped():
                raise ShutdownRequested()
            try:
                broker = subprocess.Popen(
                    [sys.executable, "-c", _BROKER_PROGRAM],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=_broker_environment(
                        project_root,
                        codex_root,
                        port,
                        allowed_host,
                        bearer,
                        scope_label,
                    ),
                )
            except OSError as exc:
                raise RuntimeLaunchError("Broker process could not be started") from exc
            processes.append(broker)
            _wait_for_broker(broker, port, bearer, stopped)
            if stopped():
                raise ShutdownRequested()
            try:
                tunnel = subprocess.Popen(
                    [cloudflared, "tunnel", "run", "--token-file", str(artifacts.token_file)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={"PATH": os.environ.get("PATH", os.defpath), "LANG": os.environ.get("LANG", "C.UTF-8")},
                )
            except OSError as exc:
                raise RuntimeLaunchError("Tunnel process could not be started") from exc
            processes.append(tunnel)
            fixture = " fixture=fixture" if not real_context else ""
            print(
                f"BROKER READY pid={broker.pid} port={port} scope={scope_label}{fixture}",
                flush=True,
            )
            print(f"TUNNEL CONNECTING pid={tunnel.pid} ingress=unverified", flush=True)
            print("Control: Ctrl-C stops this launcher and its child processes.", flush=True)
            _monitor_children(broker, tunnel, stopped)
    except ShutdownRequested:
        return
    finally:
        _terminate_children(processes)
        _remove_runtime(artifacts)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the private read-only context broker and tunnel; fixture scope by default."
    )
    parser.add_argument("--runtime-dir", required=True, metavar="ABS_PATH")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--allowed-host", required=True, metavar="HOST")
    parser.add_argument("--encrypted-credentials", metavar="JSONFILE")
    parser.add_argument("--handoff-key", metavar="PRIVATE_PEM")
    parser.add_argument(
        "--real-context", action="store_true",
        help="Use the fixed approved project and Codex instruction roots instead of synthetic fixtures.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        launch(
            args.runtime_dir,
            args.port,
            args.allowed_host,
            args.encrypted_credentials,
            args.handoff_key,
            args.real_context,
        )
    except (RuntimeLaunchError, OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        print("ERROR: local context runtime could not start safely", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
