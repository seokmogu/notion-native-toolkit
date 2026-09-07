from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from notion_native_toolkit.mcp_server import (
    _extract_inference_text,
    notion_ai_ask,
    notion_ai_models,
)


def test_notion_ai_models_exposes_routing_metadata() -> None:
    model = {
        "model": "orange-mousse",
        "modelMessage": "GPT-5.6 Sol",
        "modelFamily": "openai",
        "modelProvider": "openai",
        "displayGroup": "intelligent",
        "modelCardAttributes": {"speed": 3, "intelligence": 5, "cost": 5},
        "modelConfiguration": {
            "defaultReasoningEffort": "medium",
            "supportedReasoningEfforts": ["none", "low", "high", "max"],
        },
    }

    with patch("notion_native_toolkit.mcp_server._load_client") as load_client:
        load_client.return_value.__enter__.return_value.get_available_models.return_value = {
            "models": [model]
        }
        result = notion_ai_models()

    assert "GPT-5.6 Sol [openai/openai]" in result
    assert "code=orange-mousse" in result
    assert "speed=3 intelligence=5 cost=5" in result
    assert "default_effort=medium" in result
    assert "supported_efforts=none,low,high,max" in result


def test_notion_ai_models_handles_malformed_nested_metadata() -> None:
    malformed = {
        "model": "legacy-model",
        "modelMessage": ["not text"],
        "modelCardAttributes": ["not a mapping"],
        "modelConfiguration": {"supportedReasoningEfforts": ["high", 3]},
        "isDisabled": "false",
    }
    with patch("notion_native_toolkit.mcp_server._load_client") as load_client:
        load_client.return_value.__enter__.return_value.get_available_models.return_value = {
            "models": [malformed, ["not a model"]]
        }
        result = notion_ai_models()

    assert "code=legacy-model" in result
    assert "supported_efforts=?" in result
    assert "(malformed isDisabled)" in result
    assert "- malformed model entry" in result


def test_notion_ai_ask_forwards_model_and_reasoning_effort() -> None:
    client = MagicMock()
    client.run_ai.return_value = iter([
        {
            "type": "patch",
            "v": [{"o": "a", "p": "/transcript/4/value/0/content", "v": "Summary"}],
        }
    ])

    with patch("notion_native_toolkit.mcp_server._load_client") as load_client:
        load_client.return_value.__enter__.return_value = client
        result = notion_ai_ask(
            "Summarize this",
            model="orange-mousse",
            reasoning_effort="high",
        )

    assert result == "Summary"
    client.run_ai.assert_called_once_with(
        "Summarize this",
        block_id=None,
        thread_id=None,
        model="orange-mousse",
        reasoning_effort="high",
    )


def test_extract_inference_text_preserves_root_value_content_patch_shape() -> None:
    chunks = [{
        "type": "patch",
        "v": [
            {"o": "a", "p": "/value/0/content", "v": "First "},
            {"o": "x", "p": "/value/1/content", "v": "second"},
        ],
    }]

    assert _extract_inference_text(chunks) == "First second"


def test_extract_inference_text_supports_observed_patch_and_agent_inference_shapes() -> None:
    chunks = [
        {
            "type": "patch",
            "v": [
                {"o": "a", "p": "/transcript/4/value/0/content", "v": "Hello "},
                {"o": "x", "p": "/transcript/4/value/0/content", "v": "world"},
                {
                    "o": "a",
                    "p": "/transcript/5",
                    "v": {
                        "type": "agent-inference",
                        "value": [{"content": "!"}, {"content": " Done."}],
                    },
                },
            ],
        },
        {"type": "patch", "v": [{"o": "replace", "p": "/anything", "v": "ignored"}]},
        {"type": "patch", "v": [{"o": "a", "p": "/foo/value/0/content", "v": "ignored"}]},
        {
            "type": "patch",
            "v": [{
                "o": "a",
                "p": "/foo/0",
                "v": {"type": "agent-inference", "value": [{"content": "ignored"}]},
            }],
        },
    ]

    assert _extract_inference_text(chunks) == "Hello world! Done."


def test_notion_ai_ask_rejects_unknown_stream_shape_without_returning_raw_chunks() -> None:
    client = MagicMock()
    client.run_ai.return_value = iter([{"type": "patch", "v": [{"o": "replace", "v": "secret"}]}])

    with patch("notion_native_toolkit.mcp_server._load_client") as load_client:
        load_client.return_value.__enter__.return_value = client
        with pytest.raises(RuntimeError, match="no text in supported stream formats"):
            notion_ai_ask("Summarize this")
