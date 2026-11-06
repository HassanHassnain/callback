"""Render the requested 1920 by 1080 cover at browser scale factor two."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, channel="chrome")
    page = browser.new_page(viewport={"width": 960, "height": 540}, device_scale_factor=2)
    page.goto((ROOT / "docs/cover.html").as_uri())
    assert page.locator("img").evaluate("image => image.complete && image.naturalWidth > 0")
    page.screenshot(path=str(ROOT / "docs/cover.png"), animations="disabled")
    browser.close()
