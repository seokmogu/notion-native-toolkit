# TODO — Pending toolkit features

Items flagged for future iteration but not yet implemented.

## Guest invite via internal API

**Status**: payload capture attempted but Share modal's primary button could
not be clicked reliably by current selectors in `scripts/capture_guest_invite.py`.

**Goal**: add `NotionInternalClient.invite_guests_to_space(block_id, emails,
role="reader")` so guest-automation and future callers can invite guests
with zero Playwright UI automation.

**Steps to complete next**:
1. Fix `scripts/capture_guest_invite.py`:
   - Share modal primary button is a `<div role="button">` with text
     "Share" inside the dialog. Current JS helper matches that exact text
     but click dispatch may not trigger Notion's React handler.
   - Retry with `dispatchEvent(new MouseEvent('click', {bubbles:true}))`
     on the element and add a 300-500 ms wait after clicking the option row.
2. Re-run capture to obtain `inviteGuestsToSpace` POST body.
3. Add method on `NotionInternalClient` mirroring captured payload:
   - `POST /api/v3/inviteGuestsToSpace`
   - Input: `spaceId`, `blockId`, list of `{email, role}` items.
4. Add unit test in `tests/test_internal.py` (mocked `_post`).
5. Add integration test in `tests/test_internal_integration.py` guarded
   behind `pytest -m integration`.

**Related doc**: `docs/internal-api-capture.md` row
`| Guest invite | inviteGuestsToSpace | Share modal → type email → invite |`

## Follow-ups for guest-automation (separate repo)

Once `invite_guests_to_space` lands here, swap out the Playwright
`_perform_invite` path in notion-guest-automation with a toolkit call. That
lets us delete the `auth.py` + persistent profile dependency entirely and
ship a pure-REST worker.
