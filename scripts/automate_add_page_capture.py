"""Capture Notion DB Automation "Add page to database" action API.

Creates SOURCE and TARGET temp DBs, opens SOURCE in Playwright with the main
Chrome profile's cookies, drives the Automation UI to add an "Add page to
<TARGET>" action, and dumps all /api/v3/ traffic.

Produces ``docs/automation-add-page-capture.json``.

Usage:
    uv run python scripts/automate_add_page_capture.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from notion_native_toolkit.toolkit import NotionToolkit
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

PROFILE_DIR = Path.home() / ".chrome-automation-profile"
COOKIES_JSON = PROFILE_DIR / "cookies.json"
DUMP_PATH = Path(__file__).parent.parent / "docs" / "automation-add-page-capture.json"
SCREENSHOT_DIR = Path("/tmp/add_page_capture")
API_FILTER = "/api/v3/"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def create_test_db(tk: NotionToolkit, label: str, props: dict) -> tuple[str, str]:
    parent_id = tk.profile.default_parent_page_id
    assert parent_id, "profile default_parent_page_id not set"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    title = f"ADDPAGE_CAPTURE_{label}_{ts}"
    log(f"creating {label} DB '{title}' under parent {parent_id}")
    client = tk.require_client()
    resp = client.create_database(
        {
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": props,
        }
    )
    assert resp is not None, "create_database returned None"
    db_id = resp["id"]
    db_url = f"https://www.notion.so/{db_id.replace('-', '')}"
    log(f"created {label} DB: {db_id}")
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


def snap(page: Page, name: str) -> None:
    path = SCREENSHOT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        log(f"snap: {path}")
    except Exception as exc:
        log(f"snap failed {name}: {exc}")


def drive_ui(page: Page, target_db_title: str) -> dict:
    """Click through: ⚡ → + New automation → + 새 작업 → 페이지 추가 → TARGET DB."""
    status: dict = {"steps": []}

    def step(name: str, ok: bool, detail: str = "") -> None:
        status["steps"].append({"name": name, "ok": ok, "detail": detail})
        log(f"  step {name}: {'OK' if ok else 'FAIL'} {detail}")

    # Dismiss "open in app" modal
    try_click(page, 'button[aria-label*="닫기" i]', timeout=1500)
    page.wait_for_timeout(500)

    # 1) ⚡ Automation button — in this workspace it opens the automation
    # editor directly (not a panel with "+ New automation")
    sel = try_click(
        page,
        'div[role="button"][aria-label="Automations"]',
        'div[role="button"][aria-label="자동화"]',
        'button[aria-label="Automations"]',
        'button[aria-label="자동화"]',
        '[aria-label*="Automation"]',
        '[aria-label*="자동화"]',
    )
    step("open_automations", bool(sel), sel or "not found")
    snap(page, "01_editor_opened")
    if not sel:
        return status
    page.wait_for_timeout(2000)

    # 2) + 새 작업 (Add action) — editor opens with trigger/action sections
    sel = try_click(
        page,
        'text="+ 새 작업"',
        'text="새 작업"',
        'text="+ New action"',
        'text="New action"',
        'button:has-text("새 작업")',
        'button:has-text("New action")',
    )
    step("add_action", bool(sel), sel or "not found")
    snap(page, "03_action_menu")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # 4) 페이지 추가 option (Korean: "페이지 추가", English: "Add page")
    sel = try_click(
        page,
        'text="페이지 추가"',
        'text="Add page"',
        'text="페이지 추가 위치"',
        'div[role="menuitem"]:has-text("페이지 추가")',
        'div[role="menuitem"]:has-text("Add page")',
        '[role="option"]:has-text("페이지 추가")',
    )
    step("select_add_page", bool(sel), sel or "not found")
    snap(page, "04_add_page_selected")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # 5) Click "데이터 소스 선택" dropdown — this opens the DB picker
    sel = try_click(
        page,
        'text="데이터 소스 선택"',
        'text="Select data source"',
        'div[role="button"]:has-text("데이터 소스 선택")',
        'div[role="button"]:has-text("Select data source")',
    )
    step("open_db_picker", bool(sel), sel or "not found")
    page.wait_for_timeout(1500)
    snap(page, "05_db_picker")

    # 6) Click target DB by title. It may appear in a search list,
    # or we may need to type the title to filter. Try direct click first.
    sel = try_click(
        page,
        f'text="{target_db_title}"',
        f'div[role="menuitem"]:has-text("{target_db_title}")',
        f'[role="option"]:has-text("{target_db_title}")',
    )
    if not sel:
        # fallback: type partial title to filter the list, then click
        try:
            search = page.locator('input[placeholder*="검색" i], input[placeholder*="Search" i]').first
            if search.is_visible(timeout=1500):
                search.fill(target_db_title[:20])
                page.wait_for_timeout(1200)
                sel = try_click(
                    page,
                    f'text="{target_db_title}"',
                    f'[role="option"]:has-text("{target_db_title}")',
                )
        except Exception:
            pass
    step("pick_target_db", bool(sel), sel or "not found")
    snap(page, "06_target_db_selected")
    page.wait_for_timeout(1500)

    # 6.5) Fill the Name title field ("제목 없음" placeholder) — the
    # 활성화 button stays disabled until title is set.
    try:
        title_input = page.locator('[placeholder="제목 없음"], [placeholder="Untitled"]').first
        title_input.click(timeout=3000)
        page.keyboard.type("auto-created")
        page.wait_for_timeout(600)
        # Click outside to commit
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        log("  title set")
    except Exception as exc:
        log(f"  title set failed: {exc}")
    snap(page, "065_title_set")

    # 7) Save — find "활성화" role=button via JS then use Playwright real click
    snap(page, "07_before_save")
    clicked = False
    # First, extract a stable CSS path to the button via JS
    selector = None
    try:
        selector = page.evaluate(
            """() => {
                const texts = ['활성화', 'Activate', '저장', 'Save'];
                for (const t of texts) {
                    const els = [...document.querySelectorAll('[role="button"], button')];
                    const hit = els.find(el => (el.innerText || '').trim() === t);
                    if (hit) {
                        hit.setAttribute('data-autotest-save', '1');
                        return '[data-autotest-save="1"]';
                    }
                }
                return null;
            }"""
        )
    except Exception as exc:
        log(f"js-locate failed: {exc}")

    if selector:
        try:
            btn = page.locator(selector).first
            btn.scroll_into_view_if_needed(timeout=2000)
            btn.click(timeout=3000)
            clicked = True
        except Exception as exc:
            log(f"playwright-click failed: {exc}")
            # Fallback to dispatch mousedown/mouseup
            try:
                page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        const cx = r.left + r.width/2, cy = r.top + r.height/2;
                        const mk = (t) => new MouseEvent(t, {bubbles:true, cancelable:true, view:window, clientX:cx, clientY:cy, button:0});
                        el.dispatchEvent(mk('mousedown'));
                        el.dispatchEvent(mk('mouseup'));
                        el.dispatchEvent(mk('click'));
                        return true;
                    }""",
                    selector,
                )
                clicked = True
            except Exception as exc2:
                log(f"dispatch mouse failed: {exc2}")

    step("save", clicked, f"selector={selector}")
    page.wait_for_timeout(6000)
    snap(page, "08_after_save")

    return status


