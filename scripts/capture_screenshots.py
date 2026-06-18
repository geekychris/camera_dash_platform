"""Capture dashboard screenshots via headless Chromium.

Assumes the backend, frontend, and MediaMTX are all running at the usual ports.
Writes to docs/screenshots/.

Run via: ``backend/.venv/bin/python scripts/capture_screenshots.py``
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

VIEWPORT = {"width": 1600, "height": 1000}
BASE = os.environ.get("CAMERA_DASH_UI", "http://localhost:5173")


async def shot(page, name: str, *, full: bool = True) -> None:
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=full)
    print(f"  saved {path.relative_to(OUT.parent.parent)}")


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = await browser.new_context(viewport=VIEWPORT, ignore_https_errors=True,
                                          permissions=["camera", "microphone"])
        page = await ctx.new_page()

        print(f"Capturing screenshots to {OUT}")

        # Dashboard
        await page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)  # let WebRTC try to connect + tiles place
        await shot(page, "01-dashboard")

        # Examples gallery
        await page.goto(f"{BASE}/examples", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        await shot(page, "02-examples-gallery")

        # Pipelines editor (open first available pipeline)
        await page.goto(f"{BASE}/editor", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        await shot(page, "03-editor-blank")

        # Try to navigate to an existing pipeline (if any)
        first_link = await page.query_selector('a[href^="/editor/"]')
        if first_link:
            await first_link.click()
            await page.wait_for_timeout(2000)
            await shot(page, "04-editor-loaded")

        # Cameras tab
        await page.goto(f"{BASE}/cameras", wait_until="domcontentloaded")
        await page.wait_for_timeout(800)
        await shot(page, "05-cameras")

        # Clips
        await page.goto(f"{BASE}/clips", wait_until="domcontentloaded")
        await page.wait_for_timeout(1200)
        await shot(page, "06-clips")

        # Events
        await page.goto(f"{BASE}/events", wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)  # let some SSE events flow
        await shot(page, "07-events")

        await browser.close()
        print(f"\nDone. {len(list(OUT.glob('*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
