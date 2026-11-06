"""Opt-in public voice smoke using a stock clip as Chrome's microphone input."""

import json
import os
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("CALLBACK_PUBLIC_URL", "https://callback-45-63-34-5.sslip.io")


def create_call(page):
    for _ in range(30):
        response = page.request.post(BASE + "/api/calls", data={"realm": "acme"})
        if response.ok:
            return response.json()["call_id"]
        assert response.status in {425, 503}, response.text()
        time.sleep(4)
    pytest.fail("Warm twin unavailable")


def audio_started(page):
    result = page.locator("[data-playback-ms]")
    expect(result).to_be_visible(timeout=240000)
    return int(result.get_attribute("data-playback-ms"))


@pytest.mark.skipif(os.environ.get("CALLBACK_VOICE_E2E") != "1", reason="Opt-in public voice test")
def test_public_voice_and_text():
    assert httpx.get(BASE + "/health", timeout=20).json()["voice_ready"]
    observed = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(prefix="callback-voice-") as directory, sync_playwright() as playwright:
        microphone = Path(directory) / "microphone.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(ROOT / "web/public/voice/lost_phone.wav"),
                        "-ar", "16000", "-ac", "1", str(microphone)], check=True)
        browser = playwright.chromium.launch(headless=True, channel="chrome", args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
            f"--use-file-for-fake-audio-capture={microphone}%noloop",
        ])
        context = browser.new_context(permissions=["microphone"], viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        for source in ["browser_microphone_with_stock_wav", "redteam_stock_clip"]:
            call_id = create_call(page)
            try:
                page.goto(BASE + ("/call" if source.startswith("browser") else "/redteam") + "?call=" + call_id)
                if source.startswith("browser"):
                    button = page.get_by_role("button", name="Hold to talk")
                    expect(button).to_be_enabled(timeout=15000)
                    box = button.bounding_box()
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.mouse.down()
                    expect(page.get_by_role("button", name="Release to send")).to_be_visible(timeout=10000)
                    time.sleep(14)
                    page.mouse.up()
                else:
                    page.get_by_role("button", name="Send stock voice into call").click()
                milliseconds = audio_started(page)
                result = page.request.get(BASE + "/api/calls/" + call_id).json()
                assert any("airport" in line["text"].casefold() for line in result["transcript"] if line["role"] == "user")
                timing = result["voice_turns"][-1]
                assert timing["stt"]["requested_model"] == "whisper-large-v3-turbo"
                assert timing["tts"]["voice"] == "ryan"
                assert result["production_status"] == "UNCHANGED"
                print(source, result["status"], milliseconds, flush=True)
                observed.append({"source": source, "call_id": call_id, "release_or_send_to_playing_ms": milliseconds,
                                 "server": timing, "status": result["status"], "effects": [e["type"] for e in result["effects"]],
                                 "production_status": result["production_status"]})
                page.screenshot(path=str(ROOT / "docs/img" / f"P7-{source}-{stamp}.png"))
            finally:
                page.request.post(BASE + f"/api/calls/{call_id}/cancel")
        call_id = create_call(page)
        try:
            page.goto(BASE + "/call?call=" + call_id)
            phrase = "Can you explain your registered-device verification policy?"
            page.get_by_label("Your message").fill(phrase)
            page.get_by_role("button", name="Send request").click()
            expect(page.get_by_text(phrase, exact=True)).to_be_visible(timeout=45000)
            expect(page.locator(".utterance.assistant").first).to_be_visible(timeout=45000)
        finally:
            page.request.post(BASE + f"/api/calls/{call_id}/cancel")
        browser.close()
    evidence = {
        "scope": "Live Vultr planner and audio. Stock synthetic caller, including Chrome fake mic input. Voice tests do not sign changes.",
        "observed_at": datetime.now(UTC).isoformat(), "turns": observed, "text_fallback_verified": True,
        "median_browser_playback_ms": statistics.median(turn["release_or_send_to_playing_ms"] for turn in observed),
    }
    (ROOT / "docs/infra" / f"P7-browser-{stamp}.json").write_text(json.dumps(evidence, indent=2) + "\n")
