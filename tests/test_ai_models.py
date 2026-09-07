from __future__ import annotations

import math

import pytest

from notion_native_toolkit.ai_models import (
    ModelSelectionError,
    select_model_by_metadata,
    validate_explicit_selection,
)


def _inventory() -> dict[str, object]:
    return {
        "models": [
            {
                "model": "slow-smart",
                "modelCardAttributes": {"speed": 2, "intelligence": 5, "cost": 5},
                "modelConfiguration": {"supportedReasoningEfforts": ["low", "high"]},
            },
            {
                "model": "fast-cheap",
                "modelCardAttributes": {"speed": 5, "intelligence": 3, "cost": 1},
                "modelConfiguration": {"supportedReasoningEfforts": ["low"]},
            },
            {
                "model": "disabled-best",
                "isDisabled": True,
                "modelCardAttributes": {"speed": 5, "intelligence": 5, "cost": 1},
                "modelConfiguration": {"supportedReasoningEfforts": ["high"]},
            },
        ]
    }


def test_validate_explicit_selection_requires_enabled_current_model_and_supported_effort() -> None:
    selected = validate_explicit_selection(
        _inventory(), model="slow-smart", reasoning_effort="high"
    )
    assert selected is not None and selected.code == "slow-smart"

    with pytest.raises(ModelSelectionError, match="not present"):
        validate_explicit_selection(_inventory(), model="missing", reasoning_effort=None)
    with pytest.raises(ModelSelectionError, match="disabled"):
        validate_explicit_selection(_inventory(), model="disabled-best", reasoning_effort=None)
    with pytest.raises(ModelSelectionError, match="does not support"):
        validate_explicit_selection(_inventory(), model="fast-cheap", reasoning_effort="high")


def test_validate_explicit_selection_does_not_allow_effort_with_automatic_model() -> None:
    with pytest.raises(ModelSelectionError, match="requires an explicit model"):
        validate_explicit_selection(_inventory(), model=None, reasoning_effort="high")


@pytest.mark.parametrize(
    "models, error",
    [
        ([{"model": "same"}, {"model": "same"}], "ambiguous duplicate"),
        ([{"model": "bad", "isDisabled": "false"}], "malformed isDisabled"),
        ([{"model": "bad", "isDisabled": None}], "malformed isDisabled"),
    ],
)
def test_validate_explicit_selection_rejects_ambiguous_or_malformed_inventory(
    models: list[dict[str, object]], error: str
) -> None:
    with pytest.raises(ModelSelectionError, match=error):
        validate_explicit_selection({"models": models}, model="same", reasoning_effort=None)


def test_legacy_missing_is_disabled_remains_selectable_but_is_disclosed() -> None:
    selected = validate_explicit_selection(
        {"models": [{"model": "legacy"}]}, model="legacy", reasoning_effort=None
    )
    assert selected is not None
    assert selected.is_disabled is None


def test_non_string_supported_effort_marks_support_unavailable() -> None:
    inventory = {
        "models": [{
            "model": "mixed-efforts",
            "modelConfiguration": {"supportedReasoningEfforts": ["high", 1]},
        }]
    }
    with pytest.raises(ModelSelectionError, match="does not report supported"):
        validate_explicit_selection(inventory, model="mixed-efforts", reasoning_effort="high")


def test_select_model_by_metadata_is_deterministic_and_filters_by_effort() -> None:
    assert select_model_by_metadata(_inventory(), preferences=["speed"]).code == "fast-cheap"
    assert select_model_by_metadata(_inventory(), preferences=["intelligence"]).code == "slow-smart"
    assert (
        select_model_by_metadata(
            _inventory(), preferences=["speed", "cost"], reasoning_effort="high"
        ).code
        == "slow-smart"
    )


def test_select_model_by_metadata_rejects_unknown_preferences() -> None:
    with pytest.raises(ModelSelectionError, match="Unknown model metadata"):
        select_model_by_metadata(_inventory(), preferences=["domain-expertise"])  # type: ignore[list-item]


@pytest.mark.parametrize("metric", [True, math.nan, math.inf, -math.inf, 0, 6])
def test_select_model_by_metadata_excludes_invalid_metric_values(metric: object) -> None:
    inventory = {
        "models": [{
            "model": "invalid-metric",
            "modelCardAttributes": {"speed": metric},
        }]
    }
    with pytest.raises(ModelSelectionError, match="No enabled"):
        select_model_by_metadata(inventory, preferences=["speed"])
