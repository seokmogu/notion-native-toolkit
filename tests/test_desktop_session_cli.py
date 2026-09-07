from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from notion_native_toolkit.desktop_session_cli import execute
from notion_native_toolkit.session_pool import CapacityError, CorrelationError
from notion_native_toolkit.session_store import SessionStoreError

PROMPT = "Produce a synthetic analysis without external actions."


def inventory() -> dict:
    return {
        "inventory_observed_at": datetime.now(UTC).isoformat(),
        "inventory": {
            "models": [
                {
                    "model": "fixture-model",
                    "isDisabled": False,
                    "modelConfiguration": {"supportedReasoningEfforts": ["high"]},
                    "modelCardAttributes": {"intelligence": 4, "speed": 3, "cost": 2},
                }
            ]
        },
    }


def submit(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "prompt": PROMPT,
        "model": "fixture-model",
        "effort": "high",
        **inventory(),
    }


def readback(action: dict, thread: str) -> dict:
    return {
        "attempt_id": action["attempt_id"],
        "observation": "sent",
        "readback": {
            "model": action["model"],
            "effort": action["effort"],
            "prompt_hash": action["prompt_hash"],
            "notion_thread_id": thread,
            "source": "manual",
        },
    }


def result(action: dict, thread: str) -> dict:
    return {
        "complete": True,
        "stable": True,
        "observation": {
            **{key: value for key, value in action.items() if key != "prompt"},
            "notion_thread_id": thread,
            "result_text": "Synthetic completed answer",
            "source": "manual",
        },
    }


def test_two_in_flight_json_handoffs_remain_isolated_and_results_are_durable(
    tmp_path: Path,
) -> None:
    directory = tmp_path / ".notion-session-wire"
    assert execute("init", directory, {"benchmark_prompt": PROMPT})["revision"] == 0
    execute("submit", directory, submit("task-1"), revision=0)
    execute("submit", directory, submit("task-2"), revision=1)
    first = execute(
        "prepare", directory, {"tab_id": "tab-1", **inventory()}, revision=2
    )["action"]
    execute("observe-send", directory, readback(first, "thread-1"), revision=3)
    second = execute(
        "prepare", directory, {"tab_id": "tab-2", **inventory()}, revision=4
    )["action"]
    execute("observe-send", directory, readback(second, "thread-2"), revision=5)
    status = execute("status", directory, {})
    assert status["in_flight_count"] == 2
    assert first["prompt"] == second["prompt"] == PROMPT
    assert first["prompt_hash"] == second["prompt_hash"]
    assert first["attempt_id"] != second["attempt_id"]
    assert PROMPT not in json.dumps(status)
    with pytest.raises(CorrelationError):
        execute("record-result", directory, result(first, "thread-2"), revision=6)
    with pytest.raises(ValueError, match="partial"):
        execute(
            "record-result",
            directory,
            {**result(first, "thread-1"), "complete": False},
            revision=6,
        )
    execute("record-result", directory, result(second, "thread-2"), revision=6)
    final = execute("record-result", directory, result(first, "thread-1"), revision=7)
    assert final["in_flight_count"] == 0
    assert [task["status"] for task in final["tasks"]] == ["completed", "completed"]
    assert [task["result_count"] for task in final["tasks"]] == [1, 1]
    assert "Synthetic completed answer" not in json.dumps(final)
    fetched = execute("result", directory, {"task_id": "task-1"})
    assert fetched["kind"] == "untrusted-notion-result"
    assert fetched["execution_performed"] is False
    assert fetched["results"][0]["result_text"] == "Synthetic completed answer"


