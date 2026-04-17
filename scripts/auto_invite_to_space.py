"""Auto-capture inviteGuestsToSpace by driving Settings → Members UI."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / ".chrome-automation-profile"
COOKIES_JSON = PROFILE_DIR / "cookies.json"
DUMP_PATH = Path(__file__).parent.parent / "docs" / "invite-to-space-capture.json"
SCREENSHOT_DIR = Path("/tmp/invite_space_capture")
API_FILTER = "/api/v3/"
TEST_EMAIL = "smguhome+spacecap@gmail.com"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def snap(page, name: str) -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"))
    except Exception as exc:
        log(f"snap {name} failed: {exc}")


def main() -> int:
    if not COOKIES_JSON.exists():
        log(f"ERROR: {COOKIES_JSON} missing")
        return 1
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    cookies = [c for c in json.loads(COOKIES_JSON.read_text())
               if "notion" in c.get("domain", "").lower()]
    log(f"loaded {len(cookies)} notion cookies")

    captures: list[dict] = []

    def on_req(req) -> None:
        if API_FILTER in req.url:
            captures.append({
                "kind": "request", "ts": time.time(),
                "method": req.method, "url": req.url,
                "post_data": req.post_data,
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
                body = f"<decode: {exc}>"
            captures.append({
                "kind": "response", "ts": time.time(),
                "status": res.status, "url": res.url, "body": body,
            })

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        ctx = browser.new_context(no_viewport=True)
        ctx.add_cookies(cookies)
        ctx.on("request", on_req)
        ctx.on("response", on_res)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Go straight to a Partner workspace page — triggers automatic workspace switch.
        PARTNER_URL = "https://www.notion.so/wxp-external/B2C-Project-3274d2a4aa13809db6acf3c2ce498c9e"
        page.goto(PARTNER_URL, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        log(f"url after goto: {page.url}")
        snap(page, "01_home")

        def click_text(labels: list[str], y_min: int = 0, y_max: int = 99999,
                       x_min: int = 0, x_max: int = 99999, label_tag: str = "") -> dict | None:
            """Find element with textContent in labels within coord box, JS-click it."""
            return page.evaluate(
                """(args) => {
                    const WANT = new Set(args.labels);
                    const nodes = document.querySelectorAll('[role="button"], button, [role="menuitem"], [role="tab"], a, div, span');
                    for (const n of nodes) {
                        if (n.offsetParent === null) continue;
                        const t = (n.textContent || '').trim();
                        if (!WANT.has(t)) continue;
                        const r = n.getBoundingClientRect();
                        if (r.width < 5 || r.height < 5) continue;
                        if (r.y < args.yMin || r.y > args.yMax) continue;
                        if (r.x < args.xMin || r.x > args.xMax) continue;
                        // climb to nearest clickable ancestor
                        let el = n;
                        for (let i=0; i<4 && el; i++) {
                            if (el.getAttribute('role') === 'button'
                                || el.tagName === 'BUTTON'
                                || el.getAttribute('role') === 'menuitem'
                                || el.getAttribute('role') === 'tab') {
                                break;
                            }
                            el = el.parentElement;
                        }
                        const cr = (el || n).getBoundingClientRect();
                        return {
                            label: t,
                            x: cr.x + cr.width/2,
                            y: cr.y + cr.height/2,
                        };
                    }
                    return null;
                }""",
                {"labels": labels, "yMin": y_min, "yMax": y_max,
                 "xMin": x_min, "xMax": x_max},
            )

        # Step 1: Click top-left workspace name button → dropdown menu
        ws_btn = page.evaluate(
            """() => {
                const btns = document.querySelectorAll('[role="button"]');
                for (const b of btns) {
                    if (b.offsetParent === null) continue;
                    const r = b.getBoundingClientRect();
                    if (r.y < 40 && r.x < 280 && r.width > 40 && r.height > 15) {
                        return { x: r.x + r.width/2, y: r.y + r.height/2,
                                 text: (b.textContent || '').trim().slice(0, 40) };
                    }
                }
                return null;
            }"""
        )
        log(f"workspace button: {ws_btn}")
        if ws_btn:
            page.mouse.click(ws_btn["x"], ws_btn["y"])
            page.wait_for_timeout(1800)
        snap(page, "02_ws_dropdown")

        # Step 2: In dropdown, click '멤버 초대' (short-circuit: skips Settings modal entirely)
        # The dropdown header shows two quick actions: '설정' and '멤버 초대'.
        invite_shortcut = click_text(
            ["멤버 초대", "Invite members", "Add members", "멤버추가"],
            y_min=30, y_max=200,  # dropdown top area, not sidebar bottom
        )
        log(f"invite shortcut: {invite_shortcut}")
        if invite_shortcut:
            page.mouse.click(invite_shortcut["x"], invite_shortcut["y"])
            page.wait_for_timeout(2500)
        snap(page, "03_invite_dialog_opened")

        # Guard: a modal/dialog must be open before we type anything.
        modal_present = page.evaluate(
            """() => {
                const sel = '[role="dialog"], [aria-modal="true"], .notion-overlay-container';
                return document.querySelectorAll(sel).length > 0;
            }"""
        )
        if not modal_present:
            log("invite dialog did not open — aborting to avoid page mistyping")
            ctx.close(); browser.close()
            DUMP_PATH.write_text(json.dumps({"captures": captures, "error": "invite_not_open"},
                                            ensure_ascii=False, indent=2, default=str))
            return 2

        # Step 6: Find email input INSIDE the settings/invite dialog only
        coords = page.evaluate(
            """(email) => {
                const modal = document.querySelector(
                    '[role="dialog"], [aria-modal="true"], .notion-overlay-container'
                );
                if (!modal) return null;
                const eds = modal.querySelectorAll(
                    'input, [contenteditable="true"], [role="textbox"], textarea'
                );
                const cand = [];
                for (const el of eds) {
                    if (el.offsetParent === null) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 80) continue;
                    const ph = (el.getAttribute('placeholder') || '').toLowerCase();
                    const al = (el.getAttribute('aria-label') || '').toLowerCase();
                    const score = (ph.includes('email') || al.includes('email')
                        || ph.includes('이메일') || al.includes('이메일')
                        || ph.includes('invite') || ph.includes('초대')) ? 10 : 0;
                    cand.push({
                        x: r.x + Math.min(30, r.width/2),
                        y: r.y + r.height/2,
                        score: score + (r.width / 100),
                        w: r.width,
                    });
                }
                cand.sort((a,b)=>b.score-a.score);
                return cand[0] || null;
            }""",
            TEST_EMAIL,
        )
        log(f"email field: {coords}")
        if coords:
            page.mouse.click(coords["x"], coords["y"])
            page.wait_for_timeout(400)
            page.keyboard.type(TEST_EMAIL, delay=20)
            page.wait_for_timeout(1500)
            # Commit the email as an invite token (pill) via Enter
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
        snap(page, "07_email_typed")

        # Step 7: Click Invite confirm button
        result = page.evaluate(
            """() => {
                const WANT = ['초대 요청', '초대요청', 'Send invite', 'Invite', '초대하기', '초대', 'Add', 'Request invite'];
                const btns = document.querySelectorAll('[role="button"], button');
                for (const b of btns) {
                    if (b.offsetParent === null) continue;
                    const t = (b.textContent || '').trim();
                    if (!WANT.includes(t)) continue;
                    const r = b.getBoundingClientRect();
                    if (r.width < 30 || r.height < 10) continue;
                    const ad = b.getAttribute('aria-disabled');
                    if (ad === 'true' || b.disabled) continue;
                    b.click();
                    return { label: t, x: r.x + r.width/2, y: r.y + r.height/2 };
                }
                return null;
            }"""
        )
        log(f"final invite click: {result}")
        page.wait_for_timeout(5000)
        snap(page, "08_after_invite")

        ctx.close()
        browser.close()

    DUMP_PATH.write_text(json.dumps({"captures": captures},
                                    ensure_ascii=False, indent=2, default=str))
    log(f"dump: {DUMP_PATH} ({len(captures)} events)")
    log(f"screenshots: {SCREENSHOT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
