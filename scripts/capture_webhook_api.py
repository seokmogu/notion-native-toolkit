"""Capture Notion internal API calls for Database Automation "Send webhook" action.

This targets the DB-level automation (lightning bolt icon on a database), NOT
the integration webhook. Automations fire when a row matches a trigger
(e.g. status property set to a value) and can POST to an arbitrary URL.

Usage:
    cd notion-native-toolkit
    source ~/project/.env.shared  # load SLACK_WEBHOOK_URL
    uv run python scripts/capture_webhook_api.py

Manual steps in the browser that opens:
    1. Log in to Notion (if not already).
    2. Navigate to a test database (full-page DB view).
    3. Click the lightning-bolt icon (top-right) -> Automations.
    4. + New automation:
        - Trigger: e.g. "When property edited" -> pick a Status property
        - Action: + Add action -> Send webhook
        - URL: paste the Slack webhook URL printed in terminal
        - (optional) customize payload body
       Save.
    5. If possible, also: edit the automation, duplicate it, delete it.
    6. Trigger the automation once (change a row's status) to capture the
       outbound firing call too.
    7. Return to terminal and press Enter to save the capture.

Output:
    docs/webhook-api-capture.json  — full request/response dump
    ~/.config/notion-native-toolkit/browser-state/worxphere.json — session
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Request, Response

STATE_PATH = Path("~/.config/notion-native-toolkit/browser-state/worxphere.json").expanduser()
DUMP_PATH = Path(__file__).parent.parent / "docs" / "automation-webhook-capture.json"
# Start at the workspace root; the user navigates to the target DB manually.
START_URL = "https://www.notion.so/"
API_FILTER = "/api/v3/"


async def main() -> None:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not slack_url:
        print("WARN: SLACK_WEBHOOK_URL env var not set. "
              "Run `source ~/project/.env.shared` first.", file=sys.stderr)
    else:
        print(f"Slack webhook URL to paste in Notion UI:\n  {slack_url}\n")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    captures: list[dict] = []

    def handle_request(req: Request) -> None:
        if API_FILTER not in req.url:
            return
        captures.append({
            "kind": "request",
            "ts": asyncio.get_event_loop().time(),
            "method": req.method,
            "url": req.url,
            "headers": dict(req.headers),
            "post_data": req.post_data,
        })

    async def handle_response_async(res: Response) -> None:
        if API_FILTER not in res.url:
            return
        body: object | None = None
        ctype = res.headers.get("content-type", "")
        try:
            if "application/json" in ctype:
                body = await res.json()
            else:
                text = await res.text()
                body = text[:10000]
        except Exception as exc:  # noqa: BLE001
            body = f"<decode error: {exc}>"
        captures.append({
            "kind": "response",
            "ts": asyncio.get_event_loop().time(),
            "status": res.status,
            "url": res.url,
            "headers": dict(res.headers),
            "body": body,
        })

    def handle_response(res: Response) -> None:
        asyncio.create_task(handle_response_async(res))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=50)
        ctx_kwargs: dict = {"viewport": {"width": 1440, "height": 900}}
        if STATE_PATH.exists():
            ctx_kwargs["storage_state"] = str(STATE_PATH)
            print(f"Using saved session: {STATE_PATH}")
        else:
            print("No saved session — log in manually in the browser.")

        context = await browser.new_context(**ctx_kwargs)
        context.on("request", handle_request)
        context.on("response", handle_response)

        page = await context.new_page()
        await page.goto(START_URL)

        print()
        print("=" * 70)
        print("Browser is open. Do the following manually in Notion:")
        print("  1) Log in if needed.")
        print("  2) Open a test database (full-page DB view).")
        print("  3) Top-right lightning-bolt icon -> Automations.")
        print("  4) + New automation:")
        print("       Trigger: e.g. 'When property edited' -> pick Status")
        print("       Action : + Add action -> Send webhook")
        print(f"       URL    : {slack_url or '<set SLACK_WEBHOOK_URL>'}")
        print("       Save.")
        print("  5) (optional) edit / duplicate / delete the automation.")
        print("  6) (optional) change a row status to trigger one firing.")
        print("  7) Return here and press Enter.")
        print("=" * 70)
        print()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, "Press Enter when done: ")

        try:
            await context.storage_state(path=str(STATE_PATH))
            print(f"Saved session: {STATE_PATH}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: could not save state: {exc}")

        DUMP_PATH.write_text(
            json.dumps(captures, ensure_ascii=False, indent=2, default=str)
        )
        print(f"Saved capture: {DUMP_PATH}  ({len(captures)} events)")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
