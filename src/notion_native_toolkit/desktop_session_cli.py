"""Local JSON handoff between a durable SessionPool and an authorized UI host.

This command has no browser, network, or generated-code execution capability.
The UI host performs each returned action and supplies observed evidence. A
checkpoint is committed before an action is printed; lost output is not replayed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from notion_native_toolkit.ai_models import (
    select_model_by_metadata,
    validate_explicit_selection,
)
from notion_native_toolkit.context_files import ContextScopeError
from notion_native_toolkit.session_pool import (
    ObservationSource,
    ReasoningEffort,
    ResultObservation,
    SendObservation,
    SessionPool,
    SessionPoolError,
    UiReadback,
)
from notion_native_toolkit.session_store import (
    MAX_CHECKPOINT_BYTES,
    SessionStore,
    SessionStoreError,
)


def _keys(
    data: dict[str, Any], required: set[str], optional: set[str] | None = None
) -> None:
    if not required <= data.keys() or data.keys() - required - (optional or set()):
        raise ValueError("unexpected or missing input fields")


def _inventory(data: dict[str, Any]) -> dict[str, Any]:
    observed_at = datetime.fromisoformat(data["inventory_observed_at"])
    if (
        observed_at.tzinfo is None
        or not -30 <= (datetime.now(UTC) - observed_at).total_seconds() <= 300
    ):
        raise ValueError("model inventory must be a fresh, timezone-aware observation")
    inventory = data["inventory"]
    if not isinstance(inventory, dict):
        raise TypeError("inventory must be an object")
    return inventory


def _selected(inventory: dict[str, Any], model: str, effort: str) -> None:
    selected = validate_explicit_selection(
        inventory, model=model, reasoning_effort=effort
    )
    if selected is None or selected.is_disabled is not False:
        raise ValueError(
            "runner requires explicit enabled status in the model inventory"
        )


def _status(pool: SessionPool) -> dict[str, Any]:
    tasks = []
    for task_id in pool.task_ids:
        task = asdict(pool.task(task_id))
        task["result_count"] = len(task.pop("results"))
        tasks.append(task)
    pending = pool.pending_ui_action
    return {
        "session_id": pool.session_id,
        "status": pool.status,
        "in_flight_count": pool.in_flight_count,
        "pending_ui_action": asdict(pending) if pending else None,
        "tasks": tasks,
    }


def _apply(
    pool: SessionPool, command: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    if command == "submit":
        _keys(
            data,
            {"task_id", "prompt", "effort", "inventory", "inventory_observed_at"},
            {"model", "preferences", "max_retries"},
        )
        inventory = _inventory(data)
        model = data.get("model")
        if model is None:
            model = select_model_by_metadata(
                inventory,
                preferences=data.get("preferences", []),
                reasoning_effort=data["effort"],
            ).code
        elif "preferences" in data:
            raise ValueError(
                "choose an explicit model or metadata preferences, not both"
            )
        _selected(inventory, model, data["effort"])
        pool.submit(
            data["task_id"],
            data["prompt"],
            model=model,
            effort=ReasoningEffort(data["effort"]),
            max_retries=data.get("max_retries", 1),
        )
    elif command == "prepare":
        _keys(data, {"tab_id", "inventory", "inventory_observed_at"})
        inventory = _inventory(data)
        action = pool.prepare_next(tab_id=data["tab_id"])
        if action is not None:
            _selected(inventory, action.model, action.effort.value)
            return {"kind": "notion-desktop-action", "action": asdict(action)}
    elif command in {"observe-send", "reconcile-sent"}:
        _keys(
            data,
            {"attempt_id", "readback"}
            | ({"observation"} if command == "observe-send" else set()),
        )
        readback = data["readback"]
        if not isinstance(readback, dict):
            raise ValueError("readback must be an object")
        _keys(
            readback, {"model", "effort", "prompt_hash", "notion_thread_id", "source"}
        )
        observed = UiReadback(
            model=readback["model"],
            effort=ReasoningEffort(readback["effort"]),
            prompt_hash=readback["prompt_hash"],
            notion_thread_id=readback["notion_thread_id"],
            source=ObservationSource(readback["source"]),
        )
        if command == "reconcile-sent":
            pool.reconcile_uncertain_send(data["attempt_id"], observed)
        else:
            pool.observe_send(
                data["attempt_id"], SendObservation(data["observation"]), observed
            )
    elif command == "record-result":
        _keys(data, {"observation", "complete", "stable"})
        if data["complete"] is not True or data["stable"] is not True:
            raise ValueError("partial or unstable result must not be accepted")
        observation = data["observation"]
        if not isinstance(observation, dict):
            raise ValueError("result observation must be an object")
        values = dict(observation)
        values["effort"] = ReasoningEffort(values["effort"])
        values["source"] = ObservationSource(values["source"])
        pool.record_result(ResultObservation(**values))
    elif command in {"pause", "resume", "takeover", "cancel"}:
        _keys(data, set())
        {
            "pause": pool.pause,
            "resume": pool.resume,
            "takeover": pool.user_takeover,
            "cancel": pool.cancel,
        }[command]()
    elif command == "cancel-task":
        _keys(data, {"task_id"})
        pool.cancel_task(data["task_id"])
    elif command in {"observe-cancellation", "resolve-not-sent", "observe-failure"}:
        _keys(data, {"attempt_id"})
        {
            "observe-cancellation": pool.observe_cancellation,
            "resolve-not-sent": pool.resolve_uncertain_as_not_sent,
            "observe-failure": pool.observe_failure,
        }[command](data["attempt_id"])
    else:
        raise ValueError("unsupported command")
    return None


def execute(
    command: str, directory: Path, data: dict[str, Any], *, revision: int | None = None
) -> dict[str, Any]:
    """Apply one local transaction; the caller separately owns actual UI actions."""
    store = SessionStore(directory)
    if command == "init":
        _keys(data, set(), {"max_in_flight", "benchmark_prompt"})
        pool = SessionPool(**data)
        return {"schema_version": 1, "revision": store.create(pool), **_status(pool)}
    with store.locked(expected_revision=revision) as transaction:
        if command == "status":
            _keys(data, set())
            return {
                "schema_version": 1,
                "revision": transaction.revision,
                **_status(transaction.pool),
            }
        if command == "result":
            _keys(data, {"task_id"})
            task = transaction.pool.task(data["task_id"])
            return {
                "schema_version": 1,
                "revision": transaction.revision,
                "kind": "untrusted-notion-result",
                "execution_performed": False,
                "results": [
                    {**asdict(record), "observed_at": record.observed_at.isoformat()}
                    for record in task.results
                ],
            }
        if type(revision) is not int:
            raise SessionStoreError("mutations require an expected revision")
        if transaction.pool.pending_ui_action is not None and command not in {
            "observe-send",
            "recover",
            "pause",
            "prepare",
        }:
            raise SessionStoreError(
                "persisted prepared action may have been sent; observe or recover before mutation"
            )
        if command == "recover":
            _keys(data, set())
            transaction.pool = SessionPool.from_state(
                transaction.pool.to_state(), recovering=True
            )
            result = None
        else:
            result = _apply(transaction.pool, command, data)
        committed_revision = transaction.commit()
        return {
            "schema_version": 1,
            "revision": committed_revision,
            **(result or _status(transaction.pool)),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "status",
            "result",
            "submit",
            "prepare",
            "observe-send",
            "reconcile-sent",
            "record-result",
            "pause",
            "resume",
            "takeover",
            "cancel",
            "cancel-task",
            "recover",
            "observe-cancellation",
            "resolve-not-sent",
            "observe-failure",
        ],
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="absolute project-owned .notion-session-<name> directory",
    )
    parser.add_argument(
        "--revision",
        type=int,
        help="expected revision from the last successful command",
    )
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_CHECKPOINT_BYTES + 1)
        if len(raw) > MAX_CHECKPOINT_BYTES:
            raise ValueError("input exceeds byte limit")
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise TypeError("input must be a JSON object")
        result = execute(args.command, args.state_dir, data, revision=args.revision)
        encoded = json.dumps(result, ensure_ascii=False)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        ContextScopeError,
        SessionPoolError,
        SessionStoreError,
    ) as exc:
        # Input may contain private prompts or UI data: do not print exception text.
        sys.stderr.write(
            json.dumps(
                {
                    "ok": False,
                    "error": "local session command rejected",
                    "error_type": type(exc).__name__,
                }
            )
            + "\n"
        )
        raise SystemExit(2) from None
    sys.stdout.write(encoded + "\n")


if __name__ == "__main__":
    main()
