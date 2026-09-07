"""Real loopback transport test against synthetic roots; no Notion/Cloudflare calls."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def test_authenticated_loopback_roundtrip(tmp_path: Path) -> None:
    project = tmp_path / "project"
    repo = project / "fixture"
    repo.mkdir(parents=True)
    (project / "AGENTS.md").write_text("Global fixture guidance")
    (repo / "AGENTS.md").write_text("Local fixture guidance")
    (repo / "sample.py").write_text("print('CONTEXT_FIXTURE_OK')\n")
    codex = tmp_path / "codex"
    skill = codex / "skills" / "notion-native-toolkit"
    skill.mkdir(parents=True)
    (codex / "AGENTS.md").write_text("Codex fixture guidance")
    (skill / "SKILL.md").write_text("Skill fixture guidance")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = secrets.token_urlsafe(48)
    program = (
        "import sys; from pathlib import Path; "
        "from notion_native_toolkit.local_context import ContextScope; "
        "from notion_native_toolkit.local_context_mcp import create_mcp; "
        "create_mcp(ContextScope(Path(sys.argv[1]), Path(sys.argv[2]))).run(transport='streamable-http')"
    )
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "LOCAL_CONTEXT_BEARER_SECRET": token,
        "LOCAL_CONTEXT_PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(project), str(codex)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None, "Fixture server stopped before readiness"
                try:
                    denied = client.post("/mcp", json={})
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline, "Fixture server did not start"
                    time.sleep(0.05)
            assert denied.status_code == 401
            client.headers.update(
                {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                }
            )

            def call(method: str, params: dict, request_id: int) -> dict:
                response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    },
                )
                assert response.status_code == 200
                event = next(
                    line[6:]
                    for line in response.text.splitlines()
                    if line.startswith("data: ")
                )
                return json.loads(event)["result"]

            info = call(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
                1,
            )
            assert info["serverInfo"]["name"] == "local-context-broker"
            tools = call("tools/list", {}, 2)["tools"]
            assert len(tools) == 8
            for request_id, (name, arguments, expected) in enumerate(
                [
                    ("get_scope_manifest", {}, "fixture"),
                    (
                        "read_agent_guidance",
                        {"path": "fixture/sample.py"},
                        "Local fixture guidance",
                    ),
                    ("read_global_agent_guidance", {}, "Codex fixture guidance"),
                    (
                        "build_task_context",
                        {"path": "fixture/sample.py", "skill_ids": ["notion-native-toolkit"]},
                        "context_sha256",
                    ),
                    (
                        "read_skill",
                        {"skill_id": "notion-native-toolkit"},
                        "Skill fixture guidance",
                    ),
                    (
                        "read_project_excerpt",
                        {"path": "fixture/sample.py"},
                        "CONTEXT_FIXTURE_OK",
                    ),
                    (
                        "search_project",
                        {"path": "fixture", "query": "CONTEXT_FIXTURE_OK"},
                        "CONTEXT_FIXTURE_OK",
                    ),
                ],
                3,
            ):
                result = call(
                    "tools/call", {"name": name, "arguments": arguments}, request_id
                )
                assert expected in json.dumps(result)
                # Configured roots are now explicit authenticated scope metadata.
                identity = result["structuredContent"]["scope"]
                assert identity["project_root"] == str(project)
                assert identity["codex_instruction_root"] == str(codex)
                assert identity["mode"] == "custom"
                assert identity["read_only"] is True
                assert token not in json.dumps(result)
            bad = call(
                "tools/call",
                {"name": "read_project_excerpt", "arguments": {"path": "../outside"}},
                20,
            )
            assert "error" in bad["structuredContent"]
            assert (
                client.post(
                    "/mcp", headers={"Host": "evil.example"}, json={}
                ).status_code
                == 421
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
