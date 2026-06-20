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

        # ============ POINT CLOUD ============
        # The dashboard automatically adds a `pointcloud` tile for any depth
        # camera (PointCloudTile). We just need to land on /dashboard and
        # confirm a 3D tile rendered before snapping. If no depth camera is
        # configured this is a no-op; the README still works because the
        # previous shot covers the dashboard.
        await goto(page, "/dashboard", 5000)  # WebGL + WS depth handshake
        pc_tile = await page.query_selector('span:has-text("point cloud")')
        if pc_tile:
            box = await pc_tile.bounding_box()
            if box:
                # Crop to the 3D tile + a margin so the README reader gets a
                # focused shot, not the whole layout.
                clip = {
                    "x": max(0, box["x"] - 24),
                    "y": max(0, box["y"] - 24),
                    "width": min(VIEWPORT["width"], 720),
                    "height": min(VIEWPORT["height"], 460),
                }
                await page.screenshot(path=str(OUT / "12-pointcloud.png"), clip=clip)
                print(f"  saved {Path('docs/screenshots/12-pointcloud.png')}")

        # ============ AUDIO EVENTS ============
        # Filter the events page to audio_event entries (the kind sink.sqlite
        # uses when the example audio pipeline is installed). If none exist,
        # the unfiltered events page is captured instead.
        await goto(page, "/events", 1500)
        kind_input = await page.query_selector('input[placeholder*="kind" i]')
        if kind_input:
            await kind_input.fill("audio_event")
            await page.wait_for_timeout(800)
        await shot(page, "13-audio-events")

        # ============ PWA NotifyButton ============
        # Snap the dashboard header strip so the 🔔 button is visible. The
        # full dashboard already covers the rest; we just want a tight crop
        # for the README.
        await goto(page, "/dashboard", 1500)
        bell = await page.query_selector('button:has-text("🔔")')
        if bell:
            box = await bell.bounding_box()
            if box:
                clip = {
                    "x": 0,
                    "y": 0,
                    "width": VIEWPORT["width"],
                    "height": max(80, int(box["y"] + box["height"] + 8)),
                }
                await page.screenshot(path=str(OUT / "14-pwa-push.png"), clip=clip)
                print(f"  saved {Path('docs/screenshots/14-pwa-push.png')}")

        await browser.close()
        print(f"\nDone. {len(list(OUT.glob('*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
