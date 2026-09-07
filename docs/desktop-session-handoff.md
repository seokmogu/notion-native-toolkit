# Durable desktop session handoff

`notion-desktop-session` connects the existing SessionPool to an external, authorized Computer Use host using JSON. It persists each transition before returning it. It does **not** invoke a model, drive a desktop app, start a background worker, publish data, or execute generated code.

The current desktop adapter still needs live integration for stable tab/thread identification, model-picker interaction, and lossless output capture. This CLI makes the local handoff and recovery usable across separate process/tool calls; it does not remove those remaining UI gates.

## Storage and ownership

- Choose an explicit absolute project-owned directory named `.notion-session-<name>`. There is no home/tool-runtime default.
- The parent must already exist. `init` creates only the final directory, mode `0700`, and refuses an existing directory.
- Checkpoints and lock files use mode `0600`. A descriptor-relative no-follow reader rejects symlinks, hardlinks, unsafe ownership and permissions.
- A nonblocking process lock serializes mutations. Checkpoints are immutable, numbered JSON files promoted atomically without overwriting old revisions. Corrupt latest state is an error, not permission to fall back and replay an earlier action.
- The schema is versioned and validated, including prompt hashes, attempt order, result correlation, thread ownership, cancellation states, and capacity. Limits are 512 tasks, 2,048 attempts, 4 MiB per checkpoint, and 10,000 checkpoints.
- Prompts and results are deliberately retained exactly. These are private local artifacts, not logs or publishable data. `.notion-session-*/` is Git-ignored and the local context broker excludes hidden paths. Do not place credentials in task prompts or copy a store into a public/shared location.
- This is accidental-concurrency/crash protection, not protection from a malicious same-user process rewriting private files. A crash during promotion can leave a checkpoint requiring manual repair; never delete a checkpoint or rewind revisions to force progress.

## Commands

Run `uv run notion-desktop-session --help`. Each command accepts one JSON object on stdin and emits one JSON object on stdout. Do not put prompt/result bodies in shell arguments or command logs. Feed EOF or redirect `/dev/null` for commands with `{}` input.

```sh
uv run notion-desktop-session init \
  --state-dir /Users/seokmogu/project/notion-native-toolkit/.notion-session-benchmark-01 \
  </dev/null
```

This creates a local session only. All mutations after `init` require `--revision N`, using the last observed revision. Read-only `status` and `result` do not advance it. Never assume a failed command did not commit: read status and reconcile before retrying.

| Command | JSON input | Behavior |
|---|---|---|
| `init` | `{}` or `max_in_flight`, `benchmark_prompt` | Create an empty private session; default two slots |
| `status` | `{}` | Metadata only; omits prompt/result bodies |
| `submit` | `task_id`, `prompt`, `effort`, inventory fields, plus `model` or `preferences`; optional `max_retries` | Validate model selection and queue a task |
| `prepare` | `tab_id`, inventory fields | Reserve and commit exactly one UI action before returning its prompt |
| `observe-send` | `attempt_id`, `observation`, `readback` | Confirm sent/not_sent/uncertain from actual observation |
| `record-result` | `observation`, `complete: true`, `stable: true` | Accept a fully correlated result; partial/unstable input is rejected |
| `result` | `task_id` | Return stored text as `untrusted-notion-result`, ISO timestamp, `execution_performed: false` |
| `recover` | `{}` | Pause a formerly running session and convert prepared attempts to uncertain, retaining tab slots |
| `reconcile-sent` | `attempt_id`, `readback` | Bind an uncertain attempt to its actually observed thread; does not resume the pool |
| `resolve-not-sent` | `attempt_id` | Permit a bounded retry only after an operator confirms no send occurred |
| `pause`, `resume`, `takeover`, `cancel` | `{}` | Local state transitions; they do not prove the UI stopped |
| `cancel-task` | `task_id` | Sent/uncertain work retains its tab pending cancellation confirmation |
| `observe-cancellation`, `observe-failure` | `attempt_id` | Record an actual external observation |

Inventory fields are `inventory` (the structured `get_available_models()` response) and `inventory_observed_at` (timezone-aware ISO observation time). `submit` and `prepare` require it to be no more than five minutes old, with explicit enabled status and effort support. A caller-supplied timestamp is a provenance declaration, not cryptographic proof of a fresh network request; the trusted host must actually perform the read. `preferences` reuses the tested metadata selector (`intelligence`, `speed`, `cost`) and does not infer task-domain strengths.

A send `readback` has `model`, `effort`, `prompt_hash`, `notion_thread_id` and `source` (`manual` or `external_ui_adapter`). `model` is the internal code; the actual UI display-name-to-code mapping must be verified against that same inventory. A confirmed send needs a real observed thread ID, never the generated task/session/attempt identifier.

A result `observation` contains `session_id`, `task_id`, `attempt_id`, `tab_id`, `notion_thread_id`, `model`, `effort`, `prompt_hash`, `result_text`, and `source`. All identities must match. The trusted host owns evidence for `complete` and `stable`; these booleans do not independently prove that a UI result was fully captured.

## Crash and operator-control contract

1. Commit `prepare` before any UI action. Consume the returned action once.
2. The host must retain exclusive control of desktop interactions. The local store lock protects state transactions, not the desktop itself.
3. If output or process state is lost, do not repeat the prior action. A persisted prepared reservation blocks cancellation/takeover and other mutations until `observe-send` or `recover`; ordinary second `prepare` is capacity-rejected.
4. Before recovery, establish from actual host/process/UI state that the old UI actor is stopped or control has been reclaimed. A timeout, missing commentary, or stale file is not enough.
5. `recover` preserves sent/uncertain/cancellation locks. Reconcile from actual UI state; do not turn uncertainty into a guessed `not_sent` just to free capacity.
6. Confirm UI cancellation before `observe-cancellation`. Explicitly resume an ordinary pause only when continued desktop control is safe. User takeover is terminal.

Two in-flight tasks, revision conflicts, process boundaries, lost prepared output, cancellation-after-crash, post-crash sent reconciliation, corrupt checkpoints, no-follow storage, and JSON result retrieval are tested with synthetic fixtures. These tests do not claim real Notion parallel inference or Cloudflare E2E.
