from __future__ import annotations

from unittest.mock import MagicMock, patch

from notion_native_toolkit.mcp_server import notion_ai_ask


def test_notion_ai_ask_forwards_model_and_reasoning_effort() -> None:
    client = MagicMock()
    client.run_ai.return_value = iter([{"type": "patch", "v": []}])

    with patch("notion_native_toolkit.mcp_server._load_client") as load_client:
        load_client.return_value.__enter__.return_value = client
        result = notion_ai_ask(
            "Summarize this",
            model="orange-mousse",
            reasoning_effort="high",
        )

    assert result == '[{"type": "patch", "v": []}]'
    client.run_ai.assert_called_once_with(
        "Summarize this",
        block_id=None,
        thread_id=None,
        model="orange-mousse",
        reasoning_effort="high",
    )
