"""Offline scheduling contracts for approved Notion desktop sessions.

This module deliberately does not import a browser, call an API, or execute
generated content.  An external UI adapter (or a human operator) receives a
``UiAction`` and reports an explicit observation back to ``SessionPool``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from typing import Protocol, TypeVar
from uuid import uuid4

MIN_IN_FLIGHT_SLOTS = 2
MAX_IN_FLIGHT_SLOTS = 3
MAX_RETRIES = 3
STATE_SCHEMA_VERSION = 1
MAX_STATE_TASKS = 512
MAX_STATE_ATTEMPTS = 2048
MAX_STATE_BYTES = 4 * 1024 * 1024

_StateEnum = TypeVar("_StateEnum", bound=Enum)


class SessionPoolError(RuntimeError):
    """Base error for state-machine and correlation failures."""


class SchedulerStoppedError(SessionPoolError):
    """Raised when scheduling is paused, cancelled, or handed to a user."""


class CapacityError(SessionPoolError):
    """Raised when an action or in-flight slot is already reserved."""


class CorrelationError(SessionPoolError):
    """Raised when an external observation does not match its provenance."""


class DuplicateResultError(CorrelationError):
    """Raised when an attempt already has an immutable accepted result."""


class PromptMismatchError(CorrelationError):
    """Raised when a benchmark or result has a different prompt hash."""


class SessionStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    USER_TAKEOVER = "user_takeover"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PREPARED = "prepared"
    WAITING_RESULT = "waiting_result"
    UNCERTAIN_SEND = "uncertain_send"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLATION_PENDING = "cancellation_pending"
    CANCELLED = "cancelled"


class AttemptStatus(str, Enum):
    PREPARED = "prepared"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    UNCERTAIN_SEND = "uncertain_send"
    COMPLETED = "completed"
    FAILED = "failed"
    USER_TAKEOVER = "user_takeover"
    CANCELLATION_PENDING = "cancellation_pending"
    CANCELLED = "cancelled"


class SendObservation(str, Enum):
    """What the adapter/operator knows about the attempted UI send."""

    SENT = "sent"
    NOT_SENT = "not_sent"
    UNCERTAIN = "uncertain"


class ReasoningEffort(str, Enum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ObservationSource(str, Enum):
    MANUAL = "manual"
    EXTERNAL_UI_ADAPTER = "external_ui_adapter"


@dataclass(frozen=True, slots=True)
class UiAction:
    """A serial UI action for an external adapter or a human to perform."""

    session_id: str
    task_id: str
    attempt_id: str
    tab_id: str
    model: str
    effort: ReasoningEffort
    prompt: str
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class UiReadback:
    """Values visibly read from the UI after the send interaction."""

    model: str
    effort: ReasoningEffort
    prompt_hash: str
    notion_thread_id: str | None
    source: ObservationSource


class ExternalUiAdapter(Protocol):
    """Optional transport boundary; implementations are intentionally external."""

    def present_action(self, action: UiAction) -> None:
        """Present one action to the desktop UI without changing pool state."""


@dataclass(frozen=True, slots=True)
class ResultObservation:
    """A result copied from an adapter or manual desktop observation."""

    session_id: str
    task_id: str
    attempt_id: str
    tab_id: str
    notion_thread_id: str
    model: str
    effort: ReasoningEffort
    prompt_hash: str
    result_text: str
    source: ObservationSource


@dataclass(frozen=True, slots=True)
class ResultRecord:
    """Immutable result plus the correlation evidence used to accept it."""

    session_id: str
    task_id: str
    attempt_id: str
    tab_id: str
    notion_thread_id: str
    model: str
    effort: ReasoningEffort
    prompt_hash: str
    result_text: str
    source: ObservationSource
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    attempt_id: str
    task_id: str
    tab_id: str
    notion_thread_id: str | None
    model: str
    effort: ReasoningEffort
    prompt_hash: str
    ordinal: int
    status: AttemptStatus


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_id: str
    model: str
    effort: ReasoningEffort
    prompt_hash: str
    status: TaskStatus
    max_retries: int
    attempt_ids: tuple[str, ...]
    results: tuple[ResultRecord, ...]


@dataclass(slots=True)
class _Attempt:
    attempt_id: str
    task_id: str
    tab_id: str
    notion_thread_id: str | None
    model: str
    effort: ReasoningEffort
    prompt_hash: str
    ordinal: int
    status: AttemptStatus = AttemptStatus.PREPARED

    def snapshot(self) -> AttemptSnapshot:
        return AttemptSnapshot(
            attempt_id=self.attempt_id,
            task_id=self.task_id,
            tab_id=self.tab_id,
            notion_thread_id=self.notion_thread_id,
            model=self.model,
            effort=self.effort,
            prompt_hash=self.prompt_hash,
            ordinal=self.ordinal,
            status=self.status,
        )


@dataclass(slots=True)
class _Task:
    task_id: str
    prompt: str
    prompt_hash: str
    model: str
    effort: ReasoningEffort
    max_retries: int
    status: TaskStatus = TaskStatus.QUEUED
    attempt_ids: list[str] = field(default_factory=list)
    results: list[ResultRecord] = field(default_factory=list)

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=self.task_id,
            model=self.model,
            effort=self.effort,
            prompt_hash=self.prompt_hash,
            status=self.status,
            max_retries=self.max_retries,
            attempt_ids=tuple(self.attempt_ids),
            results=tuple(self.results),
        )


class SessionPool:
    """A bounded, in-memory scheduler that serializes conceptual UI actions.

    A pool may have two or three attempts awaiting a result, but only one
    ``UiAction`` can be prepared at a time.  Calling ``observe_send`` releases
    that UI-action reservation.  ``UNCERTAIN`` deliberately retains the slot
    and never becomes a retry without an explicit manual resolution.
    """

    def __init__(
        self,
        *,
        max_in_flight: int = MIN_IN_FLIGHT_SLOTS,
        benchmark_prompt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if type(max_in_flight) is not int:
            raise TypeError("max_in_flight must be an integer")
        if max_in_flight not in range(MIN_IN_FLIGHT_SLOTS, MAX_IN_FLIGHT_SLOTS + 1):
            raise ValueError("max_in_flight must be 2 or 3")
        if benchmark_prompt is not None and not isinstance(benchmark_prompt, str):
            raise TypeError("benchmark_prompt must be a string")
        if benchmark_prompt is not None and not benchmark_prompt.strip():
            raise ValueError("benchmark_prompt must not be empty")
        self.session_id = session_id or f"session-{uuid4()}"
        _require_identifier("session_id", self.session_id)
        self.max_in_flight = max_in_flight
        self.benchmark_prompt_hash = _prompt_hash(benchmark_prompt) if benchmark_prompt else None
        self.status = SessionStatus.RUNNING
        self._tasks: dict[str, _Task] = {}
        self._attempts: dict[str, _Attempt] = {}
        self._thread_owners: dict[str, str] = {}
        self._pending_ui_attempt_id: str | None = None

    def submit(
        self,
        task_id: str,
        prompt: str,
        *,
        model: str,
        effort: ReasoningEffort,
        max_retries: int = 1,
    ) -> TaskSnapshot:
        """Queue immutable prompt content for a future external UI action."""
        self._require_not_cancelled()
        _require_identifier("task_id", task_id)
        if task_id == self.session_id:
            raise ValueError("task_id must differ from session_id")
        if task_id in self._tasks:
            raise ValueError(f"duplicate task_id: {task_id}")
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        _require_identifier("model", model)
        if not isinstance(effort, ReasoningEffort):
            raise TypeError("effort must be a ReasoningEffort")
        if type(max_retries) is not int:
            raise TypeError("max_retries must be an integer")
        if max_retries not in range(MAX_RETRIES + 1):
            raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}")
        prompt_hash = _prompt_hash(prompt)
        if self.benchmark_prompt_hash and prompt_hash != self.benchmark_prompt_hash:
            raise PromptMismatchError("task prompt does not match the benchmark prompt")
        task = _Task(
            task_id=task_id,
            prompt=prompt,
            prompt_hash=prompt_hash,
            model=model,
            effort=effort,
            max_retries=max_retries,
        )
        self._tasks[task_id] = task
        return task.snapshot()

    def prepare_next(self, *, tab_id: str) -> UiAction | None:
        """Reserve one slot and return the next action; does not send anything."""
        self._require_running()
        _require_identifier("tab_id", tab_id)
        if self._pending_ui_attempt_id is not None:
            raise CapacityError("a UI action is already prepared; record its send observation first")
        if self.in_flight_count >= self.max_in_flight:
            raise CapacityError("all in-flight slots are occupied")
        if any(
            attempt.status
            in {
                AttemptStatus.PREPARED,
                AttemptStatus.SENT,
                AttemptStatus.UNCERTAIN_SEND,
                AttemptStatus.CANCELLATION_PENDING,
            }
            and attempt.tab_id == tab_id
            for attempt in self._attempts.values()
        ):
            raise CapacityError("tab_id is exclusive while an attempt is in flight or cancellation is pending")
        task = next((item for item in self._tasks.values() if item.status is TaskStatus.QUEUED), None)
        if task is None:
            return None
        attempt_id = f"attempt-{uuid4()}"
        _require_distinct(
            session_id=self.session_id,
            task_id=task.task_id,
            attempt_id=attempt_id,
            tab_id=tab_id,
        )
        attempt = _Attempt(
            attempt_id=attempt_id,
            task_id=task.task_id,
            tab_id=tab_id,
            notion_thread_id=None,
            model=task.model,
            effort=task.effort,
            prompt_hash=task.prompt_hash,
            ordinal=len(task.attempt_ids) + 1,
        )
        self._attempts[attempt_id] = attempt
        task.attempt_ids.append(attempt_id)
        task.status = TaskStatus.PREPARED
        self._pending_ui_attempt_id = attempt_id
        return UiAction(
            session_id=self.session_id,
            task_id=task.task_id,
            attempt_id=attempt_id,
            tab_id=tab_id,
            model=task.model,
            effort=task.effort,
            prompt=task.prompt,
            prompt_hash=task.prompt_hash,
        )

    def observe_send(
        self,
        attempt_id: str,
        observation: SendObservation,
        readback: UiReadback,
    ) -> AttemptSnapshot:
        """Accept a known or uncertain send outcome from the external boundary."""
        attempt = self._attempt(attempt_id)
        if not isinstance(observation, SendObservation):
            raise TypeError("observation must be a SendObservation")
        if self._pending_ui_attempt_id != attempt_id or attempt.status is not AttemptStatus.PREPARED:
            raise CorrelationError("send observation does not match the prepared UI action")
        task = self._tasks[attempt.task_id]
        self._validate_readback(attempt, readback)
        if observation is SendObservation.SENT:
            self._bind_thread(attempt, readback.notion_thread_id)
        elif observation is SendObservation.NOT_SENT and readback.notion_thread_id is not None:
            raise CorrelationError("a not-sent observation cannot bind a Notion thread")
        elif observation is SendObservation.UNCERTAIN and readback.notion_thread_id is not None:
            self._bind_thread(attempt, readback.notion_thread_id)
        self._pending_ui_attempt_id = None
        if observation is SendObservation.SENT:
            attempt.status = AttemptStatus.SENT
            task.status = TaskStatus.WAITING_RESULT
        elif observation is SendObservation.UNCERTAIN:
            attempt.status = AttemptStatus.UNCERTAIN_SEND
            task.status = TaskStatus.UNCERTAIN_SEND
        elif observation is SendObservation.NOT_SENT:
            attempt.status = AttemptStatus.SEND_FAILED
            self._retry_or_fail(task)
        return attempt.snapshot()

    def resolve_uncertain_as_not_sent(self, attempt_id: str) -> AttemptSnapshot:
        """Retry only after a human/external adapter establishes that it was not sent."""
        attempt = self._attempt(attempt_id)
        if attempt.status is not AttemptStatus.UNCERTAIN_SEND:
            raise CorrelationError("only an uncertain send can be manually resolved as not sent")
        attempt.status = AttemptStatus.SEND_FAILED
        self._retry_or_fail(self._tasks[attempt.task_id])
        return attempt.snapshot()

    def observe_failure(self, attempt_id: str) -> AttemptSnapshot:
        """Record a known post-send failure and apply the bounded retry policy."""
        attempt = self._attempt(attempt_id)
        if attempt.status is not AttemptStatus.SENT:
            raise CorrelationError("only a confirmed sent attempt can be marked failed")
        attempt.status = AttemptStatus.FAILED
        self._retry_or_fail(self._tasks[attempt.task_id])
        return attempt.snapshot()

    def record_result(self, observation: ResultObservation) -> ResultRecord:
        """Accept one fully correlated immutable result; generated text is never run."""
        attempt = self._attempt(observation.attempt_id)
        task = self._tasks[attempt.task_id]
        if attempt.status is AttemptStatus.COMPLETED:
            raise DuplicateResultError(f"attempt already has a result: {attempt.attempt_id}")
        if attempt.status not in {AttemptStatus.SENT, AttemptStatus.UNCERTAIN_SEND}:
            raise CorrelationError("result is not eligible before a sent or uncertain observation")
        if attempt.notion_thread_id is None:
            raise CorrelationError("result requires an observed Notion thread id")
        if not isinstance(observation.effort, ReasoningEffort):
            raise TypeError("result effort must be a ReasoningEffort")
        if not isinstance(observation.source, ObservationSource):
            raise TypeError("result source must be an ObservationSource")
        if not observation.result_text.strip():
            raise ValueError("result_text must not be empty")
        expected = (
            self.session_id,
            attempt.task_id,
            attempt.attempt_id,
            attempt.tab_id,
            attempt.notion_thread_id,
            attempt.model,
            attempt.effort,
            attempt.prompt_hash,
        )
        received = (
            observation.session_id,
            observation.task_id,
            observation.attempt_id,
            observation.tab_id,
            observation.notion_thread_id,
            observation.model,
            observation.effort,
            observation.prompt_hash,
        )
        if received != expected:
            if observation.prompt_hash != attempt.prompt_hash:
                raise PromptMismatchError("result prompt hash does not match its attempt")
            raise CorrelationError("result provenance does not match its attempt or session")
        record = ResultRecord(
            session_id=observation.session_id,
            task_id=observation.task_id,
            attempt_id=observation.attempt_id,
            tab_id=observation.tab_id,
            notion_thread_id=observation.notion_thread_id,
            model=observation.model,
            effort=observation.effort,
            prompt_hash=observation.prompt_hash,
            result_text=observation.result_text,
            source=observation.source,
            observed_at=datetime.now(UTC),
        )
        task.results.append(record)
        attempt.status = AttemptStatus.COMPLETED
        task.status = TaskStatus.COMPLETED
        return record

    def pause(self) -> None:
        """Stop future scheduling while preserving current evidence and reservations."""
        if self.status is SessionStatus.RUNNING:
            self.status = SessionStatus.PAUSED

    def resume(self) -> None:
        """Resume only an ordinary pause; user takeover is intentionally terminal."""
        if self.status is not SessionStatus.PAUSED:
            raise SchedulerStoppedError("only a paused session can resume")
        self.status = SessionStatus.RUNNING

    def cancel_task(self, task_id: str) -> TaskSnapshot:
        """Cancel one task and release a still-prepared UI reservation, if any."""
        task = self._task(task_id)
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise CorrelationError("cannot cancel a terminal task")
        if task.status is TaskStatus.CANCELLATION_PENDING:
            return task.snapshot()
        if task.attempt_ids:
            latest = self._attempts[task.attempt_ids[-1]]
            if latest.status is AttemptStatus.PREPARED:
                latest.status = AttemptStatus.CANCELLED
                if self._pending_ui_attempt_id == latest.attempt_id:
                    self._pending_ui_attempt_id = None
                task.status = TaskStatus.CANCELLED
            elif latest.status in {AttemptStatus.SENT, AttemptStatus.UNCERTAIN_SEND}:
                latest.status = AttemptStatus.CANCELLATION_PENDING
                task.status = TaskStatus.CANCELLATION_PENDING
            else:
                task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.CANCELLED
        return task.snapshot()

    def observe_cancellation(self, attempt_id: str) -> AttemptSnapshot:
        """Release a sent tab only after an external cancellation confirmation."""
        attempt = self._attempt(attempt_id)
        if attempt.status is not AttemptStatus.CANCELLATION_PENDING:
            raise CorrelationError("cancellation was not pending for this attempt")
        attempt.status = AttemptStatus.CANCELLED
        self._tasks[attempt.task_id].status = TaskStatus.CANCELLED
        return attempt.snapshot()

    def cancel(self) -> None:
        """Terminally stop the whole scheduler without deleting immutable evidence."""
        self.status = SessionStatus.CANCELLED
        for attempt in self._attempts.values():
            if attempt.status is AttemptStatus.PREPARED:
                attempt.status = AttemptStatus.CANCELLED
            elif attempt.status in {AttemptStatus.SENT, AttemptStatus.UNCERTAIN_SEND}:
                attempt.status = AttemptStatus.CANCELLATION_PENDING
        for task in self._tasks.values():
            if any(
                self._attempts[attempt_id].status is AttemptStatus.CANCELLATION_PENDING
                for attempt_id in task.attempt_ids
            ):
                task.status = TaskStatus.CANCELLATION_PENDING
            elif task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                task.status = TaskStatus.CANCELLED
        self._pending_ui_attempt_id = None

    def user_takeover(self) -> None:
        """Give control to the user and stop all future scheduler actions."""
        if self.status is SessionStatus.CANCELLED:
            raise SchedulerStoppedError("a cancelled session cannot be taken over")
        self.status = SessionStatus.USER_TAKEOVER
        if self._pending_ui_attempt_id is not None:
            attempt = self._attempts[self._pending_ui_attempt_id]
            attempt.status = AttemptStatus.USER_TAKEOVER
            self._tasks[attempt.task_id].status = TaskStatus.PAUSED
            self._pending_ui_attempt_id = None
        for task in self._tasks.values():
            if task.status is TaskStatus.QUEUED:
                task.status = TaskStatus.PAUSED

    def to_state(self) -> dict[str, object]:
        """Return a versioned, JSON-compatible snapshot without performing I/O."""
        if len(self._tasks) > MAX_STATE_TASKS or len(self._attempts) > MAX_STATE_ATTEMPTS:
            raise ValueError("state exceeds task or attempt limits")
        state: dict[str, object] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "session_id": self.session_id,
            "max_in_flight": self.max_in_flight,
            "benchmark_prompt_hash": self.benchmark_prompt_hash,
            "status": self.status.value,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "prompt": task.prompt,
                    "prompt_hash": task.prompt_hash,
                    "model": task.model,
                    "effort": task.effort.value,
                    "max_retries": task.max_retries,
                    "status": task.status.value,
                    "attempt_ids": list(task.attempt_ids),
                    "results": [
                        {
                            "session_id": result.session_id,
                            "task_id": result.task_id,
                            "attempt_id": result.attempt_id,
                            "tab_id": result.tab_id,
                            "notion_thread_id": result.notion_thread_id,
                            "model": result.model,
                            "effort": result.effort.value,
                            "prompt_hash": result.prompt_hash,
                            "result_text": result.result_text,
                            "source": result.source.value,
                            "observed_at": result.observed_at.isoformat(),
                        }
                        for result in task.results
                    ],
                }
                for task in self._tasks.values()
            ],
            "attempts": [
                {
                    "attempt_id": attempt.attempt_id,
                    "task_id": attempt.task_id,
                    "tab_id": attempt.tab_id,
                    "notion_thread_id": attempt.notion_thread_id,
                    "model": attempt.model,
                    "effort": attempt.effort.value,
                    "prompt_hash": attempt.prompt_hash,
                    "ordinal": attempt.ordinal,
                    "status": attempt.status.value,
                }
                for attempt in self._attempts.values()
            ],
            "thread_owners": dict(self._thread_owners),
            "pending_ui_attempt_id": self._pending_ui_attempt_id,
        }
        _require_state_size(state)
        return state

    @classmethod
    def from_state(cls, state: dict[str, object], *, recovering: bool = True) -> SessionPool:
        """Validate and reconstruct persisted state without evaluating its contents.

        ``recovering=True`` is the crash-safe default: a formerly running pool
        is paused and a prepared UI action becomes an uncertain send.  Passing
        ``recovering=False`` is only appropriate while the caller owns the
        persistent-store transaction lock.  That lock serializes state changes;
        it is not a live UI lock, and persisted prepared reservations still
        enforce serial dispatch.  It never bypasses validation.
        """
        parsed = _parse_state(state)
        pool = cls(
            max_in_flight=parsed.max_in_flight,
            session_id=parsed.session_id,
        )
        pool.benchmark_prompt_hash = parsed.benchmark_prompt_hash
        pool.status = parsed.status
        pool._tasks = parsed.tasks
        pool._attempts = parsed.attempts
        pool._thread_owners = parsed.thread_owners
        pool._pending_ui_attempt_id = parsed.pending_ui_attempt_id
        if recovering:
            pool._apply_recovery_safety()
        return pool

    def reconcile_uncertain_send(self, attempt_id: str, readback: UiReadback) -> AttemptSnapshot:
        """Confirm an uncertain send from a matching observed UI readback.

        A thread id is never generated or accepted without the same provenance
        checks as an ordinary send.  A missing thread cannot establish whether
        the UI sent the prompt, so it leaves the pool unchanged.  This does not
        resume a recovered pool.
        """
        attempt = self._attempt(attempt_id)
        if attempt.status is not AttemptStatus.UNCERTAIN_SEND:
            raise CorrelationError("only an uncertain send can be reconciled")
        self._validate_readback(attempt, readback)
        if readback.notion_thread_id is None:
            raise CorrelationError("uncertain reconciliation requires an observed Notion thread id")
        self._bind_thread(attempt, readback.notion_thread_id)
        attempt.status = AttemptStatus.SENT
        self._tasks[attempt.task_id].status = TaskStatus.WAITING_RESULT
        return attempt.snapshot()

    @property
    def in_flight_count(self) -> int:
        return sum(
            attempt.status
            in {
                AttemptStatus.PREPARED,
                AttemptStatus.SENT,
                AttemptStatus.UNCERTAIN_SEND,
                AttemptStatus.CANCELLATION_PENDING,
            }
            for attempt in self._attempts.values()
        )

    @property
    def pending_ui_action(self) -> AttemptSnapshot | None:
        if self._pending_ui_attempt_id is None:
            return None
        return self._attempts[self._pending_ui_attempt_id].snapshot()

    @property
    def task_ids(self) -> tuple[str, ...]:
        """Return task identifiers in their submission order without exposing internals."""
        return tuple(self._tasks)

    def task(self, task_id: str) -> TaskSnapshot:
        return self._task(task_id).snapshot()

    def attempt(self, attempt_id: str) -> AttemptSnapshot:
        return self._attempt(attempt_id).snapshot()

    def _retry_or_fail(self, task: _Task) -> None:
        if len(task.attempt_ids) <= task.max_retries:
            task.status = TaskStatus.QUEUED
        else:
            task.status = TaskStatus.FAILED

    def _apply_recovery_safety(self) -> None:
        """Make interrupted UI work non-runnable until an explicit observation."""
        if self.status is SessionStatus.RUNNING:
            self.status = SessionStatus.PAUSED
        for attempt in self._attempts.values():
            if attempt.status is AttemptStatus.PREPARED:
                attempt.status = AttemptStatus.UNCERTAIN_SEND
                self._tasks[attempt.task_id].status = TaskStatus.UNCERTAIN_SEND
        self._pending_ui_attempt_id = None

    def _require_running(self) -> None:
        if self.status is not SessionStatus.RUNNING:
            raise SchedulerStoppedError(f"scheduler is {self.status.value}")

    def _require_not_cancelled(self) -> None:
        if self.status is SessionStatus.CANCELLED:
            raise SchedulerStoppedError("scheduler is cancelled")

    def _task(self, task_id: str) -> _Task:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise CorrelationError(f"unknown task_id: {task_id}") from exc

    def _attempt(self, attempt_id: str) -> _Attempt:
        try:
            return self._attempts[attempt_id]
        except KeyError as exc:
            raise CorrelationError(f"unknown attempt_id: {attempt_id}") from exc

    def _validate_readback(self, attempt: _Attempt, readback: UiReadback) -> None:
        if not isinstance(readback, UiReadback):
            raise TypeError("readback must be a UiReadback")
        if not isinstance(readback.effort, ReasoningEffort):
            raise TypeError("UI readback effort must be a ReasoningEffort")
        if not isinstance(readback.source, ObservationSource):
            raise TypeError("UI readback source must be an ObservationSource")
        if readback.prompt_hash != attempt.prompt_hash:
            raise PromptMismatchError("UI readback prompt hash does not match its attempt")
        if readback.model != attempt.model or readback.effort is not attempt.effort:
            raise CorrelationError("UI readback model or effort does not match its attempt")

    def _bind_thread(self, attempt: _Attempt, notion_thread_id: str | None) -> None:
        if notion_thread_id is None:
            raise CorrelationError("a sent observation requires an observed Notion thread id")
        _require_identifier("notion_thread_id", notion_thread_id)
        _require_distinct(
            session_id=self.session_id,
            task_id=attempt.task_id,
            attempt_id=attempt.attempt_id,
            tab_id=attempt.tab_id,
            notion_thread_id=notion_thread_id,
        )
        if attempt.notion_thread_id is not None and attempt.notion_thread_id != notion_thread_id:
            raise CorrelationError("an attempt cannot be rebound to a different Notion thread")
        owner = self._thread_owners.get(notion_thread_id)
        if owner is not None and owner != attempt.task_id:
            raise CorrelationError("an observed Notion thread cannot be reused by an unrelated task")
        attempt.notion_thread_id = notion_thread_id
        self._thread_owners[notion_thread_id] = attempt.task_id


def _prompt_hash(prompt: str | None) -> str:
    return sha256((prompt or "").encode("utf-8")).hexdigest()


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_distinct(**identifiers: str) -> None:
    if len(set(identifiers.values())) != len(identifiers):
        raise ValueError("session_id, task_id, attempt_id, tab_id, and notion_thread_id must be distinct")


@dataclass(slots=True)
class _ParsedState:
    session_id: str
    max_in_flight: int
    benchmark_prompt_hash: str | None
    status: SessionStatus
    tasks: dict[str, _Task]
    attempts: dict[str, _Attempt]
    thread_owners: dict[str, str]
    pending_ui_attempt_id: str | None


def _parse_state(state: dict[str, object]) -> _ParsedState:
    raw = _state_dict(state, "state")
    _require_keys(
        raw,
        {
            "schema_version",
            "session_id",
            "max_in_flight",
            "benchmark_prompt_hash",
            "status",
            "tasks",
            "attempts",
            "thread_owners",
            "pending_ui_attempt_id",
        },
        "state",
    )
    if _state_int(raw["schema_version"], "schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported state schema_version: {raw['schema_version']!r}")
    session_id = _state_identifier(raw["session_id"], "session_id")
    max_in_flight = _state_int(raw["max_in_flight"], "max_in_flight")
    if max_in_flight not in range(MIN_IN_FLIGHT_SLOTS, MAX_IN_FLIGHT_SLOTS + 1):
        raise ValueError("max_in_flight must be 2 or 3")
    benchmark_prompt_hash = _state_optional_hash(raw["benchmark_prompt_hash"], "benchmark_prompt_hash")
    status = _state_enum(SessionStatus, raw["status"], "status")
    raw_tasks = _state_list(raw["tasks"], "tasks")
    raw_attempts = _state_list(raw["attempts"], "attempts")
    if len(raw_tasks) > MAX_STATE_TASKS or len(raw_attempts) > MAX_STATE_ATTEMPTS:
        raise ValueError("state exceeds task or attempt limits")
    _require_state_size(raw)
    tasks = _parse_tasks(raw_tasks, session_id, benchmark_prompt_hash)
    attempts = _parse_attempts(raw_attempts, tasks, session_id)
    thread_owners = _parse_thread_owners(raw["thread_owners"], tasks)
    pending_ui_attempt_id = _state_optional_identifier(raw["pending_ui_attempt_id"], "pending_ui_attempt_id")
    _validate_state_graph(
        session_id=session_id,
        max_in_flight=max_in_flight,
        status=status,
        tasks=tasks,
        attempts=attempts,
        thread_owners=thread_owners,
        pending_ui_attempt_id=pending_ui_attempt_id,
    )
    return _ParsedState(
        session_id=session_id,
        max_in_flight=max_in_flight,
        benchmark_prompt_hash=benchmark_prompt_hash,
        status=status,
        tasks=tasks,
        attempts=attempts,
        thread_owners=thread_owners,
        pending_ui_attempt_id=pending_ui_attempt_id,
    )


def _parse_tasks(
    raw_tasks: list[object], session_id: str, benchmark_prompt_hash: str | None
) -> dict[str, _Task]:
    tasks: dict[str, _Task] = {}
    for index, raw_task in enumerate(raw_tasks):
        task = _state_dict(raw_task, f"tasks[{index}]")
        _require_keys(
            task,
            {"task_id", "prompt", "prompt_hash", "model", "effort", "max_retries", "status", "attempt_ids", "results"},
            f"tasks[{index}]",
        )
        task_id = _state_identifier(task["task_id"], f"tasks[{index}].task_id")
        if task_id == session_id or task_id in tasks:
            raise ValueError(f"invalid or duplicate task_id: {task_id}")
        prompt = _state_nonempty_string(task["prompt"], f"tasks[{index}].prompt")
        prompt_hash = _state_hash(task["prompt_hash"], f"tasks[{index}].prompt_hash")
        if prompt_hash != _prompt_hash(prompt):
            raise PromptMismatchError("task prompt hash does not match its prompt")
        if benchmark_prompt_hash is not None and prompt_hash != benchmark_prompt_hash:
            raise PromptMismatchError("task prompt does not match the benchmark prompt")
        model = _state_identifier(task["model"], f"tasks[{index}].model")
        max_retries = _state_int(task["max_retries"], f"tasks[{index}].max_retries")
        if max_retries not in range(MAX_RETRIES + 1):
            raise ValueError(f"tasks[{index}].max_retries must be between 0 and {MAX_RETRIES}")
        attempt_ids = _state_identifier_list(task["attempt_ids"], f"tasks[{index}].attempt_ids")
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError(f"tasks[{index}].attempt_ids must be unique")
        tasks[task_id] = _Task(
            task_id=task_id,
            prompt=prompt,
            prompt_hash=prompt_hash,
            model=model,
            effort=_state_enum(ReasoningEffort, task["effort"], f"tasks[{index}].effort"),
            max_retries=max_retries,
            status=_state_enum(TaskStatus, task["status"], f"tasks[{index}].status"),
            attempt_ids=attempt_ids,
            results=_parse_results(task["results"], f"tasks[{index}].results"),
        )
    return tasks


def _parse_attempts(raw_attempts: list[object], tasks: dict[str, _Task], session_id: str) -> dict[str, _Attempt]:
    attempts: dict[str, _Attempt] = {}
    for index, raw_attempt in enumerate(raw_attempts):
        attempt = _state_dict(raw_attempt, f"attempts[{index}]")
        _require_keys(
            attempt,
            {"attempt_id", "task_id", "tab_id", "notion_thread_id", "model", "effort", "prompt_hash", "ordinal", "status"},
            f"attempts[{index}]",
        )
        attempt_id = _state_identifier(attempt["attempt_id"], f"attempts[{index}].attempt_id")
        task_id = _state_identifier(attempt["task_id"], f"attempts[{index}].task_id")
        tab_id = _state_identifier(attempt["tab_id"], f"attempts[{index}].tab_id")
        notion_thread_id = _state_optional_identifier(attempt["notion_thread_id"], f"attempts[{index}].notion_thread_id")
        if attempt_id in attempts or task_id not in tasks:
            raise ValueError(f"unknown task or duplicate attempt at attempts[{index}]")
        _require_distinct(
            session_id=session_id,
            task_id=task_id,
            attempt_id=attempt_id,
            tab_id=tab_id,
            **({"notion_thread_id": notion_thread_id} if notion_thread_id is not None else {}),
        )
        task = tasks[task_id]
        model = _state_identifier(attempt["model"], f"attempts[{index}].model")
        prompt_hash = _state_hash(attempt["prompt_hash"], f"attempts[{index}].prompt_hash")
        effort = _state_enum(ReasoningEffort, attempt["effort"], f"attempts[{index}].effort")
        if (model, effort, prompt_hash) != (task.model, task.effort, task.prompt_hash):
            raise CorrelationError("attempt provenance does not match its task")
        attempts[attempt_id] = _Attempt(
            attempt_id=attempt_id,
            task_id=task_id,
            tab_id=tab_id,
            notion_thread_id=notion_thread_id,
            model=model,
            effort=effort,
            prompt_hash=prompt_hash,
            ordinal=_state_positive_int(attempt["ordinal"], f"attempts[{index}].ordinal"),
            status=_state_enum(AttemptStatus, attempt["status"], f"attempts[{index}].status"),
        )
    return attempts


def _parse_results(raw_results: object, path: str) -> list[ResultRecord]:
    results: list[ResultRecord] = []
    for index, raw_result in enumerate(_state_list(raw_results, path)):
        result = _state_dict(raw_result, f"{path}[{index}]")
        _require_keys(
            result,
            {
                "session_id", "task_id", "attempt_id", "tab_id", "notion_thread_id", "model", "effort",
                "prompt_hash", "result_text", "source", "observed_at",
            },
            f"{path}[{index}]",
        )
        observed_at = _state_datetime(result["observed_at"], f"{path}[{index}].observed_at")
        results.append(
            ResultRecord(
                session_id=_state_identifier(result["session_id"], f"{path}[{index}].session_id"),
                task_id=_state_identifier(result["task_id"], f"{path}[{index}].task_id"),
                attempt_id=_state_identifier(result["attempt_id"], f"{path}[{index}].attempt_id"),
                tab_id=_state_identifier(result["tab_id"], f"{path}[{index}].tab_id"),
                notion_thread_id=_state_identifier(result["notion_thread_id"], f"{path}[{index}].notion_thread_id"),
                model=_state_identifier(result["model"], f"{path}[{index}].model"),
                effort=_state_enum(ReasoningEffort, result["effort"], f"{path}[{index}].effort"),
                prompt_hash=_state_hash(result["prompt_hash"], f"{path}[{index}].prompt_hash"),
                result_text=_state_nonempty_string(result["result_text"], f"{path}[{index}].result_text"),
                source=_state_enum(ObservationSource, result["source"], f"{path}[{index}].source"),
                observed_at=observed_at,
            )
        )
    return results


def _parse_thread_owners(raw_owners: object, tasks: dict[str, _Task]) -> dict[str, str]:
    owners = _state_dict(raw_owners, "thread_owners")
    parsed: dict[str, str] = {}
    for raw_thread_id, raw_task_id in owners.items():
        thread_id = _state_identifier(raw_thread_id, "thread_owners key")
        task_id = _state_identifier(raw_task_id, f"thread_owners[{thread_id!r}]")
        if task_id not in tasks:
            raise CorrelationError("thread owner references an unknown task")
        parsed[thread_id] = task_id
    return parsed


def _validate_state_graph(
    *,
    session_id: str,
    max_in_flight: int,
    status: SessionStatus,
    tasks: dict[str, _Task],
    attempts: dict[str, _Attempt],
    thread_owners: dict[str, str],
    pending_ui_attempt_id: str | None,
) -> None:
    expected_threads: dict[str, str] = {}
    prepared_ids: list[str] = []
    active_tab_ids: set[str] = set()
    active_attempt_count = 0
    for task in tasks.values():
        task_attempts = [attempts.get(attempt_id) for attempt_id in task.attempt_ids]
        if any(attempt is None for attempt in task_attempts):
            raise CorrelationError("task references an unknown attempt")
        if any(attempt.task_id != task.task_id for attempt in task_attempts if attempt is not None):
            raise CorrelationError("task references an attempt owned by another task")
        if [attempt.ordinal for attempt in task_attempts if attempt is not None] != list(range(1, len(task_attempts) + 1)):
            raise CorrelationError("attempt ordinals must match task attempt order")
        _validate_task_status(task, [attempt for attempt in task_attempts if attempt is not None])
        for result in task.results:
            attempt = attempts.get(result.attempt_id)
            if attempt is None or attempt.task_id != task.task_id or attempt.status is not AttemptStatus.COMPLETED:
                raise CorrelationError("result does not reference a completed task attempt")
            expected = (
                result.session_id,
                result.task_id,
                result.attempt_id,
                result.tab_id,
                result.notion_thread_id,
                result.model,
                result.effort,
                result.prompt_hash,
            )
            actual = (
                session_id,
                attempt.task_id,
                attempt.attempt_id,
                attempt.tab_id,
                attempt.notion_thread_id,
                attempt.model,
                attempt.effort,
                attempt.prompt_hash,
            )
            if expected != actual or not result.result_text.strip():
                raise CorrelationError("result provenance does not match its attempt")
        completed_ids = {attempt.attempt_id for attempt in task_attempts if attempt is not None and attempt.status is AttemptStatus.COMPLETED}
        if completed_ids != {result.attempt_id for result in task.results} or len(task.results) != len(completed_ids):
            raise CorrelationError("completed attempts must have exactly one result")
        for attempt in task_attempts:
            if attempt is None:
                continue
            if attempt.status is AttemptStatus.PREPARED:
                prepared_ids.append(attempt.attempt_id)
                if attempt.notion_thread_id is not None:
                    raise CorrelationError("a prepared attempt cannot have a Notion thread")
            if attempt.status in {
                AttemptStatus.PREPARED,
                AttemptStatus.SENT,
                AttemptStatus.UNCERTAIN_SEND,
                AttemptStatus.CANCELLATION_PENDING,
            }:
                active_attempt_count += 1
                if attempt.tab_id in active_tab_ids:
                    raise CorrelationError("active attempts cannot share a tab")
                active_tab_ids.add(attempt.tab_id)
            if attempt.notion_thread_id is not None:
                owner = expected_threads.setdefault(attempt.notion_thread_id, task.task_id)
                if owner != task.task_id:
                    raise CorrelationError("a Notion thread cannot belong to unrelated tasks")
    if set(attempts) != {attempt_id for task in tasks.values() for attempt_id in task.attempt_ids}:
        raise CorrelationError("attempts must be referenced by exactly one task")
    if thread_owners != expected_threads:
        raise CorrelationError("thread ownership does not match bound attempts")
    if len(prepared_ids) > 1 or (pending_ui_attempt_id is None) != (not prepared_ids):
        raise CorrelationError("prepared UI action reservation is inconsistent")
    if active_attempt_count > max_in_flight:
        raise CapacityError("persisted state exceeds in-flight capacity")
    if pending_ui_attempt_id is not None and pending_ui_attempt_id != prepared_ids[0]:
        raise CorrelationError("pending UI action does not match the prepared attempt")
    if status is SessionStatus.CANCELLED and any(
        task.status in {TaskStatus.QUEUED, TaskStatus.PREPARED, TaskStatus.WAITING_RESULT, TaskStatus.UNCERTAIN_SEND}
        for task in tasks.values()
    ):
        raise CorrelationError("cancelled session has active task state")
    if status is SessionStatus.USER_TAKEOVER and (prepared_ids or any(task.status is TaskStatus.QUEUED for task in tasks.values())):
        raise CorrelationError("user takeover session has schedulable task state")


def _validate_task_status(task: _Task, attempts: list[_Attempt]) -> None:
    latest = attempts[-1] if attempts else None
    if task.status is TaskStatus.QUEUED:
        if latest is not None and (latest.status not in {AttemptStatus.SEND_FAILED, AttemptStatus.FAILED} or len(attempts) > task.max_retries):
            raise CorrelationError("queued task has an invalid retry state")
    elif task.status is TaskStatus.PREPARED:
        _require_latest_status(task, latest, AttemptStatus.PREPARED)
    elif task.status is TaskStatus.WAITING_RESULT:
        _require_latest_status(task, latest, AttemptStatus.SENT)
    elif task.status is TaskStatus.UNCERTAIN_SEND:
        _require_latest_status(task, latest, AttemptStatus.UNCERTAIN_SEND)
    elif task.status is TaskStatus.COMPLETED:
        _require_latest_status(task, latest, AttemptStatus.COMPLETED)
    elif task.status is TaskStatus.FAILED:
        if latest is None or latest.status not in {AttemptStatus.SEND_FAILED, AttemptStatus.FAILED} or len(attempts) <= task.max_retries:
            raise CorrelationError("failed task has an invalid retry state")
    elif task.status is TaskStatus.CANCELLATION_PENDING:
        _require_latest_status(task, latest, AttemptStatus.CANCELLATION_PENDING)
    elif task.status is TaskStatus.PAUSED:
        if latest is not None and latest.status is not AttemptStatus.USER_TAKEOVER:
            raise CorrelationError("paused task has an invalid attempt state")
    elif task.status is TaskStatus.CANCELLED and latest is not None and latest.status is AttemptStatus.PREPARED:
        raise CorrelationError("cancelled task retains a prepared attempt")


def _require_latest_status(task: _Task, latest: _Attempt | None, expected: AttemptStatus) -> None:
    if latest is None or latest.status is not expected:
        raise CorrelationError(f"{task.status.value} task has an invalid latest attempt")


def _state_dict(value: object, path: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise TypeError(f"{path} must be a string-keyed object")
    return value


def _state_list(value: object, path: str) -> list[object]:
    if type(value) is not list:
        raise TypeError(f"{path} must be a list")
    return value


def _require_keys(value: dict[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{path} has an unsupported shape")


def _state_string(value: object, path: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{path} must be a string")
    return value


def _state_nonempty_string(value: object, path: str) -> str:
    value = _state_string(value, path)
    if not value:
        raise ValueError(f"{path} must not be empty")
    return value


def _state_identifier(value: object, path: str) -> str:
    value = _state_nonempty_string(value, path)
    _require_identifier(path, value)
    return value


def _state_optional_identifier(value: object, path: str) -> str | None:
    return None if value is None else _state_identifier(value, path)


def _state_identifier_list(value: object, path: str) -> list[str]:
    return [_state_identifier(item, f"{path}[{index}]") for index, item in enumerate(_state_list(value, path))]


def _state_int(value: object, path: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{path} must be an integer")
    return value


def _state_positive_int(value: object, path: str) -> int:
    value = _state_int(value, path)
    if value < 1:
        raise ValueError(f"{path} must be positive")
    return value


def _state_hash(value: object, path: str) -> str:
    value = _state_string(value, path)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{path} must be a sha256 hex digest")
    return value


def _state_optional_hash(value: object, path: str) -> str | None:
    return None if value is None else _state_hash(value, path)


def _state_enum(enum_type: type[_StateEnum], value: object, path: str) -> _StateEnum:
    value = _state_string(value, path)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{path} has an unsupported value") from exc


def _state_datetime(value: object, path: str) -> datetime:
    value = _state_string(value, path)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{path} must be a UTC datetime")
    return parsed


def _require_state_size(state: dict[str, object]) -> None:
    try:
        serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("state must contain only JSON-compatible values") from exc
    if len(serialized.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("state exceeds the 4 MiB serialized size limit")
