from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from notion_native_toolkit import local_context_runtime as runtime

_TUNNEL_TOKEN = base64.b64encode(json.dumps({
    "a": "synthetic-account", "t": "synthetic-tunnel", "s": "synthetic-secret-only"
}).encode()).decode()


@pytest.mark.parametrize("preview", ["eyJhIjoiZj", "eyJhIjoiZj...", "Generating", "x" * 96])
def test_rejects_ui_preview_instead_of_a_full_tunnel_token(preview: str) -> None:
    assert runtime._valid_tunnel_token(preview) is False
_BEARER = "b" * 32


def test_private_fixture_has_strict_modes_and_never_uses_real_roots(tmp_path: Path) -> None:
    artifacts = runtime._create_private_runtime(tmp_path)
    try:
        assert artifacts.root.parent == tmp_path
        assert artifacts.project_root != Path.home()
        assert artifacts.codex_root != Path.home()
        assert stat.S_IMODE(artifacts.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(artifacts.project_root.stat().st_mode) == 0o700
        assert (artifacts.project_root / "AGENTS.md").read_text() == "Synthetic fixture root guidance.\n"
        marker = (artifacts.project_root / "fixture" / "source-marker.txt").read_text()
        assert marker.startswith("fixture-marker:")
        runtime._write_tunnel_token(artifacts, _TUNNEL_TOKEN)
        assert stat.S_IMODE(artifacts.token_file.stat().st_mode) == 0o600
        assert artifacts.token_file.read_text() == _TUNNEL_TOKEN
    finally:
        runtime._remove_runtime(artifacts)
    assert not artifacts.root.exists()


def test_real_context_flag_selects_only_fixed_approved_roots() -> None:
    artifacts = runtime.RuntimeArtifacts(
        root=Path("/synthetic/runtime"),
        project_root=Path("/synthetic/fixture-project"),
        codex_root=Path("/synthetic/fixture-codex"),
        token_file=Path("/synthetic/runtime/tunnel-token"),
    )

    assert runtime._scope_roots(artifacts, False) == (
        artifacts.project_root,
        artifacts.codex_root,
    )
    assert runtime._scope_roots(artifacts, True) == (
        Path("/Users/seokmogu/project"),
        Path("/Users/seokmogu/.codex"),
    )
    assert runtime._arguments(
        ["--runtime-dir", "/synthetic", "--allowed-host", "safe.example"]
    ).real_context is False
    assert runtime._arguments(
        [
            "--runtime-dir",
            "/synthetic",
            "--allowed-host",
            "safe.example",
            "--real-context",
        ]
    ).real_context is True


@pytest.mark.parametrize("mode", ["fixture", "approved-projects"])
def test_broker_environment_carries_explicit_scope_mode(mode: str) -> None:
    env = runtime._broker_environment(
        Path("/synthetic/project"), Path("/synthetic/codex"),
        8001, "safe.example", _BEARER, mode,
    )
    assert env["LOCAL_CONTEXT_SCOPE_MODE"] == mode
    assert 'scope_mode=os.environ["LOCAL_CONTEXT_SCOPE_MODE"]' in runtime._BROKER_PROGRAM


def test_runtime_directory_creation_does_not_overwrite_collision(
    tmp_path: Path, monkeypatch
) -> None:
    collision = tmp_path / ".notion-context-runtime-collision"
    collision.mkdir(mode=0o700)
    generated = iter(("collision", "fresh"))
    monkeypatch.setattr(runtime.secrets, "token_hex", lambda _size: next(generated))

    artifacts = runtime._create_private_runtime(tmp_path)
    try:
        assert artifacts.root.name == ".notion-context-runtime-fresh"
        assert collision.is_dir()
    finally:
        runtime._remove_runtime(artifacts)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("short", False),
        ("a" * 31, False),
        ("a" * 32, True),
        ("a" * 31 + " ", False),
        ("가" * 32, False),
    ],
)
def test_bearer_validation_is_strict(value: str, expected: bool) -> None:
    assert runtime._valid_bearer(value) is expected


def test_invalid_input_and_errors_are_redacted(tmp_path: Path, monkeypatch, capsys) -> None:
    secret = "not-a-valid-secret"
    monkeypatch.setattr(runtime, "_verify_cloudflared", lambda: "/bin/cloudflared")
    monkeypatch.setattr(runtime.getpass, "getpass", lambda _prompt: secret)

    assert runtime.main(["--runtime-dir", str(tmp_path), "--allowed-host", "safe.example"]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "could not start safely" in captured.err
    with pytest.raises(runtime.RuntimeLaunchError, match="exact host"):
        runtime._validate_allowed_host("*.unsafe.example")
    with pytest.raises(runtime.RuntimeLaunchError, match="between"):
        runtime._validate_port(65536)


def test_probe_requires_unauthenticated_401_and_authenticated_mcp_health(monkeypatch) -> None:
    calls: list[str | None] = []

    def sse(payload: dict) -> bytes:
        return f"data: {runtime.json.dumps(payload)}\n\n".encode()

    def post(_port: int, payload: dict, bearer: str | None) -> tuple[int, bytes]:
        calls.append(bearer)
        if bearer is None:
            return 401, b""
        if payload["method"] == "initialize":
            return 200, sse({"result": {"serverInfo": {"name": "local-context-broker"}}})
        return 200, sse({"result": {"tools": [{"name": "get_scope_manifest"}]}})

    monkeypatch.setattr(runtime, "_http_post", post)
    assert runtime._probe_broker(8001, _BEARER) is True
    assert calls == [None, _BEARER, _BEARER]

    monkeypatch.setattr(runtime, "_http_post", lambda *_args: (200, b""))
    assert runtime._probe_broker(8001, _BEARER) is False


class _Process:
    next_pid = 4100

    def __init__(self) -> None:
        self.pid = self.next_pid
        type(self).next_pid += 1
        self.terminated = False
        self.killed = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: int | None = None) -> int:
        return 0


