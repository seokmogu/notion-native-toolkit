from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .credentials import resolve_credential
from .gmail import (
    configured_gmail_token_file,
    configured_gmail_user,
    fetch_notion_login_code_from_gmail,
    fetch_notion_login_link_from_gmail,
    get_gmail_access_token,
)
from .profiles import WorkspaceProfile


class BrowserNotAvailableError(RuntimeError):
    pass


_OTP_SELECTORS = [
    'input[autocomplete="one-time-code"]',
    'input[inputmode="numeric"]',
    'input[type="tel"]',
    'input[name*="code" i]',
    'input[aria-label*="code" i]',
    'input[placeholder*="code" i]',
]


@dataclass(slots=True)
class _LoginBrowserSession:
    manager: Any
    context: Any
    page: Any
    close_context: bool

    async def close(self) -> None:
        if self.close_context:
            await self.context.close()
        else:
            await self.page.close()
        await self.manager.__aexit__(None, None, None)


class NotionBrowserAutomation:
    def __init__(self, profile: WorkspaceProfile):
        self.profile = profile

    def _state_path(self) -> Path:
        raw = self.profile.browser_state_path
        if raw is None:
            raise ValueError("browser_state_path is not configured")
        path = Path(raw).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def _playwright(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserNotAvailableError(
                "playwright is not installed; run 'pip install -e .' and 'playwright install chromium'"
            ) from exc
        return async_playwright()

    async def _open_context(self, headed: bool) -> tuple[Any, Any, Any]:
        playwright_context = await self._playwright()
        playwright = await playwright_context.__aenter__()
        browser = await playwright.chromium.launch(headless=not headed)
        context = await browser.new_context(
            storage_state=self._state_path() if self._state_path().exists() else None
        )
        page = await context.new_page()
        return playwright_context, context, page

    async def login(
        self,
        headed: bool = True,
        timeout_seconds: int = 180,
        gmail_token_file: str | None = None,
        gmail_user: str | None = None,
        cdp_url: str | None = None,
    ) -> str:
        workspace_url = self.profile.workspace_url or "https://www.notion.so"
        email = resolve_credential(self.profile.browser_email)
        password = resolve_credential(self.profile.browser_password)
        login_started_at = datetime.now(UTC) - timedelta(seconds=5)
        token_file = configured_gmail_token_file(gmail_token_file)
        effective_gmail_user = configured_gmail_user(gmail_user)
        gmail_access_token: str | None = None
        session = await self._open_login_context(headed=headed, cdp_url=cdp_url)
        context = session.context
        page = session.page
        try:
            await page.goto(workspace_url)
            await page.wait_for_load_state("domcontentloaded")
            if email and password:
                await self._attempt_login(page, email, password)
            await page.wait_for_timeout(3000)
            end_time = asyncio.get_running_loop().time() + timeout_seconds
            code_submitted = False
            code_resent = False
            while asyncio.get_running_loop().time() < end_time:
                current_url = page.url
                if (
                    "notion.so" in current_url
                    and "/login" not in current_url
                    and "accounts.google" not in current_url
                ):
                    await context.storage_state(path=str(self._state_path()))
                    return str(self._state_path())
                if not code_submitted and token_file is not None:
                    if gmail_access_token is None:
                        gmail_access_token = get_gmail_access_token(token_file)
                    if gmail_access_token is not None:
                        link = fetch_notion_login_link_from_gmail(
                            gmail_access_token,
                            login_started_at,
                            gmail_user=effective_gmail_user,
                        )
                        if link:
                            await page.goto(link)
                            code_submitted = True
                    if (
                        gmail_access_token is not None
                        and not code_submitted
                        and await self._has_code_input(page)
                    ):
                        code = fetch_notion_login_code_from_gmail(
                            gmail_access_token,
                            login_started_at,
                            gmail_user=effective_gmail_user,
                        )
                        if code:
                            await self._submit_login_code(page, code)
                            code_submitted = True
                        elif not code_resent and await self._click_resend_code(page):
                            code_resent = True
                            login_started_at = datetime.now(UTC) - timedelta(seconds=5)
                await page.wait_for_timeout(1000)
            raise RuntimeError("Timed out waiting for a logged-in Notion session")
        finally:
            await session.close()

    async def _open_login_context(
        self,
        *,
        headed: bool,
        cdp_url: str | None,
    ) -> _LoginBrowserSession:
        if not cdp_url:
            manager, context, page = await self._open_context(headed=headed)
            return _LoginBrowserSession(
                manager=manager,
                context=context,
                page=page,
                close_context=True,
            )
        playwright_context = await self._playwright()
        playwright = await playwright_context.__aenter__()
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        return _LoginBrowserSession(
            manager=playwright_context,
            context=context,
            page=page,
            close_context=False,
        )

    async def _attempt_login(self, page: Any, email: str, password: str) -> None:
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[autocomplete="username"]',
            'input[placeholder*="Email"]',
            'input[placeholder*="이메일"]',
        ]
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]
        await self._wait_for_any(page, email_selectors, timeout_ms=15000)
        for selector in email_selectors:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.fill(email)
                break
        for text in ["Continue with email", "Continue", "Sign in", "계속"]:
            button = page.get_by_role("button", name=text)
            if await button.count():
                await button.first.click()
                break
        await page.wait_for_timeout(2000)
        password_filled = False
        for selector in password_selectors:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.fill(password)
                password_filled = True
                break
        if password_filled:
            for text in ["Continue", "Log in", "Sign in", "계속", "로그인"]:
                button = page.get_by_role("button", name=text)
                if await button.count():
                    await button.first.click()
                    break

    async def _wait_for_any(
        self,
        page: Any,
        selectors: list[str],
        *,
        timeout_ms: int,
    ) -> None:
        end_time = asyncio.get_running_loop().time() + (timeout_ms / 1000)
        while asyncio.get_running_loop().time() < end_time:
            for selector in selectors:
                if await page.locator(selector).count():
                    return
            await page.wait_for_timeout(250)

    async def _has_code_input(self, page: Any) -> bool:
        for selector in _OTP_SELECTORS:
            if await page.locator(selector).count():
                return True
        return False

    async def _submit_login_code(self, page: Any, code: str) -> None:
        inputs = []
        for selector in _OTP_SELECTORS:
            locator = page.locator(selector)
            count = await locator.count()
            if count:
                inputs = [locator.nth(index) for index in range(count)]
                break
        if not inputs:
            return
        if len(inputs) == 1:
            await inputs[0].fill(code)
        else:
            for index, digit in enumerate(code[: len(inputs)]):
                await inputs[index].fill(digit)
        for text in ["Continue", "Verify", "Log in", "Sign in", "계속", "인증"]:
            button = page.get_by_role("button", name=text)
            if await button.count():
                await button.first.click()
                return
        await page.keyboard.press("Enter")

    async def _click_resend_code(self, page: Any) -> bool:
        for text in ["인증 코드 재전송하기", "Resend code", "Resend"]:
            button = page.get_by_role("button", name=text)
            if await button.count():
                await button.first.click()
                return True
        return False

    async def list_teamspaces(self, headed: bool = False) -> list[dict[str, str]]:
        workspace_url = self.profile.workspace_url or "https://www.notion.so"
        manager, context, page = await self._open_context(headed=headed)
        try:
            await page.goto(workspace_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)
            await page.wait_for_timeout(2000)
            teamspaces = await page.evaluate(
                """
                () => {
                  const nodes = document.querySelectorAll('[data-testid="sidebar-teamspace"]');
                  return Array.from(nodes).map((node) => ({
                    name: node.textContent?.trim() || '',
                    href: node.href || ''
                  }));
                }
                """
            )
            if not isinstance(teamspaces, list):
                return []
            return [item for item in teamspaces if isinstance(item, dict)]
        finally:
            await context.close()
            await manager.__aexit__(None, None, None)

    async def create_teamspace(self, name: str, headed: bool = True) -> None:
        workspace_url = self.profile.workspace_url or "https://www.notion.so"
        manager, context, page = await self._open_context(headed=headed)
        try:
            await page.goto(workspace_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)
            for label in ["Create a teamspace", "New teamspace", "Create teamspace"]:
                button = page.get_by_role("button", name=label)
                if await button.count():
                    await button.first.click()
                    break
            await page.wait_for_timeout(1500)
            textbox = page.get_by_role("textbox").first
            if await textbox.count():
                await textbox.fill(name)
            create_button = page.get_by_role("button", name="Create")
            if await create_button.count():
                await create_button.first.click()
                await page.wait_for_timeout(3000)
        finally:
            await context.close()
            await manager.__aexit__(None, None, None)

    async def paste_markdown(
        self, page_url: str, markdown_text: str, headed: bool = True
    ) -> None:
        manager, context, page = await self._open_context(headed=headed)
        try:
            await page.goto(page_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)
            await page.wait_for_timeout(2000)
            await page.evaluate(
                """
                async (content) => {
                  await navigator.clipboard.writeText(content);
                }
                """,
                markdown_text,
            )
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Backspace")
            await page.keyboard.press("Meta+v")
            await page.wait_for_timeout(3000)
        finally:
            await context.close()
            await manager.__aexit__(None, None, None)
