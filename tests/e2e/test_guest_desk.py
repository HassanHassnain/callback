"""Opt-in public guest desk verification from fresh Chrome profiles."""

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("CALLBACK_PUBLIC_URL", "https://callback-45-63-34-5.sslip.io")


async def guest(browser, persona, stamp):
    context = await browser.new_context(viewport={"width": 1920, "height": 1080})
    page = await context.new_page()
    started = time.monotonic()
    await page.goto(BASE + "/call?guest=1")
    await page.get_by_label("Guest persona").select_option(persona)
    startup_responses = []
    page.on("response", lambda response: startup_responses.append(response)
            if response.url.endswith("/api/guest/start") else None)
    try:
        await page.get_by_role("button", name="Start guest call").click()
        try:
            await expect(page.get_by_role("button", name="Send request")).to_be_enabled(timeout=120000)
        except AssertionError:
            print(persona, "guest start statuses", [response.status for response in startup_responses], flush=True)
            for response in startup_responses[-1:]:
                if not response.ok:
                    print("guest start failure", (await response.text())[:220], flush=True)
            raise
        ready_seconds = time.monotonic() - started
        await page.get_by_role("button", name="Send request").click()
        approve = page.get_by_role("button", name="Approve exact changes")
        await expect(approve).to_be_enabled(timeout=180000)
        await approve.click()
        reveal = page.get_by_role("button", name="Reveal temporary password")
        await expect(reveal).to_be_enabled(timeout=120000)
        applied_seconds = time.monotonic() - started
        call_id = page.url.split("call=")[-1]
        state = await (await page.request.get(BASE + "/api/calls/" + call_id)).json()
        assert state["realm"] == "acme-guest" and state["guest_username"] == persona
        assert state["production_status"] == "APPLIED_VERIFIED"
        assert "guest_session_token" not in state
        assert [e["type"] for e in state["effects"]] == ["user.password.reset"]
        await page.screenshot(path=str(ROOT / "docs/img" / f"P9-guest-{persona}-{stamp}.png"))
        await reveal.click()
        await expect(page.get_by_test_id("guest-password")).to_be_visible(timeout=15000)
        await page.get_by_role("button", name="Hide password").click()
        link = page.get_by_role("link", name="Verify signed receipt")
        receipt_page = await context.new_page()
        await receipt_page.goto(BASE + await link.get_attribute("href"))
        await expect(receipt_page.get_by_role("status")).to_contain_text("Verified in this browser", timeout=30000)
        reset = page.get_by_role("button", name="Reset my guest slot")
        await expect(reset).to_be_enabled(timeout=15000)
        await reset.click()
        await expect(page.get_by_role("status").filter(has_text="Your guest slot was reset.")).to_be_visible(timeout=30000)
        return {"persona": persona, "call_id": call_id, "ready_seconds": round(ready_seconds, 3),
                "elapsed_seconds_to_apply": round(applied_seconds, 3),
                "browser_decryption_observed": True, "receipt_verified": True, "signed_reset_verified": True}
    finally:
        await context.close()


@pytest.mark.skipif(os.environ.get("CALLBACK_GUEST_E2E") != "1", reason="Opt-in guest mode browser test")
def test_public_guest():
    async def run():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, channel="chrome")
            result = {"concurrent": []}
            if os.environ.get("CALLBACK_GUEST_CONCURRENT") == "1":
                outcomes = await asyncio.gather(*(guest(browser, persona, stamp) for persona in
                                                  ("isaac.morgan", "ava.bennett", "liam.foster")),
                                                return_exceptions=True)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
                    result["concurrent"].append(outcome)
            else:
                result["solo"] = await guest(browser, "isaac.morgan", stamp + "-solo")
                assert result["solo"]["elapsed_seconds_to_apply"] < 120, result["solo"]
            await browser.close()
        (ROOT / "docs/infra" / f"P9-public-guest-{stamp}.json").write_text(json.dumps(result, indent=2) + "\n")

    asyncio.run(run())