def test_launch_hides_tokens_and_shuts_down_only_its_children(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    processes: list[_Process] = []
    marker = "MARKER_MUST_NOT_APPEAR"
    monkeypatch.setattr(runtime.secrets, "token_urlsafe", lambda _size: marker)
    monkeypatch.setattr(runtime, "_verify_cloudflared", lambda: "/opt/bin/cloudflared")
    answers = iter((_TUNNEL_TOKEN, _BEARER))
    monkeypatch.setattr(runtime.getpass, "getpass", lambda _prompt: next(answers))
    monkeypatch.setattr(runtime, "_wait_for_broker", lambda *_args: None)
    monkeypatch.setattr(runtime, "_monitor_children", lambda *_args: None)

    def popen(command: list[str], **kwargs: object) -> _Process:
        calls.append((command, kwargs["env"]))  # type: ignore[index]
        process = _Process()
        processes.append(process)
        return process

    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    runtime.launch(str(tmp_path), 8001, "context-origin.example.com")

    output = capsys.readouterr().out
    assert "BROKER READY" in output
    assert "scope=fixture fixture=fixture" in output
    assert "TUNNEL CONNECTING" in output
    assert "ingress=unverified" in output
    assert _TUNNEL_TOKEN not in output
    assert _BEARER not in output
    assert marker not in output
    assert len(calls) == 2
    broker_command, broker_env = calls[0]
    tunnel_command, tunnel_env = calls[1]
    assert _BEARER not in " ".join(broker_command)
    assert _TUNNEL_TOKEN not in " ".join(tunnel_command)
    assert broker_env["LOCAL_CONTEXT_BEARER_SECRET"] == _BEARER
    assert "LOCAL_CONTEXT_BEARER_SECRET" not in tunnel_env
    assert "--token-file" in tunnel_command
    assert all(process.terminated and not process.killed for process in processes)
    assert not list(tmp_path.glob(".notion-context-runtime-*"))


def test_cloudflared_help_must_advertise_token_file(monkeypatch) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/opt/bin/cloudflared")
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"--token-file", b""),
    )
    assert runtime._verify_cloudflared() == "/opt/bin/cloudflared"
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"", b""),
    )
    with pytest.raises(runtime.RuntimeLaunchError, match="token-file"):
        runtime._verify_cloudflared()


def test_main_sanitizes_anticipated_os_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    secret = "synthetic-error-must-not-print"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError(secret)

    monkeypatch.setattr(runtime, "launch", fail)
    assert runtime.main(["--runtime-dir", str(tmp_path), "--allowed-host", "safe.example"]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "could not start safely" in captured.err


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is required")
def test_encrypted_handoff_decrypts_fixed_oaep_envelope(tmp_path: Path) -> None:
    private_key = tmp_path / "handoff-private.pem"
    public_key = tmp_path / "handoff-public.pem"
    envelope = tmp_path / "handoff.json"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:4096",
            "-out",
            str(private_key),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.chmod(private_key, 0o600)
    subprocess.run(
        ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def encrypt(value: str) -> str:
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-encrypt",
                "-pubin",
                "-inkey",
                str(public_key),
                "-pkeyopt",
                "rsa_padding_mode:oaep",
                "-pkeyopt",
                "rsa_oaep_md:sha256",
                "-pkeyopt",
                "rsa_mgf1_md:sha256",
            ],
            input=value.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return base64.b64encode(result.stdout).decode("ascii")

    envelope.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tunnel_token": encrypt(_TUNNEL_TOKEN),
                "broker_bearer": encrypt(_BEARER),
                "origin_client_id": encrypt("synthetic-origin-client"),
                "origin_client_secret": encrypt("synthetic-origin-secret"),
            }
        )
    )
    os.chmod(envelope, 0o600)
    assert runtime.load_encrypted_credentials(str(envelope), str(private_key)) == {
        "tunnel_token": _TUNNEL_TOKEN,
        "broker_bearer": _BEARER,
        "origin_client_id": "synthetic-origin-client",
        "origin_client_secret": "synthetic-origin-secret",
    }


def test_encrypted_handoff_requires_exact_locked_files(tmp_path: Path) -> None:
    private_key = tmp_path / "handoff-private.pem"
    envelope = tmp_path / "handoff.json"
    private_key.write_text("private")
    envelope.write_text("{}")
    os.chmod(private_key, 0o644)
    os.chmod(envelope, 0o600)

    with pytest.raises(runtime.RuntimeLaunchError, match="handoff file"):
        runtime.load_encrypted_credentials(str(envelope), str(private_key))
    os.chmod(private_key, 0o600)
    with pytest.raises(runtime.RuntimeLaunchError, match="handoff"):
        runtime.load_encrypted_credentials(str(envelope), str(private_key))
    with pytest.raises(runtime.RuntimeLaunchError, match="supplied together"):
        runtime._credentials(str(envelope), None)