def test_lost_prepared_output_is_not_reemitted_and_recovery_preserves_slot(
    tmp_path: Path,
) -> None:
    directory = tmp_path / ".notion-session-crash"
    execute("init", directory, {})
    execute("submit", directory, submit("task-1"), revision=0)
    execute("prepare", directory, {"tab_id": "tab-1", **inventory()}, revision=1)
    with pytest.raises(CapacityError):
        execute("prepare", directory, {"tab_id": "tab-2", **inventory()}, revision=2)
    with pytest.raises(SessionStoreError, match="may have been sent"):
        execute("cancel-task", directory, {"task_id": "task-1"}, revision=2)
    with pytest.raises(SessionStoreError, match="may have been sent"):
        execute("cancel", directory, {}, revision=2)
    recovered = execute("recover", directory, {}, revision=2)
    assert recovered["status"] == "paused"
    assert recovered["in_flight_count"] == 1
    assert recovered["tasks"][0]["status"] == "uncertain_send"
    assert recovered["pending_ui_action"] is None
    with (directory / "checkpoint-000002.json").open() as source:
        state = json.load(source)["state"]
    attempt = state["attempts"][0]
    sent_evidence = readback(attempt, "observed-thread-after-crash")
    del sent_evidence["observation"]
    reconciled = execute("reconcile-sent", directory, sent_evidence, revision=3)
    assert reconciled["status"] == "paused"
    assert reconciled["tasks"][0]["status"] == "waiting_result"
    cancelled = execute("cancel-task", directory, {"task_id": "task-1"}, revision=4)
    assert cancelled["in_flight_count"] == 1
    assert cancelled["tasks"][0]["status"] == "cancellation_pending"


def test_stale_or_disabled_inventory_cannot_prepare_an_action(tmp_path: Path) -> None:
    directory = tmp_path / ".notion-session-models"
    execute("init", directory, {})
    stale = submit("task-1")
    stale["inventory_observed_at"] = (
        datetime.now(UTC) - timedelta(minutes=10)
    ).isoformat()
    with pytest.raises(ValueError, match="fresh"):
        execute("submit", directory, stale, revision=0)
    execute("submit", directory, submit("task-1"), revision=0)
    disabled = inventory()
    disabled["inventory"]["models"][0]["isDisabled"] = True
    with pytest.raises(ValueError, match="disabled"):
        execute("prepare", directory, {"tab_id": "tab-1", **disabled}, revision=1)
    assert execute("status", directory, {})["tasks"][0]["status"] == "queued"


def test_metadata_selection_reuses_validated_model_helper(tmp_path: Path) -> None:
    directory = tmp_path / ".notion-session-routing"
    execute("init", directory, {})
    task = submit("task-1")
    del task["model"]
    task["preferences"] = ["intelligence", "cost"]
    selected = execute("submit", directory, task, revision=0)
    assert selected["tasks"][0]["model"] == "fixture-model"


def test_mutations_need_a_revision_and_unexpected_fields_are_rejected(
    tmp_path: Path,
) -> None:
    directory = tmp_path / ".notion-session-revision"
    execute("init", directory, {})
    with pytest.raises(SessionStoreError, match="expected revision"):
        execute("submit", directory, submit("task-1"))
    with pytest.raises(ValueError):
        execute(
            "submit",
            directory,
            {**submit("task-1"), "arbitrary_shell": "must not execute"},
            revision=0,
        )
    assert execute("status", directory, {})["revision"] == 0


def test_real_cli_processes_share_checkpoints_without_leaking_rejected_input(
    tmp_path: Path,
) -> None:
    directory = tmp_path / ".notion-session-process"

    def run(
        command: str, data: dict, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "notion_native_toolkit.desktop_session_cli",
                command,
                "--state-dir",
                str(directory),
                *arguments,
            ],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    assert run("init", {}).returncode == 0
    assert run("submit", submit("task-1"), "--revision", "0").returncode == 0
    observed = run("status", {})
    assert json.loads(observed.stdout)["revision"] == 1
    failed = run("submit", {"prompt": "SYNTHETIC_SECRET_INPUT"}, "--revision", "1")
    assert failed.returncode == 2
    assert not failed.stdout
    assert "SYNTHETIC_SECRET_INPUT" not in failed.stderr
    invalid_prompt = run(
        "submit", {**submit("task-2"), "prompt": 17}, "--revision", "1"
    )
    assert invalid_prompt.returncode == 2
    assert json.loads(invalid_prompt.stderr)["error_type"] == "TypeError"
    prepared = run("prepare", {"tab_id": "tab-1", **inventory()}, "--revision", "1")
    action = json.loads(prepared.stdout)["action"]
    assert (
        run("observe-send", readback(action, "thread-1"), "--revision", "2").returncode
        == 0
    )
    assert (
        run("record-result", result(action, "thread-1"), "--revision", "3").returncode
        == 0
    )
    fetched = run("result", {"task_id": "task-1"})
    assert fetched.returncode == 0
    record = json.loads(fetched.stdout)["results"][0]
    assert record["result_text"] == "Synthetic completed answer"
    assert datetime.fromisoformat(record["observed_at"]).tzinfo is not None
