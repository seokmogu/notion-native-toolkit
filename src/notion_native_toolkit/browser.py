from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .credentials import resolve_credential
from .profiles import WorkspaceProfile


class BrowserNotAvailableError(RuntimeError):
    pass


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

    async def login(self, headed: bool = True, timeout_seconds: int = 180) -> str:
        workspace_url = self.profile.workspace_url or "https://www.notion.so"
        email = resolve_credential(self.profile.browser_email)
        password = resolve_credential(self.profile.browser_password)
        manager, context, page = await self._open_context(headed=headed)
        try:
            await page.goto(workspace_url)
            await page.wait_for_load_state("domcontentloaded")
            if email and password:
                await self._attempt_login(page, email, password)
            await page.wait_for_timeout(3000)
            end_time = asyncio.get_running_loop().time() + timeout_seconds
            while asyncio.get_running_loop().time() < end_time:
                current_url = page.url
                if (
                    "notion.so" in current_url
                    and "/login" not in current_url
                    and "accounts.google" not in current_url
                ):
                    await context.storage_state(path=str(self._state_path()))
                    return str(self._state_path())
                await page.wait_for_timeout(1000)
            raise RuntimeError("Timed out waiting for a logged-in Notion session")
        finally:
            await context.close()
            await manager.__aexit__(None, None, None)

    async def _attempt_login(self, page: Any, email: str, password: str) -> None:
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[placeholder*="Email"]',
        ]
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
        ]
        for selector in email_selectors:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.fill(email)
                break
        for text in ["Continue with email", "Continue", "Sign in"]:
            button = page.get_by_role("button", name=text)
            if await button.count():
                await button.first.click()
                break
        await page.wait_for_timeout(1000)
        for selector in password_selectors:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.fill(password)
                break
        for text in ["Continue", "Log in", "Sign in"]:
            button = page.get_by_role("button", name=text)
            if await button.count():
                await button.first.click()
                break

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
