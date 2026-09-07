"""MCP server exposing Notion Internal API (AI, search, usage)."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from notion_native_toolkit.browser_state import find_storage_state_cookie
from notion_native_toolkit.internal import NotionInternalClient
from notion_native_toolkit.profiles import get_profile

logger = logging.getLogger(__name__)

COOKIES_PATH = Path(
    os.getenv(
        "NOTION_COOKIES_PATH",
        str(Path.home() / ".chrome-automation-profile" / "cookies.json"),
    )
)

mcp = FastMCP("notion-internal")

_INFERENCE_CONTENT_PATH = re.compile(
    r"(?:/value/\d+/content|/transcript/\d+/value/\d+/content)\Z"
)
_AGENT_INFERENCE_PATH = re.compile(r"(?:/value/\d+|/transcript/\d+)\Z")


def _extract_inference_text(chunks: list[Mapping[str, Any]]) -> str:
    """Extract text from the two observed ``asPatchResponse`` inference shapes.

    Supported shapes are root ``/value/<index>/content`` and transcript
    ``/transcript/<index>/value/<index>/content`` patches, plus appended
    ``agent-inference`` values at their corresponding parent paths. Unknown
    patches are ignored intentionally; this is not a generic JSON-patch
    interpreter.
    """
    text_parts: list[str] = []
    for chunk in chunks:
        if chunk.get("type") != "patch":
            continue
        operations = chunk.get("v")
        if not isinstance(operations, list):
            continue
        for operation in operations:
            if not isinstance(operation, Mapping):
                continue
            op = operation.get("o")
            path = operation.get("p")
            value = operation.get("v")
            if (
                op in ("a", "x")
                and isinstance(path, str)
                and _INFERENCE_CONTENT_PATH.fullmatch(path) is not None
                and isinstance(value, str)
            ):
                text_parts.append(value)
            elif (
                op == "a"
                and isinstance(path, str)
                and _AGENT_INFERENCE_PATH.fullmatch(path) is not None
                and isinstance(value, Mapping)
                and value.get("type") == "agent-inference"
            ):
                parts = value.get("value")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if isinstance(part, Mapping) and isinstance(part.get("content"), str):
                        text_parts.append(part["content"])
    return "".join(text_parts)


def _safe_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_text(value: object, default: str = "?") -> str:
    return value if isinstance(value, str) else default


def _load_client() -> NotionInternalClient:
    """Build client from cookies.json or env vars.

    Auth priority:
      1. NOTION_TOKEN_V2 env var (explicit)
      2. NOTION_PROFILE / NOTION_NATIVE_PROFILE browser_state_path
      3. NOTION_BROWSER_STATE_PATH
      4. ~/.chrome-automation-profile/cookies.json (legacy Playwright sync)

    Required env vars:
      - NOTION_SPACE_ID: workspace ID (always required)

    Optional env vars:
      - NOTION_TOKEN_V2: skip cookies.json lookup
      - NOTION_USER_ID: override user from cookies
      - NOTION_PROFILE / NOTION_NATIVE_PROFILE: toolkit profile name
      - NOTION_BROWSER_STATE_PATH: Playwright storage_state JSON path
      - NOTION_COOKIES_PATH: custom cookies.json location
    """
    token = os.getenv("NOTION_TOKEN_V2")
    space_id = os.getenv("NOTION_SPACE_ID")
    user_id = os.getenv("NOTION_USER_ID")

    profile_name = os.getenv("NOTION_PROFILE") or os.getenv("NOTION_NATIVE_PROFILE")
    if not token and profile_name:
        try:
            profile = get_profile(profile_name)
        except ValueError:
            profile = None
        if profile is not None:
            token = find_storage_state_cookie(profile.browser_state_path, "token_v2")
            user_id = user_id or find_storage_state_cookie(
                profile.browser_state_path,
                "notion_user_id",
            )
            space_id = space_id or profile.space_id

    browser_state_path = os.getenv("NOTION_BROWSER_STATE_PATH")
    if not token and browser_state_path:
        token = find_storage_state_cookie(browser_state_path, "token_v2")
        user_id = user_id or find_storage_state_cookie(
            browser_state_path,
            "notion_user_id",
        )

    if not token and COOKIES_PATH.exists():
        cookies = json.loads(COOKIES_PATH.read_text())
        token = next(
            (c["value"] for c in cookies if c["name"] == "token_v2" and "notion.so" in c.get("domain", "")),
            None,
        )
        user_id = user_id or next(
            (c["value"] for c in cookies if c["name"] == "notion_user_id" and "notion.so" in c.get("domain", "")),
            None,
        )

    if not token:
        hints = [
            "Notion 인증을 찾을 수 없습니다. 다음 중 하나를 확인하세요:",
            "",
            "1) cookies.json 방식 (권장):",
            "   - notion-native browser sync-chrome-cookies --profile <profile> --validate-internal",
            "   - MCP env에 NOTION_PROFILE=<profile> 설정",
            f"   - 레거시 쿠키 파일 경로: {COOKIES_PATH}",
            "   - 쿠키에 token_v2 (domain: .notion.so) 항목이 있어야 함",
            "",
            "2) 환경변수 방식:",
            "   export NOTION_TOKEN_V2='<token_v2 쿠키값>'",
            "   - Chrome DevTools > Application > Cookies > notion.so > token_v2",
            "",
            "3) token_v2 만료 (약 1년):",
            "   - 401/403 에러 시 브라우저에서 Notion 재로그인 후 쿠키 재동기화",
        ]
        raise RuntimeError("\n".join(hints))

    if not space_id:
        hints = [
            "NOTION_SPACE_ID가 설정되지 않았습니다.",
            "",
            "확인 방법:",
            "  - Notion 워크스페이스 Settings > ... > space ID 복사",
            "  - 또는 브라우저 DevTools Network 탭에서 spaceId 검색",
            "",
            "설정:",
            "  export NOTION_SPACE_ID='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'",
        ]
        raise RuntimeError("\n".join(hints))

    return NotionInternalClient(
        token_v2=token,
        space_id=space_id,
        user_id=user_id,
        rate_limit=0.3,
    )


@mcp.tool()
def notion_ai_models() -> str:
    """List available AI models in the Notion workspace.

    Returns model names, families (openai/anthropic/gemini), and capabilities.
    """
    with _load_client() as client:
        result = client.get_available_models()
    if not isinstance(result, Mapping) or not isinstance(result.get("models"), list):
        return "Failed to fetch models"
    models = result["models"]
    lines = []
    for m in models:
        if not isinstance(m, dict):
            lines.append("- malformed model entry")
            continue
        name = _safe_text(m.get("modelMessage"), _safe_text(m.get("model")))
        family = _safe_text(m.get("modelFamily"))
        provider = _safe_text(m.get("modelProvider"), family)
        group = _safe_text(m.get("displayGroup"))
        code = _safe_text(m.get("model"))
        card = _safe_mapping(m.get("modelCardAttributes"))
        configuration = _safe_mapping(m.get("modelConfiguration"))
        supported_efforts = configuration.get("supportedReasoningEfforts")
        supported = (
            ",".join(supported_efforts)
            if isinstance(supported_efforts, list) and all(isinstance(effort, str) for effort in supported_efforts)
            else "?"
        )
        characteristics = (
            f"speed={card.get('speed', '?')} "
            f"intelligence={card.get('intelligence', '?')} "
            f"cost={card.get('cost', '?')}"
        )
        effort = _safe_text(configuration.get("defaultReasoningEffort"))
        has_disabled = "isDisabled" in m
        disabled_value = m.get("isDisabled")
        disabled = (
            " (disabled)"
            if disabled_value is True
            else " (legacy isDisabled missing)"
            if not has_disabled
            else " (malformed isDisabled)"
            if not isinstance(disabled_value, bool)
            else ""
        )
        lines.append(
            f"- {name} [{family}/{provider}] group={group} code={code} "
            f"{characteristics} default_effort={effort} "
            f"supported_efforts={supported or '?'}{disabled}"
        )
    return "\n".join(lines)


@mcp.tool()
def notion_ai_usage() -> str:
    """Get AI credit usage and limits for the workspace.

    Shows current period usage, lifetime totals, and remaining credits.
    """
    with _load_client() as client:
        result = client.get_ai_usage()
    if not result:
        return "Failed to fetch AI usage"
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def notion_ai_ask(
    prompt: str,
    block_id: str | None = None,
    thread_id: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Run Notion AI with a prompt and return the streamed response.

    Args:
        prompt: The question or instruction for Notion AI.
        block_id: Optional page/block ID for context.
        thread_id: Optional thread ID to continue a conversation.
        model: Internal model code from ``notion_ai_models``. Omit for automatic routing.
        reasoning_effort: ``none``, ``minimal``, ``low``, ``medium``, ``high``, ``xhigh``, or ``max``.
            Requires ``model`` so support can be validated against the current inventory.
    """
    with _load_client() as client:
        chunks = list(
            client.run_ai(
                prompt,
                block_id=block_id,
                thread_id=thread_id,
                model=model,
                reasoning_effort=reasoning_effort,
            )
        )

    text = _extract_inference_text(chunks)
    if not text:
        raise RuntimeError("Notion AI returned no text in supported stream formats.")
    return text


@mcp.tool()
def notion_ai_agents() -> str:
    """List custom AI agents configured in the workspace."""
    with _load_client() as client:
        result = client.get_custom_agents()
    if not result:
        return "Failed to fetch custom agents"
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def notion_ai_connectors() -> str:
    """List AI connector integrations (Slack, Calendar, etc.)."""
    with _load_client() as client:
        result = client.get_ai_connectors()
    if not result:
        return "Failed to fetch AI connectors"
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def notion_search(query: str, limit: int = 10) -> str:
    """Search across the Notion workspace (richer than official API).

    Args:
        query: Search text.
        limit: Max results (default 10).
    """
    with _load_client() as client:
        result = client.search(query, limit=limit)
    if not result:
        return "Search failed"
    # Summarize results
    records = result.get("results", [])
    if not records:
        return "No results found"
    lines = []
    for r in records[:limit]:
        title = r.get("highlight", {}).get("text", r.get("id", "?"))
        lines.append(f"- {title} (id: {r.get('id', '?')})")
    return f"Found {len(records)} results:\n" + "\n".join(lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
