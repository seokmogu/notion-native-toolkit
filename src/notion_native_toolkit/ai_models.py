"""Validated, metadata-only helpers for Notion AI model inventories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
ModelPreference = Literal["speed", "intelligence", "cost"]
_PREFERENCE_FIELDS = frozenset(("speed", "intelligence", "cost"))


class ModelSelectionError(ValueError):
    """Raised when an explicit Notion AI selection cannot be validated."""


@dataclass(frozen=True)
class AIModel:
    """The inventory fields needed for selection and validation.

    ``is_disabled=None`` means the legacy inventory omitted ``isDisabled``. It
    remains selectable for compatibility, but callers can distinguish it from
    an explicit ``False`` value.
    """

    code: str
    is_disabled: bool | None
    supported_reasoning_efforts: tuple[str, ...] | None
    attributes: Mapping[str, Any]


def _available_models(inventory: Mapping[str, Any] | None) -> list[AIModel]:
    if not isinstance(inventory, Mapping) or not isinstance(inventory.get("models"), list):
        raise ModelSelectionError(
            "Notion AI model inventory is unavailable or malformed; cannot validate an explicit selection."
        )

    models: list[AIModel] = []
    seen_codes: set[str] = set()
    for item in inventory["models"]:
        if not isinstance(item, Mapping):
            raise ModelSelectionError("Notion AI model inventory contains a malformed model entry.")
        code = item.get("model")
        if not isinstance(code, str) or not code:
            raise ModelSelectionError("Notion AI model inventory contains a model without a valid code.")
        if code in seen_codes:
            raise ModelSelectionError(
                f"Notion AI model inventory contains ambiguous duplicate model code {code!r}."
            )
        seen_codes.add(code)

        disabled = item.get("isDisabled") if "isDisabled" in item else None
        if "isDisabled" in item and not isinstance(disabled, bool):
            raise ModelSelectionError(
                f"Model {code!r} has a malformed isDisabled value in the current inventory."
            )
        configuration = item.get("modelConfiguration")
        efforts = (
            configuration.get("supportedReasoningEfforts")
            if isinstance(configuration, Mapping)
            else None
        )
        supported = (
            tuple(efforts)
            if isinstance(efforts, list) and all(isinstance(effort, str) for effort in efforts)
            else None
        )
        attributes = item.get("modelCardAttributes")
        models.append(
            AIModel(
                code=code,
                is_disabled=disabled if isinstance(disabled, bool) else None,
                supported_reasoning_efforts=supported,
                attributes=attributes if isinstance(attributes, Mapping) else {},
            )
        )
    return models


def validate_explicit_selection(
    inventory: Mapping[str, Any] | None,
    *,
    model: str | None,
    reasoning_effort: str | None,
) -> AIModel | None:
    """Validate an explicit selection against the just-fetched inventory.

    An effort without a model would be applied to an unknown automatic choice,
    so it is deliberately rejected rather than silently falling back.
    """
    if model is None and reasoning_effort is None:
        return None
    if model is None:
        raise ModelSelectionError(
            "reasoning_effort requires an explicit model; automatic routing cannot be validated "
            "against model-specific supported efforts."
        )
    if not isinstance(model, str) or not model:
        raise ModelSelectionError("model must be a non-empty internal model code.")
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
        allowed = ", ".join(REASONING_EFFORTS)
        raise ModelSelectionError(
            f"Unsupported reasoning_effort {reasoning_effort!r}; expected one of: {allowed}"
        )

    selected = next((entry for entry in _available_models(inventory) if entry.code == model), None)
    if selected is None:
        raise ModelSelectionError(
            f"Model {model!r} is not present in the current Notion AI model inventory."
        )
    if selected.is_disabled:
        raise ModelSelectionError(f"Model {model!r} is disabled in the current Notion AI model inventory.")
    if reasoning_effort is not None:
        if selected.supported_reasoning_efforts is None:
            raise ModelSelectionError(
                f"Model {model!r} does not report supported reasoning efforts in the current inventory."
            )
        if reasoning_effort not in selected.supported_reasoning_efforts:
            supported = ", ".join(selected.supported_reasoning_efforts) or "none reported"
            raise ModelSelectionError(
                f"Model {model!r} does not support reasoning_effort {reasoning_effort!r}; "
                f"supported efforts: {supported}."
            )
    return selected


def select_model_by_metadata(
    inventory: Mapping[str, Any] | None,
    *,
    preferences: Sequence[ModelPreference],
    reasoning_effort: str | None = None,
) -> AIModel:
    """Choose an enabled model by caller-provided inventory metrics only.

    ``speed`` and ``intelligence`` are maximized; ``cost`` is minimized.
    Ties use the internal model code, making selection deterministic. This helper
    intentionally does not infer task-domain strengths from a model family/name.
    """
    if not preferences:
        raise ModelSelectionError("At least one metadata preference is required for model selection.")
    unknown = [preference for preference in preferences if preference not in _PREFERENCE_FIELDS]
    if unknown:
        raise ModelSelectionError(
            f"Unknown model metadata preference(s): {', '.join(map(repr, unknown))}."
        )
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
        allowed = ", ".join(REASONING_EFFORTS)
        raise ModelSelectionError(
            f"Unsupported reasoning_effort {reasoning_effort!r}; expected one of: {allowed}"
        )

    candidates = []
    for entry in _available_models(inventory):
        if entry.is_disabled is True:
            continue
        if reasoning_effort is not None and (
            entry.supported_reasoning_efforts is None
            or reasoning_effort not in entry.supported_reasoning_efforts
        ):
            continue
        values: list[float] = []
        for preference in preferences:
            value = entry.attributes.get(preference)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not 1 <= value <= 5
            ):
                break
            values.append(float(value))
        else:
            candidates.append((entry, values))

    if not candidates:
        raise ModelSelectionError(
            "No enabled Notion AI model has the requested metadata and reasoning-effort support."
        )

    def sort_key(candidate: tuple[AIModel, list[float]]) -> tuple[float | str, ...]:
        entry, values = candidate
        ranked = tuple(
            value if preference == "cost" else -value
            for preference, value in zip(preferences, values, strict=True)
        )
        return (*ranked, entry.code)

    return min(candidates, key=sort_key)[0]
