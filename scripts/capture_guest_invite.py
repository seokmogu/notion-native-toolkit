"""Capture Notion internal API for Guest invite (inviteGuestsToSpace).

Opens a page in a headed browser using the saved Chrome automation
profile's cookies, automates Share modal -> email input -> Invite,
and dumps /api/v3/* network traffic to docs/guest-invite-capture.json.

Usage:
    cd notion-native-toolkit
    TEST_PAGE_URL='https://www.notion.so/<page-id>' \
    GUEST_EMAIL='someone+ngtest@example.com' \
    uv run python scripts/capture_guest_invite.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

PROFILE_DIR = Path.home() / ".chrome-automation-profile"
COOKIES_JSON = PROFILE_DIR / "cookies.json"
DUMP_PATH = Path(__file__).parent.parent / "docs" / "guest-invite-capture.json"
SCREENSHOT_DIR = Path("/tmp/guest_invite_capture")
API_FILTER = "/api/v3/"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def snap(page: Page, name: str) -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"), full_page=False)
    except Exception as exc:
        log(f"snap {name} failed: {exc}")


def try_click(page: Page, *selectors: str, timeout: int = 4000) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return sel
        except Exception:
            continue
    return None


def main() -> int:
    test_url = os.environ.get("TEST_PAGE_URL") or ""
    guest_email = os.environ.get("GUEST_EMAIL") or ""
    if not test_url or not guest_email:
        log("ERROR: set TEST_PAGE_URL and GUEST_EMAIL env vars")
        return 1
    if not COOKIES_JSON.exists():
        log(f"ERROR: no cookies at {COOKIES_JSON}")
        return 1

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    cookies_all = json.loads(COOKIES_JSON.read_text())
    cookies = [c for c in cookies_all if "notion" in c.get("domain", "").lower()]
    log(f"loaded {len(cookies)} notion cookies")

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
                    body = (res.text() or "")[:3000]
            except Exception as exc:
                body = f"<decode error: {exc}>"
            captures.append({
                "kind": "response",
                "ts": time.time(),
                "status": res.status,
                "url": res.url,
                "body": body,
            })

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        ctx = browser.new_context(no_viewport=True)
        ctx.add_cookies(cookies)
        ctx.on("request", on_req)
        ctx.on("response", on_res)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        log(f"navigate: {test_url}")
        try:
            page.goto(test_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            log(f"goto warn: {exc}")
        page.wait_for_timeout(3500)
        snap(page, "01_page_loaded")

        # Click "공유" / "Share" top-right button
        sel = try_click(
            page,
            'text="공유"',
            'text="Share"',
            '[aria-label="공유"]',
            '[aria-label="Share"]',
        )
        log(f"open share: {sel}")
        page.wait_for_timeout(1500)
        snap(page, "02_share_opened")

        # Type guest email into the access input
        email_coords = page.evaluate(
            """(email) => {
                const eds = document.querySelectorAll(
                    'input[type="text"], input[type="email"], input:not([type="hidden"]), [contenteditable="true"], [role="textbox"]'
                );
                for (const el of eds) {
                    if (el.offsetParent === null) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 80) continue;
                    const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    // pick inputs that look like email/access inputs
                    if (placeholder.includes('email') || aria.includes('email')
                        || placeholder.includes('이메일') || placeholder.includes('사람')
                        || placeholder.includes('add people') || placeholder.includes('invite')) {
                        return { x: r.x + r.width/2, y: r.y + r.height/2, hit: placeholder || aria };
                    }
                }
                return null;
            }""",
            guest_email,
        )
        log(f"email field: {email_coords}")
        if email_coords:
            page.mouse.click(email_coords["x"], email_coords["y"])
            page.wait_for_timeout(400)
            page.keyboard.type(guest_email, delay=15)
            page.wait_for_timeout(1200)
            snap(page, "03_email_typed")

            # A completion entry usually appears — click it
            entry = try_click(
                page,
                f'text="{guest_email}"',
                'div[role="option"]',
                '[role="menuitem"]',
            )
            log(f"select entry: {entry}")
            page.wait_for_timeout(800)
            snap(page, "04_entry_selected")

            # Primary button inside Share modal is labeled "Share" (or "공유").
            # JS click() didn't trigger Notion's React handler last time, so
            # use Playwright's real mouse.click at the discovered coordinates.
            # Exclude the page's top-bar Share button (y < 40). The modal
            # primary button lives just above/beside the email input.
            coords = page.evaluate(
                f"""() => {{
                    const WANT_EXACT = new Set(['Share', '공유', '공유하기', 'Invite', '초대']);
                    const WANT_PREFIX = ['공유', 'Share', 'Invite', '초대'];
                    const matchText = (t) => {{
                        if (WANT_EXACT.has(t)) return true;
                        return WANT_PREFIX.some(p => t.startsWith(p)) && t.length < 20;
                    }};
                    const EMAIL_Y = {email_coords['y']};
                    const EMAIL_X = {email_coords['x']};
                    const btns = Array.from(document.querySelectorAll(
                        '[role="button"], button'
                    ));
                    const matches = [];
                    for (const b of btns) {{
                        const t = (b.textContent || '').trim();
                        if (!matchText(t)) continue;
                        if (b.offsetParent === null) continue;
                        const r = b.getBoundingClientRect();
                        if (r.width < 5 || r.height < 5) continue;
                        const cx = r.x + r.width / 2;
                        const cy = r.y + r.height / 2;
                        // Reject topbar area (the page's own Share button)
                        if (cy < 40) continue;
                        // Prefer buttons near the email input (same popover)
                        const dx = Math.abs(cx - EMAIL_X);
                        const dy = Math.abs(cy - EMAIL_Y);
                        if (dx > 600 || dy > 500) continue;
                        const ad = b.getAttribute('aria-disabled');
                        matches.push({{
                            label: t, x: cx, y: cy, w: r.width, h: r.height,
                            distance: dx + dy,
                            disabled: ad === 'true' || b.disabled === true,
                        }});
                    }}
                    matches.sort((a, b) => a.distance - b.distance);
                    return matches.length ? matches[0] : null;
                }}"""
            )
            log(f"share button: {coords}")
            if coords and not coords.get("disabled"):
                page.mouse.click(coords["x"], coords["y"])
                log(f"clicked at ({coords['x']:.0f},{coords['y']:.0f})")
            else:
                # Fallback: Enter key
                page.keyboard.press("Enter")
                log("fallback: pressed Enter")
            page.wait_for_timeout(4000)
            snap(page, "05_after_invite")

        ctx.close()
        browser.close()

    DUMP_PATH.write_text(
        json.dumps({"test_url": test_url, "guest_email": guest_email, "captures": captures},
                   ensure_ascii=False, indent=2, default=str)
    )
    log(f"saved dump: {DUMP_PATH} ({len(captures)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
