"""Capture annotated dashboard screenshots via headless Chromium.

Walks through every major UI surface (Dashboard, Cameras, Editor, Examples,
Clips, Events) and saves a PNG per scene to ``docs/screenshots/``. Used by
the README's Visual Tour section.

By default the target is ``http://localhost:5173`` — point at a running Pi
deploy by setting ``CAMERA_DASH_UI=http://pi5-8.local:5173`` (or whichever
LAN host) so you get tiles with live cameras + running pipelines instead of
an empty editor.

Run via: ``backend/.venv/bin/python scripts/capture_screenshots.py``
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import Page, async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

VIEWPORT = {"width": 1600, "height": 1000}
BASE = os.environ.get("CAMERA_DASH_UI", "http://localhost:5173")


async def shot(page: Page, name: str, *, full: bool = True) -> None:
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=full)
    print(f"  saved {path.relative_to(OUT.parent.parent)}")


async def goto(page: Page, path: str, wait_ms: int = 1500) -> None:
    await page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
    await page.wait_for_timeout(wait_ms)


async def click_button_with_emoji(page: Page, emoji: str) -> bool:
    """Click the first button inside a CameraTile header that matches the emoji."""
    handle = await page.query_selector(f'button:has-text("{emoji}")')
    if handle is None:
        return False
    await handle.click()
    return True


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
        print(f"Capturing screenshots from {BASE} to {OUT}")

        # ============ DASHBOARD ============
        # Plain dashboard view — covers all the tiles auto-laid-out on top of
        # the underlying grid.
        await goto(page, "/dashboard", 4000)  # WebRTC needs a beat to connect
        await shot(page, "01-dashboard")

        # Stream share menu — click the 🔗 button on the first tile so the
        # popover with RTSP/HLS/WebRTC URLs + VLC/ffplay commands renders.
        if await click_button_with_emoji(page, "🔗"):
            await page.wait_for_timeout(600)
            await shot(page, "02-dashboard-share-menu")
            # Close the popover before moving on.
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

        # ============ CAMERAS ============
        await goto(page, "/cameras", 800)
        await shot(page, "03-cameras")

        # Click Discover so the per-device cards render.
        discover_btn = await page.query_selector('button:has-text("Discover")')
        if discover_btn:
            await discover_btn.click()
            await page.wait_for_timeout(1500)
            await shot(page, "04-cameras-discover")

        # ============ EXAMPLES GALLERY ============
        await goto(page, "/examples", 1500)
        await shot(page, "05-examples-gallery")

        # ============ PIPELINE EDITOR ============
        # Blank editor first.
        await goto(page, "/editor", 1500)
        await shot(page, "06-editor-blank")

        # Load the first listed pipeline from the left sidebar. The editor
        # renders pipelines as <button> elements (navigate() pushes the URL),
        # not anchors, so we look for one with a known prefix in the body.
        pipeline_btn = await page.query_selector(
            'button:has-text("FLIR"), button:has-text("Motion"), button:has-text("flir"), button:has-text("motion")'
        )
        if pipeline_btn:
            await pipeline_btn.click()
            await page.wait_for_timeout(2500)
            await shot(page, "07-editor-loaded")

            # Click any broadcast.stream node so the properties panel + the
            # `🖥️` "Dashboard surface" badge are both visible in one shot.
            stream_node = await page.query_selector(
                '.react-flow__node:has-text("broadcast.stream")'
            )
            if stream_node is None:
                stream_node = await page.query_selector(".react-flow__node")
            if stream_node:
                await stream_node.click()
                await page.wait_for_timeout(700)
                await shot(page, "08-editor-node-selected")

            # Hover a palette item so the help popover with description + port
            # info + config field docs renders. The palette buttons render the
            # type_id text plus a category icon — match by text-include.
            palette_btn = await page.query_selector(
                'button:has-text("detector.yolo_world")'
            )
            if palette_btn is None:
                palette_btn = await page.query_selector(
                    'button:has-text("source.camera")'
                )
            if palette_btn is None:
                palette_btn = await page.query_selector(
                    'button:has-text("transform.annotate")'
                )
            if palette_btn:
                await palette_btn.hover()
                await page.wait_for_timeout(700)
                await shot(page, "09-editor-palette-hover")

        # ============ CLIPS ============
        await goto(page, "/clips", 1200)
        await shot(page, "10-clips")

        # ============ EVENTS ============
        await goto(page, "/events", 3000)  # let some SSE events flow
        await shot(page, "11-events")

        await browser.close()
        print(f"\nDone. {len(list(OUT.glob('*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
