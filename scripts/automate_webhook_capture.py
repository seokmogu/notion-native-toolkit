"""Fully automated capture of Notion DB Automation "Send webhook" API.

Creates a temp DB under the worxphere profile's default parent, opens it in
Playwright with the main Chrome profile's cookies, drives the Automation UI
to add a Send webhook action, and dumps all /api/v3/ traffic.

Usage:
    source ~/project/.env.shared
    uv run python scripts/automate_webhook_capture.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from notion_native_toolkit.toolkit import NotionToolkit
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

PROFILE_DIR = Path.home() / ".chrome-automation-profile"
COOKIES_JSON = PROFILE_DIR / "cookies.json"
DUMP_PATH = Path(__file__).parent.parent / "docs" / "automation-webhook-capture.json"
SCREENSHOT_DIR = Path("/tmp/webhook_capture")
API_FILTER = "/api/v3/"
STATUS_OPTION_COLOR = "blue"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def create_test_db(tk: NotionToolkit) -> tuple[str, str]:
    parent_id = tk.profile.default_parent_page_id
    assert parent_id, "profile default_parent_page_id not set"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    title = f"WEBHOOK_CAPTURE_{ts}"
    log(f"creating test DB '{title}' under parent {parent_id}")
    client = tk.require_client()
    resp = client.create_database(
        {
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": {
                "Name": {"title": {}},
                "Status": {
                    "status": {}
                },
            },
        }
    )
    db_id = resp["id"]
    # Force notion.so domain — main Chrome's session cookies are bound to it.
    db_url = f"https://www.notion.so/{db_id.replace('-', '')}"
    log(f"created DB: {db_id}")
    log(f"url: {db_url}")
    return db_id, db_url


def try_click(page: Page, *selectors: str, timeout: int = 6000) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return sel
        except PWTimeout:
            continue
        except Exception:
            continue
    return None


def try_fill(page: Page, value: str, *selectors: str, timeout: int = 6000) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.fill(value)
            return sel
        except PWTimeout:
            continue
        except Exception:
            continue
    return None


def snap(page: Page, name: str) -> None:
    path = SCREENSHOT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        log(f"snap: {path}")
    except Exception as exc:  # noqa: BLE001
        log(f"snap failed {name}: {exc}")


def drive_ui(page: Page, slack_url: str) -> dict:
    """Attempt to create a Send webhook automation. Returns status dict."""
    status: dict = {"steps": []}

    def step(name: str, ok: bool, detail: str = "") -> None:
        status["steps"].append({"name": name, "ok": ok, "detail": detail})
        log(f"  step {name}: {'OK' if ok else 'FAIL'} {detail}")

    # 1) Open Automation panel — bolt icon top-right
    sel = try_click(
        page,
        '[aria-label="Automations"]',
        '[aria-label*="Automation"]',
        '[aria-label="자동화"]',
        '[aria-label*="자동화"]',
        'div[role="button"]:has-text("Automations")',
    )
    step("open_automations", bool(sel), sel or "not found")
    snap(page, "01_automations_panel")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # 2) + New automation
    sel = try_click(
        page,
        'text="+ New automation"',
        'text="New automation"',
        'button:has-text("New automation")',
        'text="+ 새 자동화"',
        'text="새 자동화"',
        '[role="menuitem"]:has-text("automation")',
    )
    step("new_automation", bool(sel), sel or "not found")
    snap(page, "02_new_automation")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # 3) Add action (usually primary affordance in dialog)
    sel = try_click(
        page,
        'text="Add action"',
        'text="+ Add action"',
        'button:has-text("Add action")',
        'text="동작 추가"',
        'text="작업 추가"',
    )
    step("click_add_action", bool(sel), sel or "not found")
    snap(page, "03_add_action_menu")

    # 4) Send webhook option
    sel = try_click(
        page,
        'text="Send webhook"',
        'div[role="menuitem"]:has-text("webhook")',
        'text="웹훅 전송"',
        'text="웹훅 보내기"',
        '[role="option"]:has-text("webhook")',
    )
    step("select_send_webhook", bool(sel), sel or "not found")
    snap(page, "04_send_webhook_form")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # 5) Fill URL
    sel = try_fill(
        page,
        slack_url,
        'input[placeholder*="URL" i]',
        'input[type="url"]',
        'input[aria-label*="URL" i]',
        'input[placeholder*="webhook" i]',
        'input:near(:text("URL"))',
    )
    step("fill_url", bool(sel), sel or "not found")
    snap(page, "05_url_filled")

    # 6) Save / Create / Done
    sel = try_click(
        page,
        'button:has-text("Create")',
        'button:has-text("Done")',
        'button:has-text("Save")',
        'button:has-text("저장")',
        'button:has-text("완료")',
        'button:has-text("생성")',
    )
    step("save", bool(sel), sel or "not found")
    page.wait_for_timeout(2500)
    snap(page, "06_saved")

    return status


def main() -> int:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL") or ""
    if not slack_url:
        log("ERROR: SLACK_WEBHOOK_URL not set")
        return 1
    if not COOKIES_JSON.exists():
        log(f"ERROR: cookies file missing: {COOKIES_JSON}")
        return 1

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    tk = NotionToolkit.from_profile("worxphere")
    reuse_id = os.environ.get("REUSE_DB_ID")
    if reuse_id:
        db_id = reuse_id
        db_url = f"https://www.notion.so/{db_id.replace('-', '')}"
        log(f"reusing DB: {db_id}")
    else:
        db_id, db_url = create_test_db(tk)

    all_cookies = json.loads(COOKIES_JSON.read_text())
    # Keep only notion cookies to avoid clobbering the target context.
    cookies = [
        c for c in all_cookies
        if "notion" in c.get("domain", "").lower()
    ]
    log(f"loaded {len(cookies)} notion cookies (out of {len(all_cookies)} total)")
    # Log key auth cookie presence
    key_names = {"token_v2", "notion_user_id", "notion_browser_id"}
    present = {c["name"] for c in cookies if c.get("name") in key_names}
    log(f"auth cookies present: {sorted(present)}")

    captures: list[dict] = []

    def on_req(req) -> None:
        if API_FILTER in req.url:
            captures.append(
                {
                    "kind": "request",
                    "ts": time.time(),
                    "method": req.method,
                    "url": req.url,
                    "post_data": req.post_data,
                    "headers": dict(req.headers),
                }
            )

    def on_res(res) -> None:
        if API_FILTER in res.url:
            body: object | None = None
            try:
                ct = res.headers.get("content-type", "")
                if "application/json" in ct:
                    body = res.json()
                else:
                    body = (res.text() or "")[:5000]
            except Exception as exc:  # noqa: BLE001
                body = f"<decode error: {exc}>"
            captures.append(
                {
                    "kind": "response",
                    "ts": time.time(),
                    "status": res.status,
                    "url": res.url,
                    "body": body,
                }
            )

    ui_status: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        ctx = browser.new_context(no_viewport=True)
        ctx.add_cookies(cookies)
        ctx.on("request", on_req)
        ctx.on("response", on_res)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log(f"navigating to DB url")
        try:
            page.goto(db_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            log(f"goto error (continuing): {exc}")
        page.wait_for_timeout(5000)
        snap(page, "00_after_goto")

        try:
            ui_status = drive_ui(page, slack_url)
        except Exception as exc:  # noqa: BLE001
            log(f"drive_ui exception: {exc}")
            ui_status = {"error": str(exc)}
            snap(page, "99_exception")

        # Give any trailing network requests time to settle.
        page.wait_for_timeout(3000)
        ctx.close()
        browser.close()

    DUMP_PATH.write_text(
        json.dumps(
            {
                "test_db_id": db_id,
                "test_db_url": db_url,
                "slack_webhook_url": slack_url[:60] + "...",
                "ui_status": ui_status,
                "captures": captures,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    log(f"saved dump: {DUMP_PATH} ({len(captures)} events)")
    log(f"screenshots: {SCREENSHOT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
