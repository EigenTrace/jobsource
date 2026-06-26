"""Async Playwright helper: render a page (JS executed) and return final HTML.

Most career sites are JS-heavy, so we use a real Chromium engine rather than a
plain HTTP GET. A single browser is launched per `BrowserSession` and reused
across page fetches. Cookie banners are dismissed best-effort.

If Playwright (or its browser binary) is unavailable, `fetch` falls back to a
plain httpx GET so the pipeline still returns *something* offline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_COOKIE_BUTTON_TEXTS = [
    "Accept all", "Accept All", "Accept", "I agree", "Agree",
    "Got it", "Allow all", "Allow cookies", "Accept cookies",
]


@dataclass
class RenderedPage:
    url: str          # final URL after redirects
    html: str
    ok: bool = True
    error: str = ""


class BrowserSession:
    """Async context manager wrapping a shared Chromium instance."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BrowserSession":
        try:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=settings.browser_headless)
            self._context = await self._browser.new_context(
                user_agent=_UA,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
        except Exception as exc:
            logger.warning("Playwright unavailable (%s); using httpx fallback.", exc)
            self._pw = None
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:  # pragma: no cover
            pass

    async def fetch(self, url: str) -> RenderedPage:
        if not url:
            return RenderedPage(url=url, html="", ok=False, error="empty url")
        if self._context is not None:
            return await self._fetch_playwright(url)
        return await _fetch_httpx(url)

    async def _fetch_playwright(self, url: str) -> RenderedPage:
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            await self._dismiss_cookies(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass  # networkidle is best-effort
            html = await page.content()
            final_url = page.url
            return RenderedPage(url=final_url, html=html, ok=True)
        except Exception as exc:
            return RenderedPage(url=url, html="", ok=False, error=str(exc))
        finally:
            await page.close()

    async def _dismiss_cookies(self, page) -> None:
        for text in _COOKIE_BUTTON_TEXTS:
            try:
                btn = page.get_by_role("button", name=text, exact=False)
                if await btn.count() > 0:
                    await btn.first.click(timeout=1500)
                    return
            except Exception:
                continue


async def _fetch_httpx(url: str) -> RenderedPage:
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers={"User-Agent": _UA}) as client:
            resp = await client.get(url)
            return RenderedPage(url=str(resp.url), html=resp.text, ok=resp.status_code < 400)
    except Exception as exc:
        return RenderedPage(url=url, html="", ok=False, error=str(exc))


async def fetch_one(url: str) -> RenderedPage:
    """Convenience for a single fetch without managing a session."""
    async with BrowserSession() as session:
        return await session.fetch(url)
