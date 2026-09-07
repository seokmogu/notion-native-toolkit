from __future__ import annotations

from copy import deepcopy

import pytest

from notion_native_toolkit.session_pool import (
    AttemptStatus,
    CapacityError,
    CorrelationError,
    ObservationSource,
    ReasoningEffort,
    ResultObservation,
    SchedulerStoppedError,
    SendObservation,
    SessionPool,
    SessionStatus,
    TaskStatus,
    UiReadback,
)

PROMPT = "Keep this exact prompt; never execute: __import__('os').system('false')."
MODEL = "orange-mousse"


def _pool() -> SessionPool:
    return SessionPool(session_id="session-a")


def _submit(pool: SessionPool, task_id: str) -> None:
    pool.submit(task_id, PROMPT, model=MODEL, effort=ReasoningEffort.HIGH)


def _readback(action, thread_id: str | None, **changes: object) -> UiReadback:
    values = {
        "model": action.model,
        "effort": action.effort,
        "prompt_hash": action.prompt_hash,
        "notion_thread_id": thread_id,
        "source": ObservationSource.MANUAL,
    }
    values.update(changes)
    return UiReadback(**values)


def test_round_trip_preserves_exact_state_results_hashes_and_task_order() -> None:
    pool = _pool()
    _submit(pool, "task-1")
    action = pool.prepare_next(tab_id="tab-1")
    assert action is not None
    pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, "thread-1"))
    pool.record_result(
        ResultObservation(
            session_id=action.session_id,
            task_id=action.task_id,
            attempt_id=action.attempt_id,
            tab_id=action.tab_id,
            notion_thread_id="thread-1",
            model=action.model,
            effort=action.effort,
            prompt_hash=action.prompt_hash,
            result_text="Exact result, including code-like text: print('never run').",
            source=ObservationSource.MANUAL,
        )
    )
    _submit(pool, "task-2")

    state = pool.to_state()
    restored = SessionPool.from_state(state, recovering=False)

    assert restored.to_state() == state
    assert restored.task_ids == ("task-1", "task-2")
    assert restored.task("task-1").results[0].result_text == "Exact result, including code-like text: print('never run')."


def test_recovery_pauses_and_converts_prepared_send_without_releasing_locks() -> None:
    pool = _pool()
    _submit(pool, "task-1")
    sent = pool.prepare_next(tab_id="tab-1")
    assert sent is not None
    pool.observe_send(sent.attempt_id, SendObservation.SENT, _readback(sent, "thread-1"))
    _submit(pool, "task-2")
    prepared = pool.prepare_next(tab_id="tab-2")
    assert prepared is not None

    restored = SessionPool.from_state(pool.to_state())

    assert restored.status is SessionStatus.PAUSED
    assert restored.pending_ui_action is None
    assert restored.in_flight_count == 2
    assert restored.attempt(sent.attempt_id).status is AttemptStatus.SENT
    assert restored.attempt(prepared.attempt_id).status is AttemptStatus.UNCERTAIN_SEND
    assert restored.task("task-2").status is TaskStatus.UNCERTAIN_SEND
    with pytest.raises(SchedulerStoppedError):
        restored.prepare_next(tab_id="tab-3")
    restored.resume()
    _submit(restored, "task-3")
    with pytest.raises(CapacityError, match="slots"):
        restored.prepare_next(tab_id="tab-3")


def test_recovery_keeps_cancellation_pending_attempts_and_tabs_reserved() -> None:
    pool = _pool()
    _submit(pool, "task-1")
    action = pool.prepare_next(tab_id="tab-1")
    assert action is not None
    pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, "thread-1"))
    pool.cancel_task("task-1")

    restored = SessionPool.from_state(pool.to_state())

    assert restored.status is SessionStatus.PAUSED
    assert restored.in_flight_count == 1
    assert restored.attempt(action.attempt_id).status is AttemptStatus.CANCELLATION_PENDING
    restored.resume()
    _submit(restored, "task-2")
    with pytest.raises(CapacityError, match="exclusive"):
        restored.prepare_next(tab_id="tab-1")


