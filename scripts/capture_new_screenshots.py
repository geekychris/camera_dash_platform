"""Capture only the screenshots added for the latest features.

Run after ``capture_screenshots.py``; this script reuses its viewport and
output directory but only hits ``/dashboard`` and ``/events`` so a slow LAN
target (e.g. the Pi over wifi) doesn't time out on the full tour.

Produces:
   12-pointcloud.png   — 3D point-cloud tile cropped to its bounds
   13-audio-events.png — events list filtered to ``audio_event`` kind
   14-pwa-push.png     — dashboard header strip showing the bell button

Usage:
   CAMERA_DASH_UI=http://pi5-8.local:5173 \
     backend/.venv/bin/python scripts/capture_new_screenshots.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
VIEWPORT = {"width": 1600, "height": 1000}
BASE = os.environ.get("CAMERA_DASH_UI", "http://localhost:5173")


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
        ctx.set_default_navigation_timeout(60_000)
        ctx.set_default_timeout(10_000)
        page = await ctx.new_page()
        print(f"Capturing new screenshots from {BASE} to {OUT}")

        # 14 — PWA bell strip (do first; needs the least DOM warmup).
        await page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        bell = await page.query_selector('button:has-text("🔔")')
        if bell:
            box = await bell.bounding_box()
            if box:
                clip = {
                    "x": 0, "y": 0,
                    "width": VIEWPORT["width"],
                    "height": max(80, int(box["y"] + box["height"] + 8)),
                }
                await page.screenshot(path=str(OUT / "14-pwa-push.png"), clip=clip)
                print("  saved 14-pwa-push.png")
        else:
            print("  no 🔔 found (dashboard build may not include NotifyButton yet)")

        # 12 — point cloud tile. Same dashboard page; let WebGL + WS settle.
        await page.wait_for_timeout(3500)
        pc = await page.query_selector('span:has-text("point cloud")')
        if pc:
            box = await pc.bounding_box()
            if box:
                clip = {
                    "x": max(0, box["x"] - 24),
                    "y": max(0, box["y"] - 24),
                    "width": 720, "height": 460,
                }
                await page.screenshot(path=str(OUT / "12-pointcloud.png"), clip=clip)
                print("  saved 12-pointcloud.png")
        else:
            print("  no point-cloud tile found (no depth camera configured)")

        # 13 — audio events. Try to filter to audio_event kind; if no filter
        # input is found, capture the unfiltered events page so the section
        # at least has *something* rather than a broken README image.
        await page.goto(f"{BASE}/events", wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        kind_input = await page.query_selector('input[placeholder*="kind" i]')
        if kind_input:
            await kind_input.fill("audio_event")
            await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "13-audio-events.png"), full_page=True)
        print("  saved 13-audio-events.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