def main() -> int:
    if not COOKIES_JSON.exists():
        log(f"ERROR: cookies file missing: {COOKIES_JSON}")
        return 1
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    tk = NotionToolkit.from_profile("worxphere")

    # Create TARGET DB first (we need its title for UI selection)
    target_props = {
        "Name": {"title": {}},
        "Status": {"select": {"options": [{"name": "Open"}, {"name": "Done"}]}},
        "Note": {"rich_text": {}},
    }
    source_props = {
        "Name": {"title": {}},
        "Priority": {"select": {"options": [{"name": "High"}, {"name": "Low"}]}},
    }
    target_id, target_url = create_test_db(tk, "TARGET", target_props)
    source_id, source_url = create_test_db(tk, "SOURCE", source_props)

    # Resolve TARGET title back from the API (exact text for UI click)
    target_db = tk.client.fetch_database(target_id)
    assert target_db is not None
    target_title = "".join(t["plain_text"] for t in target_db.get("title", []))
    log(f"TARGET title: {target_title}")

    all_cookies = json.loads(COOKIES_JSON.read_text())
    cookies = [c for c in all_cookies if "notion" in c.get("domain", "").lower()]
    log(f"loaded {len(cookies)} notion cookies")

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
                    body = (res.text() or "")[:2000]
            except Exception as exc:
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
        # Headed mode is required — Notion detects pure headless and hides the
        # Automation UI. Move the window offscreen so it doesn't bother the user.
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-position=-2400,0", "--window-size=1400,900"],
        )
        ctx = browser.new_context(no_viewport=True)
        ctx.add_cookies(cookies)
        ctx.on("request", on_req)
        ctx.on("response", on_res)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log(f"navigating to SOURCE DB url")
        try:
            page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            log(f"goto error (continuing): {exc}")
        page.wait_for_timeout(5000)
        snap(page, "00_after_goto")

        try:
            ui_status = drive_ui(page, target_title)
        except Exception as exc:
            log(f"drive_ui exception: {exc}")
            ui_status = {"error": str(exc)}
            snap(page, "99_exception")

        page.wait_for_timeout(3000)
        ctx.close()
        browser.close()

    DUMP_PATH.write_text(
        json.dumps(
            {
                "source_db_id": source_id,
                "source_db_url": source_url,
                "target_db_id": target_id,
                "target_db_url": target_url,
                "target_db_title": target_title,
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
