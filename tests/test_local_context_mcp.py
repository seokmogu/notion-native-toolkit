from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from notion_native_toolkit import local_context_mcp
from notion_native_toolkit.local_context import ContextScope

_BEARER_SECRET = "test-static-bearer-secret-that-is-long-enough-123456"
_MCP_HEADERS = {
    "Authorization": f"Bearer {_BEARER_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _request(method: str, request_id: int, params: dict | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _initialize_params() -> dict:
    return {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "unit-test", "version": "0"},
    }


def _mcp_payload(response: httpx.Response) -> dict:
    """Decode the single JSON-RPC payload carried by Streamable HTTP SSE."""

    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"Missing MCP data event: {response.text!r}")


def test_streamable_http_server_is_authenticated_and_rebinding_protected(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOCAL_CONTEXT_BEARER_SECRET", _BEARER_SECRET)
    monkeypatch.delenv("LOCAL_CONTEXT_ALLOWED_HOST", raising=False)
    broker = local_context_mcp.create_mcp(ContextScope())

    assert broker.settings.host == "127.0.0.1"
    assert broker.settings.streamable_http_path == "/mcp"
    assert broker.settings.stateless_http is True
    assert broker.settings.auth is not None
    assert broker.settings.auth.required_scopes == ["local-context.read"]
    assert broker.settings.transport_security.enable_dns_rebinding_protection is True
    assert broker.settings.transport_security.allowed_hosts == ["127.0.0.1:8001"]
    assert "*" not in "".join(broker.settings.transport_security.allowed_hosts)
    assert broker.streamable_http_app() is not None

    for tool in asyncio.run(broker.list_tools()):
        annotations = tool.annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.openWorldHint is False
        assert annotations.idempotentHint is True


def test_additional_approved_host_requires_an_exact_env_value(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_CONTEXT_ALLOWED_HOST", "broker.example.test:8443")
    hosts, origins = local_context_mcp._approved_host(8001)

    assert hosts == ["127.0.0.1:8001", "broker.example.test:8443"]
    assert origins[-2:] == [
        "http://broker.example.test:8443",
        "https://broker.example.test:8443",
    ]

    monkeypatch.setenv("LOCAL_CONTEXT_ALLOWED_HOST", "*.example.test")
    with pytest.raises(RuntimeError, match="one exact host"):
        local_context_mcp._approved_host(8001)


def test_http_startup_requires_a_strong_env_bearer_secret(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_CONTEXT_TRANSPORT", "streamable-http")
    monkeypatch.delenv("LOCAL_CONTEXT_BEARER_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="LOCAL_CONTEXT_BEARER_SECRET"):
        local_context_mcp.main()

    monkeypatch.setenv("LOCAL_CONTEXT_BEARER_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="LOCAL_CONTEXT_BEARER_SECRET"):
        local_context_mcp.main()


def test_port_and_bearer_configuration_reject_unsafe_values(monkeypatch) -> None:
    for port in ("0", "65536"):
        monkeypatch.setenv("LOCAL_CONTEXT_PORT", port)
        with pytest.raises(RuntimeError, match="between 1 and 65535"):
            local_context_mcp._port()

    for secret in (_BEARER_SECRET + " ", "가" * 32):
        monkeypatch.setenv("LOCAL_CONTEXT_BEARER_SECRET", secret)
        assert local_context_mcp._configured_bearer_secret(required=False) is None
        with pytest.raises(RuntimeError, match="ASCII non-whitespace"):
            local_context_mcp._configured_bearer_secret(required=True)

    verifier = local_context_mcp.StaticBearerTokenVerifier(_BEARER_SECRET)
    assert asyncio.run(verifier.verify_token("가" * 32)) is None
    assert asyncio.run(verifier.verify_token(_BEARER_SECRET + " ")) is None


def test_stdio_does_not_require_http_bearer_secret(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.delenv("LOCAL_CONTEXT_BEARER_SECRET", raising=False)
    monkeypatch.setenv("LOCAL_CONTEXT_TRANSPORT", "stdio")
    monkeypatch.setattr(
        local_context_mcp.mcp, "run", lambda *, transport: calls.append(transport)
    )

    local_context_mcp.main()

    assert calls == ["stdio"]


def test_mcp_tool_returns_scope_errors_as_data(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    codex_root = tmp_path / "codex"
    (codex_root / "skills").mkdir(parents=True)
    monkeypatch.setattr(
        local_context_mcp,
        "scope",
        ContextScope(project_root=project_root, codex_root=codex_root),
    )
    result = local_context_mcp.read_project_excerpt("../outside")
    assert result == {
        "error": "Project paths must not contain traversal or control characters"
    }


def test_scoped_results_are_bounded() -> None:
    class OversizedManifestScope:
        def get_scope_manifest(self) -> dict:
            return {"payload": "x" * local_context_mcp._MAX_RESULT_BYTES}

    oversized = local_context_mcp._call_scope(
        OversizedManifestScope(), "get_scope_manifest"
    )

    assert oversized == {
        "error": "Local context result exceeds the response size limit"
    }


def test_successful_calls_include_scope_before_response_bounding(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "source.txt").write_text("sample\n")
    scope = ContextScope(tmp_path, tmp_path, scope_mode="fixture")
    for operation, kwargs in (
        ("read_project_excerpt", {"path": "source.txt"}),
        ("search_project", {"query": "sample"}),
    ):
        result = local_context_mcp._call_scope(scope, operation, **kwargs)
        assert result["scope"] == scope.scope_identity()
    monkeypatch.setattr(local_context_mcp, "_MAX_RESULT_BYTES", 20)
    assert "error" in local_context_mcp._call_scope(scope, "read_project_excerpt", path="source.txt")


@pytest.mark.parametrize(
    "error",
    [
        UnicodeDecodeError("utf-8", b"\\xff", 0, 1, "invalid start byte"),
        subprocess.TimeoutExpired(["rg"], timeout=5),
        OSError("/private/context-path"),
    ],
)
def test_scoped_operational_errors_are_sanitized(error: Exception) -> None:
    class FailingScope:
        def get_scope_manifest(self) -> dict:
            raise error

    failure = local_context_mcp._call_scope(FailingScope(), "get_scope_manifest")

    assert failure == {"error": "Local context operation could not be completed"}
    assert "private" not in str(failure)


def test_streamable_http_asgi_auth_and_protocol_are_safe(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    codex_root = tmp_path / "codex"
    (codex_root / "skills").mkdir(parents=True)
    monkeypatch.setenv("LOCAL_CONTEXT_BEARER_SECRET", _BEARER_SECRET)
    monkeypatch.delenv("LOCAL_CONTEXT_ALLOWED_HOST", raising=False)
    broker = local_context_mcp.create_mcp(
        ContextScope(project_root=project_root, codex_root=codex_root)
    )
    app = broker.streamable_http_app()

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8001",
            ) as client,
        ):
            denied = await client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    1,
                    {"name": "get_scope_manifest", "arguments": {}},
                ),
            )
            assert denied.status_code == 401
            assert _BEARER_SECRET not in denied.text

            invalid = await client.post(
                "/mcp",
                headers={**_MCP_HEADERS, "Authorization": "Bearer invalid"},
                json=_request("initialize", 2, _initialize_params()),
            )
            assert invalid.status_code == 401
            assert _BEARER_SECRET not in invalid.text

            rebinding = await client.post(
                "/mcp",
                headers={**_MCP_HEADERS, "Host": "rebind.example.test"},
                json=_request("initialize", 3, _initialize_params()),
            )
            assert rebinding.status_code == 421

            initialized = await client.post(
                "/mcp",
                headers=_MCP_HEADERS,
                json=_request("initialize", 4, _initialize_params()),
            )
            assert initialized.status_code == 200
            assert (
                _mcp_payload(initialized)["result"]["serverInfo"]["name"]
                == "local-context-broker"
            )

            tools = await client.post(
                "/mcp",
                headers=_MCP_HEADERS,
                json=_request("tools/list", 5),
            )
            assert tools.status_code == 200
            assert "get_scope_manifest" in {
                tool["name"] for tool in _mcp_payload(tools)["result"]["tools"]
            }

            normal_call = await client.post(
                "/mcp",
                headers=_MCP_HEADERS,
                json=_request(
                    "tools/call",
                    6,
                    {"name": "get_scope_manifest", "arguments": {}},
                ),
            )
            assert normal_call.status_code == 200
            assert (
                _mcp_payload(normal_call)["result"]["structuredContent"]["projects"]
                == []
            )

            safe_error = await client.post(
                "/mcp",
                headers=_MCP_HEADERS,
                json=_request(
                    "tools/call",
                    7,
                    {
                        "name": "read_project_excerpt",
                        "arguments": {"path": "../outside"},
                    },
                ),
            )
            assert safe_error.status_code == 200
            error_payload = _mcp_payload(safe_error)["result"]["structuredContent"]
            assert error_payload == {
                "error": "Project paths must not contain traversal or control characters"
            }
            assert str(project_root) not in safe_error.text
            assert _BEARER_SECRET not in safe_error.text

    asyncio.run(exercise())
