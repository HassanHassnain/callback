"""Render the narrated submission from actual browser captures and replay evidence."""

import argparse
import asyncio
import html
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from playwright.async_api import async_playwright, expect

from services.control.inference import VultrInference
from services.control.voice import synthesize, wav_duration

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://callback-45-63-34-5.sslip.io"
DURATIONS = (21, 24, 21, 19, 21, 19, 22, 19, 20, 23, 22, 18)
BROWSER_SIZE = {"width": 1920, "height": 1080}
DEMO = ROOT / "docs/img/P6-e2e-20261105T192549Z"
LABELS = {
    1: "Synthetic narration generated with a Vultr stock voice",
    2: "Public voice test | Synthetic stock caller",
    3: "Recorded live result | Physical phone decision",
    4: "Recorded denial | Browser signature verification",
    5: "Recorded operator test | Scripted workload, simulated claim",
    6: "Recorded operator test | Production digests matched",
    7: "Recorded live result | One reset verified",
    8: "Recorded browser test | Tampered hash refused",
    9: "Benchmark | Coverage as shown",
    10: "Live deployment | Four Vultr VMs",
    11: "Live guest desk | Simulated device",
    12: "callback-45-63-34-5.sslip.io",
}



def command(*args):
    subprocess.run(args, check=True)


async def narrate(lines, folder):
    key = dotenv_values(ROOT / ".env")["VULTR_INFERENCE_API_KEY"]
    async with VultrInference(key) as client:
        await client.catalog()
        limit = asyncio.Semaphore(2)

        async def speech(index, text):
            async with limit:
                data, evidence = await synthesize(client, text)
            path = folder / f"narration-{index:02d}.wav"
            path.write_bytes(data)
            return path, wav_duration(data), evidence

        return await asyncio.gather(*(speech(index, text) for index, text in enumerate(lines, 1)))


async def capture(browser, index, folder, duration):
    context = await browser.new_context(viewport=BROWSER_SIZE,
                                        record_video_dir=folder / "captures", record_video_size=BROWSER_SIZE)
    page = await context.new_page()
    try:
        if index in {3, 4, 5, 6, 7}:
            manifest = await (await page.request.get(BASE + "/api/demo")).json()
            beat_name = {3: "dana", 4: "dana", 5: "hostile", 6: "hostile", 7: "sam"}[index]
            beat = next(beat for beat in manifest["beats"] if beat["id"] == beat_name)
            await page.goto(BASE + "/console?demo=1&call=" + beat["call_id"], wait_until="domcontentloaded")
            await expect(page.get_by_test_id("gate")).to_be_visible(timeout=30000)
            if index in {4, 6}:
                await asyncio.sleep(2)
                await page.get_by_role("link", name="Verify signed receipt").click()
                await expect(page.get_by_role("status")).to_contain_text("Verified in this browser", timeout=30000)
            elif index == 5:
                await page.get_by_text("Compromised. Contained.", exact=True).scroll_into_view_if_needed()
            elif index == 7:
                await page.get_by_text("Compare before / after", exact=False).first.click()
        elif index == 9:
            await page.goto(BASE + "/race", wait_until="domcontentloaded")
            await expect(page.locator(".benchmark-run")).to_be_visible(timeout=30000)
        elif index == 10:
            await page.goto(BASE, wait_until="domcontentloaded")
            await expect(page.get_by_role("img", name=re.compile("isolated twin"))).to_be_visible(timeout=30000)
        elif index == 11:
            await page.goto(BASE + "/call?guest=1", wait_until="domcontentloaded")
            await expect(page.get_by_text("Simulated device", exact=False)).to_be_visible(timeout=30000)
        await asyncio.sleep(duration)
    finally:
        await context.close()
    return await page.video.path()


async def main(output):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = ROOT / ".local" / ("submission-video-" + stamp)
    folder.mkdir(parents=True)
    raw = (ROOT / "docs/video-script.md").read_text()
    lines = [text.strip() for _, text in re.findall(r"### (\d+) [^\n]+\n\n(.*?)(?=\n\n(?:###|##))", raw, re.S)]
    assert len(lines) == len(DURATIONS)
    speech = asyncio.create_task(narrate(lines, folder))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, channel="chrome")
        limit = asyncio.Semaphore(3)

        async def scene(index):
            async with limit:
                return await capture(browser, index, folder, DURATIONS[index - 1])

        jobs = {index: asyncio.create_task(scene(index)) for index in (3, 4, 5, 6, 7, 9, 10, 11)}
        captures = {index: await task for index, task in jobs.items()}
        labels = await browser.new_page(viewport={"width": 1920, "height": 56})
        for index, text in LABELS.items():
            await labels.set_content("<body style='margin:0;padding:15px 62px;background:#10141b;"
                                     "color:#edf0f5;font:23px system-ui'>" + html.escape(text))
            await labels.screenshot(path=folder / f"scope-{index:02d}.png")
        await browser.close()
    voices = await speech
    stills = {
        1: ROOT / "docs/cover.png",
        2: ROOT / "docs/img/P7-redteam_stock_clip-20261106T150701Z.png",
        8: DEMO / "fresh-tamper-refusal.png",
        12: ROOT / "docs/cover.png",
    }
    parts = []
    voice_report = []
    for index, (seconds, (wav, spoken_seconds, observation)) in enumerate(zip(DURATIONS, voices, strict=True), 1):
        part = folder / f"part-{index:02d}.mp4"
        label = folder / f"scope-{index:02d}.png"
        video = ["-loop", "1", "-framerate", "30", "-i", str(stills[index])] if index in stills else ["-i", str(captures[index])]
        visual = ("[0:v]scale=1920:1080,fps=30,setsar=1,tpad=stop_mode=clone:stop_duration=1[frame];"
                  "[frame][2:v]overlay=0:1024[output]")
        stock = ROOT / "web/public/voice/lost_phone.wav"
        caller_seconds = wav_duration(stock.read_bytes()) if index == 2 else 0
        tempo = max(1, spoken_seconds / (seconds - caller_seconds - 0.6))
        if tempo > 1.45:
            raise RuntimeError("Narration does not fit the scene duration")
        audio = f"atempo={tempo:.4f},loudnorm=I=-17:TP=-1.5:LRA=11"
        if index == 2:
            visual += (f";[1:a]{audio},aresample=48000,aformat=channel_layouts=mono[narrator];"
                       "[3:a]loudnorm=I=-17:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=mono[caller];"
                       "[caller][narrator]concat=n=2:v=0:a=1,apad[spoken]")
            sound = ["-i", str(stock)]
            audio_map = ["-map", "[spoken]"]
        else:
            sound = []
            audio_map = ["-map", "1:a", "-af", audio + ",apad"]
        command("ffmpeg", "-hide_banner", "-loglevel", "error", *video, "-i", str(wav), "-i", str(label), *sound,
                "-t", str(seconds), "-filter_complex", visual, "-map", "[output]", *audio_map,
                "-c:v", "libx264", "-threads", "3", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(part))
        parts.append(part)
        voice_report.append({"scene": index, "duration_seconds": seconds, "speech_tempo": tempo, **observation})
        print("Rendered scene", index, flush=True)
    playlist = folder / "parts.txt"
    playlist.write_text("".join(f"file '{path.name}'\n" for path in parts))
    output.parent.mkdir(parents=True, exist_ok=True)
    command("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist),
            "-c", "copy", "-movflags", "+faststart", str(output))
    (folder / "voice-evidence.json").write_text(json.dumps(voice_report, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output.resolve()))
