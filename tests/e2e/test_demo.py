"""Opt-in browser verification of the explicitly labelled recorded-evidence demo."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.environ.get("CALLBACK_LIVE_E2E") != "1", reason="Opt-in public browser test")
def test_recorded_three_beats_and_fresh_tamper_receipt():
    base = os.environ.get("CALLBACK_PUBLIC_URL", "https://callback-45-63-34-5.sslip.io")
    manifest = httpx.get(base + "/api/demo", timeout=30).json()
    assert manifest["mode"] == "evidence_replay"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = ROOT / "docs/img" / ("P6-e2e-" + stamp)
    folder.mkdir(parents=True)
    observed = []
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".local/playwright-browsers"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, reduced_motion="reduce")
        page.goto(base + "/console?demo=1", wait_until="domcontentloaded")
        expect(page.get_by_text("EVIDENCE REPLAY", exact=True)).to_be_visible()
        for beat in manifest["beats"]:
            page.get_by_role("button", name=beat["title"], exact=False).click()
            expected = {"dana": "DENIED", "hostile": "BLOCKED", "sam": "APPLIED_VERIFIED"}[beat["id"]]
            expect(page.get_by_test_id("gate")).to_have_attribute("data-production-status", expected, timeout=30000)
            assert "demo=1" in page.url
            expect(page.get_by_text("TWIN DESTROYED", exact=False)).to_be_visible()
            if beat["id"] == "hostile":
                expect(page.get_by_text("Compromised. Contained.", exact=True)).to_be_visible()
                expect(page.get_by_text("14 OTP credentials removed in the twin", exact=True)).to_be_visible()
            page.screenshot(path=str(folder / (beat["id"] + "-gate.png")), animations="disabled")
            page.get_by_role("link", name="Verify signed receipt ↗", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Verified in this browser", timeout=30000)
            page.screenshot(path=str(folder / (beat["id"] + "-receipt.png")), animations="disabled")
            observed.append({"beat": beat["id"], "call_id": beat["call_id"], "production_status": expected, "browser_receipt_verified": True})
            page.goto(base + "/console?demo=1&call=" + beat["call_id"], wait_until="domcontentloaded")
        sam = next(beat for beat in manifest["beats"] if beat["id"] == "sam")
        page.goto(base + "/redteam?call=" + sam["call_id"], wait_until="domcontentloaded")
        button = page.get_by_role("button", name="Tamper signed copy → Dana", exact=True)
        expect(button).to_be_enabled(timeout=30000)
        with page.expect_response(lambda response: response.url.endswith("/tamper") and response.request.method == "POST") as result:
            button.click()
        payload = result.value.json()
        assert payload["receipt"]["payload"]["reason"]["code"] == "HASH_MISMATCH"
        assert payload["demonstration"]["after"]["username"] == "dana.whitfield"
        page.goto(base + "/receipts/" + payload["receipt"]["payload"]["receipt_id"], wait_until="domcontentloaded")
        expect(page.get_by_role("status")).to_contain_text("Verified in this browser", timeout=30000)
        page.screenshot(path=str(folder / "fresh-tamper-refusal.png"), animations="disabled")
        browser.close()
    report = {"observed_at": datetime.now(UTC).isoformat(), "mode": "evidence_replay_ui_plus_fresh_executor_tamper",
        "scope": "The three scenario executions are recorded evidence; this test does not claim to start new planner calls or operate a real phone.",
        "beats": observed, "fresh_tamper_refused": True, "fresh_tamper_receipt_verified_in_browser": True, "all_passed": True}
    (ROOT / "docs/infra" / ("P6-demo-e2e-" + stamp + ".json")).write_text(json.dumps(report, indent=2) + "\n")
