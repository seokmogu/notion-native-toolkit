"""MCP server exposing Notion Internal API (AI, search, usage)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from notion_native_toolkit.internal import NotionInternalClient

logger = logging.getLogger(__name__)

COOKIES_PATH = Path(
    os.getenv(
        "NOTION_COOKIES_PATH",
        str(Path.home() / ".chrome-automation-profile" / "cookies.json"),
    )
)

mcp = FastMCP("notion-internal")


def _load_client() -> NotionInternalClient:
    """Build client from cookies.json or env vars.

    Auth priority:
      1. NOTION_TOKEN_V2 env var (explicit)
      2. ~/.chrome-automation-profile/cookies.json (Playwright sync)

    Required env vars:
      - NOTION_SPACE_ID: workspace ID (always required)

    Optional env vars:
      - NOTION_TOKEN_V2: skip cookies.json lookup
      - NOTION_USER_ID: override user from cookies
      - NOTION_COOKIES_PATH: custom cookies.json location
    """
    token = os.getenv("NOTION_TOKEN_V2")
    space_id = os.getenv("NOTION_SPACE_ID")
    user_id = os.getenv("NOTION_USER_ID")

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
            f"   쿠키 파일 경로: {COOKIES_PATH}",
            "   - Playwright로 Notion 로그인 후 쿠키를 저장했는지 확인",
            "   - notion-native profile init → notion-native login 실행",
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
    if not result or "models" not in result:
        return "Failed to fetch models"
    models = result["models"]
    lines = []
    for m in models:
        name = m.get("modelMessage", m.get("model", "?"))
        family = m.get("modelFamily", "?")
        group = m.get("displayGroup", "?")
        code = m.get("model", "?")
        disabled = " (disabled)" if m.get("isDisabled") else ""
        lines.append(f"- {name} [{family}] group={group} code={code}{disabled}")
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
def notion_ai_ask(prompt: str, block_id: str | None = None, thread_id: str | None = None) -> str:
    """Run Notion AI with a prompt and return the streamed response.

    Args:
        prompt: The question or instruction for Notion AI.
        block_id: Optional page/block ID for context.
        thread_id: Optional thread ID to continue a conversation.
    """
    with _load_client() as client:
        chunks = list(client.run_ai(prompt, block_id=block_id, thread_id=thread_id))

    # Extract text from streaming patches
    text_parts: list[str] = []
    for chunk in chunks:
        ctype = chunk.get("type", "")
        if ctype == "patch":
            for v in chunk.get("v", []):
                op = v.get("o")
                path = v.get("p", "")
                val = v.get("v", "")
                # append or extend on inference content
                if op in ("a", "x") and "/value/" in path and "content" in path:
                    if isinstance(val, str):
                        text_parts.append(val)
                elif op == "a" and isinstance(val, dict) and val.get("type") == "agent-inference":
                    for part in val.get("value", []):
                        if isinstance(part, dict) and "content" in part:
                            text_parts.append(part["content"])

    return "".join(text_parts) if text_parts else json.dumps(chunks[-3:], ensure_ascii=False) if chunks else "No response"


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
