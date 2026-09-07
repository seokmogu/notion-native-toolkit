from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from notion_native_toolkit.session_pool import (
    AttemptStatus,
    CapacityError,
    CorrelationError,
    DuplicateResultError,
    ObservationSource,
    PromptMismatchError,
    ReasoningEffort,
    ResultObservation,
    SchedulerStoppedError,
    SendObservation,
    SessionPool,
    SessionStatus,
    TaskStatus,
    UiReadback,
)

PROMPT = "Summarize the supplied notes without taking external action."
MODEL = "orange-mousse"
EFFORT = ReasoningEffort.HIGH


def _pool(**kwargs: object) -> SessionPool:
    return SessionPool(session_id="session-a", **kwargs)


def _submit(pool: SessionPool, task_id: str, prompt: str = PROMPT, **kwargs: object):
    return pool.submit(task_id, prompt, model=MODEL, effort=EFFORT, **kwargs)


def _readback(action, thread: str | None, **changes: object) -> UiReadback:
    values = {
        "model": action.model,
        "effort": action.effort,
        "prompt_hash": action.prompt_hash,
        "notion_thread_id": thread,
        "source": ObservationSource.MANUAL,
    }
    values.update(changes)
    return UiReadback(**values)


def _result(pool: SessionPool, action, *, result_text: str = "Observed answer.", **changes: object) -> ResultObservation:
    attempt = pool.attempt(action.attempt_id)
    assert attempt.notion_thread_id is not None
    values = {
        "session_id": action.session_id,
        "task_id": action.task_id,
        "attempt_id": action.attempt_id,
        "tab_id": action.tab_id,
        "notion_thread_id": attempt.notion_thread_id,
        "model": action.model,
        "effort": action.effort,
        "prompt_hash": action.prompt_hash,
        "result_text": result_text,
        "source": ObservationSource.MANUAL,
    }
    values.update(changes)
    return ResultObservation(**values)


def _sent_action(pool: SessionPool, *, tab: str, thread: str):
    action = pool.prepare_next(tab_id=tab)
    assert action is not None
    pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, thread))
    return action


