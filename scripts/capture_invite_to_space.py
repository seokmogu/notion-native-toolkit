"""Capture Notion inviteGuestsToSpace payload via Workspace Settings → Members.

Opens a headed Chrome reusing main-profile cookies. User manually:
    1. Switches to the target workspace (partner).
    2. Settings & members → Members → Invite.
    3. Types guest email, clicks Invite.
Returns with Enter. All /api/v3/* traffic is dumped for analysis.

Usage:
    cd notion-native-toolkit
    uv run python scripts/capture_invite_to_space.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / ".chrome-automation-profile"
COOKIES_JSON = PROFILE_DIR / "cookies.json"
DUMP_PATH = Path(__file__).parent.parent / "docs" / "invite-to-space-capture.json"
API_FILTER = "/api/v3/"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    if not COOKIES_JSON.exists():
        log(f"ERROR: {COOKIES_JSON} missing — run sync-chrome-automation-profile.sh first")
        return 1
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    cookies = [c for c in json.loads(COOKIES_JSON.read_text())
               if "notion" in c.get("domain", "").lower()]
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

        page.goto("https://www.notion.so/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        print()
        print("=" * 70)
        print("  수동으로 다음 작업 수행:")
        print("    1) 좌상단 워크스페이스 이름 클릭 → '[웍스피어] Partner 외부협업' 전환")
        print("    2) 좌측 'Settings & members' 또는 Cmd+, → 'Members' 탭")
        print("    3) 'Invite' 또는 'Add members' 버튼 → 이메일 입력")
        print("    4) 'Invite' 클릭")
        print("    5) 완료되면 이 터미널에 Enter")
        print("=" * 70)
        print()
        try:
            input("Press Enter when done: ")
        except Exception:
            pass

        page.wait_for_timeout(2000)
        ctx.close()
        browser.close()

    DUMP_PATH.write_text(json.dumps({"captures": captures},
                                    ensure_ascii=False, indent=2, default=str))
    log(f"saved: {DUMP_PATH} ({len(captures)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
