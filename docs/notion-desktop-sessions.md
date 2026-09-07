# Notion desktop sessions (locally tested foundation)

`notion_native_toolkit.session_pool` is a state machine for the approved Notion desktop multi-tab workflow. It has no browser/UI library, page fetch, Notion API call (official or internal), or code-execution path. Versioned snapshots can now be persisted through the separate private store/JSON handoff CLI.

The pool returns an immutable `UiAction`; an approved external UI adapter or human operator performs it. The same boundary then calls `observe_send()` with a `SendObservation` and an immutable `UiReadback`, and later supplies `ResultObservation`. `ExternalUiAdapter` is only a protocol boundary. The separate injected JavaScript adapter below is not yet wired to this Python pool; neither component constitutes a live end-to-end runner.

## Routing, identity, and readback guardrails

`submit()` requires an explicit opaque `model` identifier and `ReasoningEffort`. The values are carried by `UiAction`, `AttemptSnapshot`, `ResultObservation`, and immutable `ResultRecord`. The pool intentionally does not claim that a chosen model or effort is available: a future approved adapter must obtain and validate that UI state.

Every task hashes the exact UTF-8 prompt. Passing `benchmark_prompt=...` makes every task match that content hash, for comparable prompt benchmarks. The post-send `UiReadback` must echo the planned model, effort, and prompt hash, so a visible UI mismatch is rejected before state advances.

The outbound action has `session_id`, `task_id`, `attempt_id`, and `tab_id`, but no invented Notion thread ID. The adapter/operator binds the actual `notion_thread_id` only through the readback after an observed send. A confirmed send needs a non-empty actual thread ID; an uncertain send may leave it absent. A result requires the bound thread plus an exact match of session, task, attempt, tab, thread, model, effort, and prompt hash.

Completed thread IDs remain owned by their task. A different task cannot bind the same observed thread later, even after the original task completes.

## Scheduling model

`max_in_flight` is intentionally restricted to 2 or 3. It represents attempts prepared, sent, uncertain, or pending cancellation; it does not claim that desktop UI actions operate in parallel. `prepare_next()` permits only one prepared action at a time. A caller must provide a send observation before another action can be prepared.

Each tab remains exclusive while its attempt is in flight. A sent or uncertain task cancellation transitions to `cancellation_pending`, retaining the tab lock until `observe_cancellation()` records external confirmation. This avoids treating a scheduler-side cancellation request as proof that the UI stopped work.

```python
from notion_native_toolkit.session_pool import (
    ObservationSource,
    ReasoningEffort,
    SendObservation,
    SessionPool,
    UiReadback,
)

pool = SessionPool(max_in_flight=2, benchmark_prompt="Summarize these notes.")
pool.submit(
    "task-001",
    "Summarize these notes.",
    model="selected-model-code",
    effort=ReasoningEffort.HIGH,
)
action = pool.prepare_next(tab_id="desktop-tab-7")
assert action is not None

# An external adapter or a human performs the UI interaction here.
pool.observe_send(
    action.attempt_id,
    SendObservation.SENT,
    UiReadback(
        model=action.model,
        effort=action.effort,
        prompt_hash=action.prompt_hash,
        notion_thread_id="observed-notion-thread-42",
        source=ObservationSource.MANUAL,
    ),
)
```

## Failure, takeover, and result rules

- `SendObservation` is an enum. Unknown values are rejected before scheduler state changes; they cannot fall through to `NOT_SENT` or trigger a retry.
- Known `NOT_SENT` and known post-send failures consume an attempt and retry only up to `max_retries` (0 through 3, default 1).
- `UNCERTAIN` retains its slot and is never retried automatically. Only `resolve_uncertain_as_not_sent()` after an explicit observation makes a bounded retry eligible.
- `pause()` blocks new actions. `cancel_task()` immediately cancels only an unsent prepared action; sent/uncertain work needs observed cancellation confirmation. `user_takeover()` stops future automation.
- Results must be non-empty, fully correlated, and are stored as immutable data. Duplicate results are rejected; result text is never evaluated or executed.

## Persistence and remaining integration work

`to_state()` and validated `from_state(..., recovering=True)` support crash-safe recovery. The default restore pauses a running session and converts a prepared attempt to uncertain, retaining its tab capacity. Existing results, ownership, cancellation and takeover state are preserved. `recovering=False` is reserved for a caller holding the persistent-store transaction lock, not arbitrary restart.

The new `notion-desktop-session` command persists private immutable checkpoints in an explicitly selected project-owned `.notion-session-<name>` directory. It provides a real JSON handoff across process/tool calls and a read-only result retrieval path. See the [handoff and recovery contract](desktop-session-handoff.md). It does not automatically connect to or control the desktop adapter.

Offline tests cover routing/readback correlation, post-send thread binding, prompt benchmarks, serialized action reservation, 2-slot capacity, uncertain sends, bounded retries, invalid observation rejection, immutable/duplicate/mismatched/empty result rejection, completed-thread isolation, pause, cancellation confirmation, and takeover. They do **not** prove actual desktop parallelism, UI cancellation, Notion thread discovery, or live result capture.

## Injected desktop adapter

`scripts/notion-desktop-adapter.mjs` accepts an existing, authorized Computer Use `App` handle; it imports no desktop-control library and calls no network API. Its `prepare`, `send`, `read`, and `createDistinctTab` methods consume fresh AX snapshots. The Node tests use a sanitized fixture based on the observed Korean Notion desktop AX shape, including `app.notion.com/ai` and the nested top tab bar.

- Exact window/content/model/effort matching gates input. Duplicate visible targets stop the action.
- Existing user drafts and active generations stop preparation/paste. Ephemeral AX-index changes alone cannot prove a new tab was created.
- The complete prompt must match the post-paste input readback before submit.
- A prepared send token is one-use. Uncertain sends are never automatically retried.
- A successful click is not sufficient send/completion evidence. Virtualized or unidentifiable results remain partial.
- Known code containers remain partial because AX-only extraction cannot prove lossless source formatting; code acceptance requires a future verified raw-text capture path.
- The adapter verifies an already selected model/effort; it does not yet drive unobserved model-picker menus, select a stable tab by persistent ID, discover the actual Notion thread ID, or implement a pool bridge.

Run fixture tests with `node --test tests/notion-desktop-adapter.test.mjs`. A passing fixture is not a live app benchmark. On 2026-09-07, live verification stopped when the current window changed to an unrelated document and screenshot capture was unavailable; no task prompt was pasted or sent. Do not restore/retry prior in-memory work after a process restart without reconciling the actual tabs and chats first.