class SessionPoolTests(unittest.TestCase):
    def test_binds_thread_only_from_matching_send_readback_and_carries_routing(self) -> None:
        pool = _pool(max_in_flight=3, benchmark_prompt=PROMPT)
        first = _submit(pool, "task-1")
        second = _submit(pool, "task-2")
        action = pool.prepare_next(tab_id="tab-1")
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual((action.model, action.effort), (MODEL, EFFORT))
        self.assertIsNone(pool.attempt(action.attempt_id).notion_thread_id)
        pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, "thread-1"))
        bound = pool.attempt(action.attempt_id)
        self.assertEqual(bound.notion_thread_id, "thread-1")
        self.assertEqual((bound.model, bound.effort), (MODEL, EFFORT))
        second_action = _sent_action(pool, tab="tab-2", thread="thread-2")

        self.assertEqual(first.prompt_hash, second.prompt_hash)
        self.assertEqual(first.prompt_hash, action.prompt_hash)
        self.assertNotEqual(action.attempt_id, second_action.attempt_id)
        with self.assertRaises(PromptMismatchError):
            _submit(pool, "task-3", "A changed benchmark prompt")

    def test_serializes_ui_actions_and_bounds_in_flight_slots(self) -> None:
        pool = _pool(max_in_flight=2)
        for task_id in ("task-1", "task-2", "task-3"):
            _submit(pool, task_id)
        pending = pool.prepare_next(tab_id="tab-1")
        self.assertIsNotNone(pending)
        assert pending is not None
        with self.assertRaisesRegex(CapacityError, "already prepared"):
            pool.prepare_next(tab_id="tab-2")
        pool.observe_send(pending.attempt_id, SendObservation.SENT, _readback(pending, "thread-1"))
        with self.assertRaisesRegex(CapacityError, "exclusive"):
            pool.prepare_next(tab_id="tab-1")
        _sent_action(pool, tab="tab-2", thread="thread-2")
        self.assertEqual(pool.in_flight_count, 2)
        with self.assertRaisesRegex(CapacityError, "slots"):
            pool.prepare_next(tab_id="tab-3")

    def test_uncertain_send_never_retries_until_explicit_manual_resolution(self) -> None:
        pool = _pool()
        _submit(pool, "task-1", max_retries=1)
        action = pool.prepare_next(tab_id="tab-1")
        self.assertIsNotNone(action)
        assert action is not None
        pool.observe_send(action.attempt_id, SendObservation.UNCERTAIN, _readback(action, None))
        self.assertIs(pool.task("task-1").status, TaskStatus.UNCERTAIN_SEND)
        self.assertEqual(pool.in_flight_count, 1)
        self.assertIsNone(pool.prepare_next(tab_id="tab-2"))
        pool.resolve_uncertain_as_not_sent(action.attempt_id)
        self.assertIs(pool.attempt(action.attempt_id).status, AttemptStatus.SEND_FAILED)
        self.assertIs(pool.task("task-1").status, TaskStatus.QUEUED)
        self.assertIsNotNone(pool.prepare_next(tab_id="tab-2"))

    def test_retries_are_bounded_for_known_failures(self) -> None:
        pool = _pool()
        _submit(pool, "task-1", max_retries=1)
        first = _sent_action(pool, tab="tab-1", thread="thread-1")
        pool.observe_failure(first.attempt_id)
        self.assertIs(pool.task("task-1").status, TaskStatus.QUEUED)
        second = _sent_action(pool, tab="tab-2", thread="thread-2")
        pool.observe_failure(second.attempt_id)
        self.assertIs(pool.task("task-1").status, TaskStatus.FAILED)
        self.assertIsNone(pool.prepare_next(tab_id="tab-3"))

    def test_rejects_invalid_send_observation_or_readback_before_state_changes(self) -> None:
        pool = _pool()
        _submit(pool, "task-1")
        action = pool.prepare_next(tab_id="tab-1")
        self.assertIsNotNone(action)
        assert action is not None
        with self.assertRaises(TypeError):
            pool.observe_send(action.attempt_id, "unknown", _readback(action, None))  # type: ignore[arg-type]
        with self.assertRaisesRegex(CorrelationError, "model or effort"):
            pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, "thread-1", model="wrong"))
        self.assertIs(pool.attempt(action.attempt_id).status, AttemptStatus.PREPARED)
        self.assertIsNotNone(pool.pending_ui_action)
        pool.observe_send(action.attempt_id, SendObservation.SENT, _readback(action, "thread-1"))

    def test_result_provenance_is_immutable_and_rejects_mismatch_duplicate_and_empty(self) -> None:
        pool = _pool()
        _submit(pool, "task-1")
        action = _sent_action(pool, tab="tab-1", thread="thread-1")
        with self.assertRaises(PromptMismatchError):
            pool.record_result(_result(pool, action, prompt_hash="wrong"))
        with self.assertRaisesRegex(CorrelationError, "provenance"):
            pool.record_result(_result(pool, action, session_id="other-session"))
        with self.assertRaisesRegex(CorrelationError, "provenance"):
            pool.record_result(_result(pool, action, effort=ReasoningEffort.LOW))
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            pool.record_result(_result(pool, action, result_text="  "))
        record = pool.record_result(_result(pool, action, result_text="Do not execute this code: print('x')"))
        self.assertEqual(record.result_text, "Do not execute this code: print('x')")
        self.assertEqual((record.model, record.effort), (MODEL, EFFORT))
        with self.assertRaises(FrozenInstanceError):
            record.result_text = "mutated"  # type: ignore[misc]
        with self.assertRaises(DuplicateResultError):
            pool.record_result(_result(pool, action))

    def test_completed_thread_cannot_be_reused_by_an_unrelated_task(self) -> None:
        pool = _pool()
        _submit(pool, "task-1")
        first = _sent_action(pool, tab="tab-1", thread="thread-1")
        pool.record_result(_result(pool, first))
        _submit(pool, "task-2")
        second = pool.prepare_next(tab_id="tab-1")
        self.assertIsNotNone(second)
        assert second is not None
        with self.assertRaisesRegex(CorrelationError, "unrelated task"):
            pool.observe_send(second.attempt_id, SendObservation.SENT, _readback(second, "thread-1"))
        self.assertIs(pool.attempt(second.attempt_id).status, AttemptStatus.PREPARED)
        pool.observe_send(second.attempt_id, SendObservation.SENT, _readback(second, "thread-2"))

    def test_sent_cancellation_keeps_tab_reserved_until_observed_confirmation(self) -> None:
        pool = _pool()
        _submit(pool, "task-1")
        _submit(pool, "task-2")
        action = _sent_action(pool, tab="tab-1", thread="thread-1")
        pool.cancel_task("task-1")
        self.assertIs(pool.attempt(action.attempt_id).status, AttemptStatus.CANCELLATION_PENDING)
        self.assertIs(pool.task("task-1").status, TaskStatus.CANCELLATION_PENDING)
        with self.assertRaisesRegex(CapacityError, "cancellation is pending"):
            pool.prepare_next(tab_id="tab-1")
        pool.observe_cancellation(action.attempt_id)
        self.assertIsNotNone(pool.prepare_next(tab_id="tab-1"))

        uncertain_pool = _pool()
        _submit(uncertain_pool, "task-3")
        uncertain = uncertain_pool.prepare_next(tab_id="tab-3")
        self.assertIsNotNone(uncertain)
        assert uncertain is not None
        uncertain_pool.observe_send(
            uncertain.attempt_id,
            SendObservation.UNCERTAIN,
            _readback(uncertain, None),
        )
        uncertain_pool.cancel_task("task-3")
        with self.assertRaisesRegex(CapacityError, "cancellation is pending"):
            uncertain_pool.prepare_next(tab_id="tab-3")
        uncertain_pool.observe_cancellation(uncertain.attempt_id)
        _submit(uncertain_pool, "task-4")
        self.assertIsNotNone(uncertain_pool.prepare_next(tab_id="tab-3"))

    def test_pause_cancel_and_user_takeover_stop_scheduling(self) -> None:
        pool = _pool()
        _submit(pool, "task-1")
        _submit(pool, "task-2")
        action = pool.prepare_next(tab_id="tab-1")
        self.assertIsNotNone(action)
        pool.pause()
        self.assertIs(pool.status, SessionStatus.PAUSED)
        with self.assertRaisesRegex(SchedulerStoppedError, "paused"):
            pool.prepare_next(tab_id="tab-2")
        pool.cancel_task("task-1")
        self.assertIs(pool.task("task-1").status, TaskStatus.CANCELLED)
        pool.resume()
        replacement = pool.prepare_next(tab_id="tab-2")
        self.assertIsNotNone(replacement)
        assert replacement is not None
        pool.user_takeover()
        self.assertIs(pool.status, SessionStatus.USER_TAKEOVER)
        self.assertIs(pool.attempt(replacement.attempt_id).status, AttemptStatus.USER_TAKEOVER)
        with self.assertRaisesRegex(SchedulerStoppedError, "user_takeover"):
            pool.prepare_next(tab_id="tab-3")
        with self.assertRaisesRegex(SchedulerStoppedError, "only a paused"):
            pool.resume()