def test_uncertain_reconciliation_requires_matching_observed_thread_and_is_atomic() -> None:
    pool = _pool()
    _submit(pool, "task-1")
    prepared = pool.prepare_next(tab_id="tab-1")
    assert prepared is not None
    restored = SessionPool.from_state(pool.to_state())
    before = restored.to_state()

    with pytest.raises(CorrelationError):
        restored.reconcile_uncertain_send(
            prepared.attempt_id,
            _readback(prepared, "thread-1", model="different-model"),
        )
    assert restored.to_state() == before
    with pytest.raises(CorrelationError, match="requires an observed"):
        restored.reconcile_uncertain_send(prepared.attempt_id, _readback(prepared, None))
    assert restored.to_state() == before

    reconciled = restored.reconcile_uncertain_send(prepared.attempt_id, _readback(prepared, "thread-1"))
    assert reconciled.status is AttemptStatus.SENT
    assert restored.task("task-1").status is TaskStatus.WAITING_RESULT
    assert restored.to_state()["thread_owners"] == {"thread-1": "task-1"}


def test_reconcile_uncertain_send_binds_observed_thread_and_keeps_recovery_paused() -> None:
    pool = _pool()
    _submit(pool, "task-1")
    first = pool.prepare_next(tab_id="tab-1")
    assert first is not None
    pool.observe_send(first.attempt_id, SendObservation.SENT, _readback(first, "thread-1"))
    _submit(pool, "task-2")
    prepared = pool.prepare_next(tab_id="tab-2")
    assert prepared is not None
    restored = SessionPool.from_state(pool.to_state())
    before = restored.to_state()

    with pytest.raises(CorrelationError, match="unrelated task"):
        restored.reconcile_uncertain_send(prepared.attempt_id, _readback(prepared, "thread-1"))
    assert restored.to_state() == before

    resolved = restored.reconcile_uncertain_send(prepared.attempt_id, _readback(prepared, "thread-2"))
    assert resolved.status is AttemptStatus.SENT
    assert restored.status is SessionStatus.PAUSED
    assert restored.task("task-2").status is TaskStatus.WAITING_RESULT
    with pytest.raises(SchedulerStoppedError):
        restored.prepare_next(tab_id="tab-3")


def test_reconcile_uncertain_send_rejects_a_changed_bound_thread_without_mutation() -> None:
    pool = _pool()
    _submit(pool, "task-1")
    action = pool.prepare_next(tab_id="tab-1")
    assert action is not None
    pool.observe_send(action.attempt_id, SendObservation.UNCERTAIN, _readback(action, "thread-1"))
    before = pool.to_state()

    with pytest.raises(CorrelationError, match="cannot be rebound"):
        pool.reconcile_uncertain_send(action.attempt_id, _readback(action, "thread-2"))

    assert pool.to_state() == before


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda state: state.__setitem__("schema_version", 2), ValueError),
        (lambda state: state["tasks"][0].__setitem__("prompt_hash", "0" * 64), Exception),
        (lambda state: state["thread_owners"].__setitem__("thread-x", "missing-task"), CorrelationError),
        (lambda state: state["tasks"][0].__setitem__("status", "queued"), CorrelationError),
    ],
)
def test_reconstruction_rejects_bad_schema_hash_references_and_statuses(mutate, error: type[Exception]) -> None:
    pool = _pool()
    _submit(pool, "task-1")
    action = pool.prepare_next(tab_id="tab-1")
    assert action is not None
    pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, "thread-1"))
    state = deepcopy(pool.to_state())

    mutate(state)

    with pytest.raises(error):
        SessionPool.from_state(state, recovering=False)


def test_reconstruction_rejects_shapes_over_task_limit_before_parsing() -> None:
    pool = _pool()
    state = pool.to_state()
    state["tasks"] = [{}, *([{}] * 512)]

    with pytest.raises(ValueError, match="limits"):
        SessionPool.from_state(state)
