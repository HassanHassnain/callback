"""Bounded browser audio decoding and Vultr stock-voice turns."""

import asyncio
import base64
import hashlib
import io
import json
import math
import time
import wave

from services.control.inference import InferenceError, redact

TTS = "qwen3-tts-12hz-1.7b"
STT = "whisper-large-v3-turbo"
UPLOAD_LIMIT = 1_048_576
SECONDS = 30
SAMPLE_RATE = 16_000
FORMATS = {
    "audio/webm": "matroska",
    "audio/ogg": "ogg",
    "audio/mp4": "mov",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def wav_duration(audio):
    with wave.open(io.BytesIO(audio), "rb") as clip:
        frames = clip.getnframes()
        if not frames or len(clip.readframes(frames)) != frames * clip.getsampwidth() * clip.getnchannels():
            raise ValueError("Incomplete WAV")
        return frames / clip.getframerate()


async def normalize(audio, content_type):
    if not 0 < len(audio) <= UPLOAD_LIMIT or content_type not in FORMATS:
        raise ValueError("Unsupported or oversized microphone clip")
    # Only fixed arguments and pipe I/O. No caller filenames, inherited secrets,
    # URLs, shell expansion, or agent commands enter the media decoder.
    worker = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-max_alloc", "16777216", "-threads", "1", "-protocol_whitelist", "pipe",
        "-f", FORMATS[content_type], "-i", "pipe:0", "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-t", str(SECONDS), "-ar", str(SAMPLE_RATE), "-ac", "1",
        "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin"},
    )
    try:
        pcm, _ = await asyncio.wait_for(worker.communicate(audio), timeout=8)
    finally:
        if worker.returncode is None:
            worker.kill()
            await worker.wait()
    if worker.returncode or not 0 < len(pcm) <= SECONDS * SAMPLE_RATE * 2:
        raise ValueError("Could not decode microphone audio")
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        clip.writeframes(pcm)
    return out.getvalue()


def observation(client, route, model, data, started, duration):
    return {
        "requested_model": model, "returned_model": data.get("model"),
        "seconds": round(time.monotonic() - started, 3),
        "audio_duration_seconds": duration, "usage": data.get("usage"),
        **client.validate_identity(route, model, data),
    }


async def transcribe(client, wav):
    duration = wav_duration(wav)
    started = time.monotonic()
    response = await client.request("audio/transcriptions", model=STT, audio_seconds=math.ceil(duration), body={
        "model": STT, "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"},
        "language": "en", "response_format": "json",
    })
    data = response.json()
    event = observation(client, "audio/transcriptions", STT, data, started, duration)
    transcript = data.get("text")
    if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 8000:
        raise InferenceError("No usable speech was transcribed")
    return redact(transcript.strip()), event


async def synthesize(client, text, voice="ryan"):
    if voice not in {"ryan", "aiden"} or not 0 < len(text) <= 450:
        raise ValueError("Expected a bounded reply and a stock voice")
    started = time.monotonic()
    response = await client.request("audio/speech", model=TTS, audio_seconds=90, body={
        "model": TTS, "input": text, "voice": voice, "response_format": "wav", "stream_format": "sse",
    })
    if "text/event-stream" not in response.headers.get("content-type", ""):
        raise InferenceError("Expected Vultr speech events")
    audio = bytearray()
    done = None
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:])
        if event.get("model") is not None:
            client.validate_identity("audio/speech", TTS, event)
        kind = event.get("type")
        if kind == "speech.audio.error" or "error" in event:
            raise InferenceError("Vultr speech generation failed")
        if kind == "speech.audio.delta":
            audio.extend(base64.b64decode(event.get("audio", event.get("delta", "")), validate=True))
        elif kind == "speech.audio.done":
            done = event
        if len(audio) > 5_000_000:
            raise InferenceError("Vultr speech output exceeded the byte limit")
    if done is None:
        raise InferenceError("Vultr speech stream did not finish")
    duration = wav_duration(audio)
    if not 0 < duration <= 90:
        raise InferenceError("Vultr speech output exceeded the duration limit")
    return bytes(audio), {
        **observation(client, "audio/speech", TTS, done, started, duration),
        "voice": voice, "audio_sha256": hashlib.sha256(audio).hexdigest(),
    }
