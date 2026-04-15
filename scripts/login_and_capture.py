"""Login to Notion then capture DB Automation webhook API.

Uses NOTION_PASSWORD env var and user email from memory. Gives the user 90s
to handle SSO / MFA prompts interactively in the opened browser if needed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from notion_native_toolkit.toolkit import NotionToolkit
from playwright.sync_api import (
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

STATE_PATH = Path("~/.config/notion-native-toolkit/browser-state/worxphere.json").expanduser()
DUMP_PATH = Path(__file__).parent.parent / "docs" / "automation-webhook-capture.json"
SCREENSHOT_DIR = Path("/tmp/webhook_capture")
API_FILTER = "/api/v3/"
NOTION_EMAIL = os.environ.get("NOTION_EMAIL", "")
LOGIN_URL = "https://www.notion.so/login"
MAX_MANUAL_WAIT_S = 120


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def snap(page: Page, name: str) -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception as exc:
        log(f"snap failed {name}: {exc}")


def try_click(page: Page, *selectors: str, timeout: int = 4000) -> str | None:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout)
            el.click()
            return sel
        except Exception:
            continue
    return None


def try_fill(page: Page, value: str, *selectors: str, timeout: int = 4000) -> str | None:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout)
            el.fill(value)
            return sel
        except Exception:
            continue
    return None


def wait_for_logged_in(page: Page, timeout_s: int = 90) -> bool:
    """Wait until Notion main app loads (URL moves past /login)."""
    deadline = time.time() + timeout_s
    last_url = ""
    while time.time() < deadline:
        cur = page.url
        if cur != last_url:
            log(f"  current url: {cur}")
            last_url = cur
        # Success: on notion.so but not a login page anymore
        if "notion.so" in cur and "/login" not in cur and "/signup" not in cur:
            # Also verify body is app-like
            try:
                _ = page.locator('[data-block-id], [data-testid="sidebar"], .notion-topbar').first
                _.wait_for(state="visible", timeout=2000)
                return True
            except Exception:
                pass
        page.wait_for_timeout(1500)
    return False


def do_login(page: Page, email: str, password: str) -> bool:
    log(f"going to login page")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2500)
    snap(page, "login_01_initial")

    # Fill email
    sel = try_fill(
        page,
        email,
        'input[type="email"]',
        'input[name="email"]',
        'input[placeholder*="이메일" i]',
        'input[placeholder*="email" i]',
    )
    if not sel:
        log("FAIL: could not find email input")
        return False
    log(f"  email filled via {sel}")

    # Submit email
    sel = try_click(
        page,
        'button:has-text("계속")',
        'button:has-text("Continue")',
        'button[type="submit"]',
    )
    if not sel:
        # Try Enter key
        try:
            page.keyboard.press("Enter")
            sel = "<Enter>"
        except Exception:
            pass
    log(f"  submitted email via {sel}")
    page.wait_for_timeout(3500)
    snap(page, "login_02_after_email")

    # Try password field (if simple password login is available)
    sel = try_fill(
        page,
        password,
        'input[type="password"]',
        'input[name="password"]',
        timeout=4000,
    )
    if sel:
        log(f"  password filled via {sel}")
        try_click(
            page,
            'button:has-text("계속")',
            'button:has-text("Continue")',
            'button[type="submit"]',
        )
        page.wait_for_timeout(3500)
        snap(page, "login_03_after_password")
    else:
        log("  no password field — likely SSO / magic link")
        # Try clicking SSO button (Microsoft for @jobkorea)
        sel = try_click(
            page,
            'button:has-text("Microsoft")',
            'button:has-text("SSO")',
            'button:has-text("통합 로그인")',
            timeout=2500,
        )
        if sel:
            log(f"  clicked SSO: {sel}")
            page.wait_for_timeout(3000)
        snap(page, "login_03_sso_or_code")

    log(f"waiting up to {MAX_MANUAL_WAIT_S}s for login to complete "
        f"(handle MFA / magic-link in the browser if prompted)")
    ok = wait_for_logged_in(page, timeout_s=MAX_MANUAL_WAIT_S)
    snap(page, "login_04_final")
    if ok:
        log("LOGIN OK")
    else:
        log("LOGIN TIMEOUT")
    return ok


def drive_ui(page: Page, slack_url: str) -> dict:
    status: dict = {"steps": []}

    def step(name: str, ok: bool, detail: str = "") -> None:
        status["steps"].append({"name": name, "ok": ok, "detail": detail})
        log(f"  step {name}: {'OK' if ok else 'FAIL'} {detail}")

    # Step 1: lightning bolt opens the "New automation" modal directly.
    sel = try_click(
        page,
        '[aria-label="자동화"]',
        '[aria-label="Automations"]',
        '[aria-label*="Automation"]',
    )
    step("open_automation_modal", bool(sel), sel or "not found")
    snap(page, "ui_01_modal")
    if not sel:
        return status
    page.wait_for_timeout(2000)

    # Skip trigger setup. Focus on Action = Send webhook (API capture is the goal).
    # Step 3: + 새 작업 (action)
    sel = try_click(
        page,
        'text="+ 새 작업"',
        'text="새 작업"',
        'text="+ New action"',
        'text="New action"',
    )
    step("click_new_action", bool(sel), sel or "not found")
    snap(page, "ui_03_action_menu")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # Step 4: select 웹훅 전송
    sel = try_click(
        page,
        'text="웹훅 전송"',
        'text="웹훅 보내기"',
        'text="Send webhook"',
        '[role="menuitem"]:has-text("웹훅")',
        '[role="option"]:has-text("웹훅")',
        '[role="menuitem"]:has-text("webhook")',
    )
    step("select_send_webhook", bool(sel), sel or "not found")
    snap(page, "ui_04_webhook_form")
    if not sel:
        return status
    page.wait_for_timeout(1500)

    # Step 5: fill URL. Notion uses contenteditable divs with role=textbox.
    page.wait_for_timeout(800)
    snap(page, "ui_04b_pre_fill")

    filled = False
    # Strategy: find the "URL" label and the first contenteditable that comes after it.
    try:
        # xpath: label text "URL" (or "URL (1)"), then closest following editable
        url_box = page.locator(
            'xpath=//*[starts-with(normalize-space(.), "URL")]'
            '/following::*[@contenteditable="true"][1]'
        ).first
        url_box.wait_for(state="visible", timeout=3000)
        url_box.click()
        page.wait_for_timeout(300)
        page.keyboard.type(slack_url, delay=10)
        filled = True
        step("fill_url", True, "xpath:after URL label")
    except Exception as exc:
        log(f"  url-fill xpath error: {exc}")

    # Fallback: pick LAST visible empty contenteditable (URL usually appears late in the form)
    if not filled:
        try:
            all_ce = page.locator('[contenteditable="true"]')
            n = all_ce.count()
            for i in range(n - 1, -1, -1):
                box = all_ce.nth(i)
                if not box.is_visible():
                    continue
                txt = (box.text_content() or "").strip()
                if txt:
                    continue
                box.click()
                page.wait_for_timeout(200)
                page.keyboard.type(slack_url, delay=10)
                filled = True
                step("fill_url", True, f"ce-reverse idx={i}")
                break
        except Exception as exc:
            log(f"  url-fill fallback error: {exc}")

    if not filled:
        step("fill_url", False, "all strategies failed")
    page.wait_for_timeout(800)
    snap(page, "ui_05_url_filled")

    # If a "leave without saving" confirmation dialog is open, cancel it.
    try:
        cancel_in_dialog = page.locator(
            '[role="alertdialog"] >> text="취소", [role="dialog"] >> text="취소"'
        ).first
        if cancel_in_dialog.is_visible(timeout=1000):
            cancel_in_dialog.click()
            page.wait_for_timeout(500)
            log("  dismissed confirmation dialog")
    except Exception:
        pass

    # Step 6: save — actual Korean label is "만들기"
    sel = try_click(
        page,
        '[role="button"]:has-text("만들기")',
        'button:has-text("만들기")',
        '[role="button"]:has-text("완료")',
        '[role="button"]:has-text("저장")',
        '[role="button"]:has-text("생성")',
        '[role="button"]:has-text("Create")',
        '[role="button"]:has-text("Done")',
        '[role="button"]:has-text("Save")',
    )
    step("save", bool(sel), sel or "not found")
    page.wait_for_timeout(3500)
    snap(page, "ui_06_saved")
    return status


def main() -> int:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL") or ""
    password = os.environ.get("NOTION_PASSWORD") or ""
    db_id = os.environ.get("REUSE_DB_ID", "")

    if not slack_url:
        log("ERROR: SLACK_WEBHOOK_URL not set")
        return 1
    if not password:
        log("WARN: NOTION_PASSWORD not set — password login will be skipped")
    if not db_id:
        log("ERROR: REUSE_DB_ID not set")
        return 1

    db_url = f"https://www.notion.so/{db_id.replace('-', '')}"
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    captures: list[dict] = []

    def on_req(req) -> None:
        if API_FILTER in req.url:
            captures.append({
                "kind": "request",
                "ts": time.time(),
                "method": req.method,
                "url": req.url,
                "post_data": req.post_data,
                "headers": dict(req.headers),
            })

    def on_res(res) -> None:
        if API_FILTER in res.url:
            body: object | None = None
            try:
                ct = res.headers.get("content-type", "")
                if "application/json" in ct:
                    body = res.json()
                else:
                    body = (res.text() or "")[:5000]
            except Exception as exc:
                body = f"<decode error: {exc}>"
            captures.append({
                "kind": "response",
                "ts": time.time(),
                "status": res.status,
                "url": res.url,
                "body": body,
            })

    login_ok = False
    ui_status: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        # Reuse saved state if available
        ctx_kwargs: dict = {"no_viewport": True}
        if STATE_PATH.exists():
            ctx_kwargs["storage_state"] = str(STATE_PATH)
            log(f"reusing saved storage state: {STATE_PATH}")
        ctx = browser.new_context(**ctx_kwargs)
        ctx.on("request", on_req)
        ctx.on("response", on_res)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Try reusing state first: hit notion.so; if that lands on login, do login.
        log("testing existing session")
        try:
            page.goto("https://www.notion.so/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
        except Exception as exc:
            log(f"initial goto error: {exc}")

        needs_login = (
            "/login" in page.url
            or "/loginwithemail" in page.url
            or "/signup" in page.url
            or "notion.com" in page.url  # marketing/landing — means logged out
        )
        if needs_login:
            log(f"session missing/expired ({page.url}) — performing login")
            login_ok = do_login(page, NOTION_EMAIL, password)
        else:
            log(f"session seems active at {page.url}")
            login_ok = True

        if login_ok:
            try:
                ctx.storage_state(path=str(STATE_PATH))
                log(f"saved storage state: {STATE_PATH}")
            except Exception as exc:
                log(f"save state failed: {exc}")

            log(f"navigating to DB: {db_url}")
            try:
                page.goto(db_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:
                log(f"goto DB error: {exc}")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            snap(page, "ui_00_db_opened")

            # Fully automated flow.
            sel = try_click(
                page,
                '[aria-label="자동화"]',
                '[aria-label="Automations"]',
                '[aria-label*="Automation"]',
            )
            log(f"open automation modal: {sel}")
            page.wait_for_timeout(2000)
            snap(page, "a1_modal")

            # Add a trigger first (activation requires at least one).
            # Use "페이지 추가 완료" — simplest page.created trigger.
            sel = try_click(page, 'text="+ 새 조건"', 'text="새 조건"')
            log(f"new condition: {sel}")
            page.wait_for_timeout(1500)
            snap(page, "a1b_condition_menu")
            sel = try_click(
                page,
                'text="페이지 추가 완료"',
                'text="페이지가 추가됨"',
                'text="페이지 추가됨"',
                'text="Page added"',
            )
            log(f"pick trigger (page added): {sel}")
            page.wait_for_timeout(1500)
            snap(page, "a1c_trigger_picked")

            sel = try_click(page, 'text="+ 새 작업"', 'text="새 작업"')
            log(f"new action: {sel}")
            page.wait_for_timeout(1500)
            snap(page, "a2_action_menu")

            sel = try_click(
                page, 'text="웹훅 보내기"', 'text="웹훅 전송"', 'text="Send webhook"'
            )
            log(f"select send webhook: {sel}")
            page.wait_for_timeout(2500)
            snap(page, "a3_webhook_form")

            # JS-based URL field discovery: find text "URL" / "URL (1)" label,
            # then click the nearest editable element following it.
            url_typed = False
            coords = page.evaluate(
                """() => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while (node = walker.nextNode()) {
                        const t = (node.textContent || '').trim();
                        if (/^URL(\\s*\\(\\d+\\))?$/.test(t)) {
                            let ancestor = node.parentElement;
                            for (let depth = 0; depth < 6 && ancestor; depth++) {
                                const sib = ancestor.nextElementSibling;
                                if (sib) {
                                    const ed = sib.querySelector(
                                        '[contenteditable="true"], input:not([type="hidden"]), textarea, [role="textbox"]'
                                    );
                                    if (ed) {
                                        const r = ed.getBoundingClientRect();
                                        return {
                                            x: r.x + Math.min(20, r.width/2),
                                            y: r.y + r.height/2,
                                            tag: ed.tagName,
                                            ce: ed.getAttribute('contenteditable'),
                                            role: ed.getAttribute('role'),
                                        };
                                    }
                                }
                                ancestor = ancestor.parentElement;
                            }
                        }
                    }
                    // Fallback: any contenteditable inside the modal panel that is empty
                    const modal = document.querySelector('[role="dialog"]')
                        || document.querySelector('.notion-overlay-container');
                    if (modal) {
                        const eds = modal.querySelectorAll(
                            '[contenteditable="true"], input:not([type="hidden"]), textarea, [role="textbox"]'
                        );
                        for (const ed of eds) {
                            const t = (ed.textContent || ed.value || '').trim();
                            if (t) continue;
                            const r = ed.getBoundingClientRect();
                            if (r.width < 30) continue;
                            return {
                                x: r.x + Math.min(20, r.width/2),
                                y: r.y + r.height/2,
                                tag: ed.tagName,
                                ce: ed.getAttribute('contenteditable'),
                                role: ed.getAttribute('role'),
                            };
                        }
                    }
                    return null;
                }"""
            )
            log(f"URL field discovery: {coords}")
            if coords:
                page.mouse.click(coords["x"], coords["y"])
                page.wait_for_timeout(400)
                page.keyboard.type(slack_url, delay=12)
                url_typed = True
                log("  typed URL via coordinate click")

            snap(page, "a4_after_url_typing")
            log(f"url_typed = {url_typed}")

            # Save: find the primary button by JS (text "활성화") and click its center.
            page.wait_for_timeout(1500)
            saved = False
            btn_coords = page.evaluate(
                """() => {
                    const wanted = ['활성화', '만들기', '완료', '저장', 'Activate', 'Create'];
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    const candidates = [];
                    while (node = walker.nextNode()) {
                        const t = (node.textContent || '').trim();
                        if (wanted.includes(t)) {
                            let el = node.parentElement;
                            // walk up to a clickable ancestor
                            for (let i = 0; i < 5 && el; i++) {
                                if (el.getAttribute('role') === 'button'
                                    || el.tagName === 'BUTTON'
                                    || el.onclick
                                    || getComputedStyle(el).cursor === 'pointer') {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) {
                                        candidates.push({
                                            label: t, x: r.x + r.width/2, y: r.y + r.height/2,
                                            w: r.width, h: r.height,
                                        });
                                    }
                                    break;
                                }
                                el = el.parentElement;
                            }
                        }
                    }
                    return candidates;
                }"""
            )
            log(f"save button candidates: {btn_coords}")
            # Try JS-native click (handles disabled check + React events).
            js_click_result = page.evaluate(
                """() => {
                    const wanted = ['활성화', '만들기', '완료', '저장'];
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while (node = walker.nextNode()) {
                        const t = (node.textContent || '').trim();
                        if (!wanted.includes(t)) continue;
                        let el = node.parentElement;
                        for (let i = 0; i < 6 && el; i++) {
                            if (el.getAttribute('role') === 'button' || el.tagName === 'BUTTON') {
                                const ariaDisabled = el.getAttribute('aria-disabled');
                                const disabled = el.disabled || ariaDisabled === 'true';
                                if (disabled) {
                                    return { label: t, status: 'disabled', aria: ariaDisabled };
                                }
                                el.click();
                                // Also dispatch native mousedown/mouseup in case React is picky
                                ['mousedown', 'mouseup', 'click'].forEach(type => {
                                    el.dispatchEvent(new MouseEvent(type, {
                                        bubbles: true, cancelable: true, view: window
                                    }));
                                });
                                return { label: t, status: 'clicked' };
                            }
                            el = el.parentElement;
                        }
                    }
                    return { status: 'not_found' };
                }"""
            )
            log(f"JS click result: {js_click_result}")
            saved = bool(js_click_result and js_click_result.get("status") == "clicked")

            page.wait_for_timeout(4000)
            snap(page, "a5_after_save")
            ui_status = {"mode": "auto", "url_typed": url_typed, "saved": saved}
        else:
            log("login failed — skipping UI automation")
            ui_status = {"error": "login_failed"}

        ctx.close()
        browser.close()

    DUMP_PATH.write_text(json.dumps({
        "login_ok": login_ok,
        "test_db_id": db_id,
        "test_db_url": db_url,
        "slack_webhook_url": slack_url[:60] + "...",
        "ui_status": ui_status,
        "captures": captures,
    }, ensure_ascii=False, indent=2, default=str))
    log(f"saved dump: {DUMP_PATH} ({len(captures)} events)")
    log(f"screenshots: {SCREENSHOT_DIR}")
    return 0 if login_ok else 2


if __name__ == "__main__":
    sys.exit(main())
