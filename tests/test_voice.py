import asyncio
import base64
import io
import json
import shutil
import wave

import httpx
import pytest

from services.control.budget import Budget, BudgetExceeded
from services.control.inference import ModelIdentityError, VultrInference
from services.control.voice import STT, TTS, normalize, synthesize


def input_wav():
    wav = io.BytesIO()
    with wave.open(wav, "wb") as clip:
        clip.setparams((2, 2, 24000, 0, "NONE", "not compressed"))
        clip.writeframes(b"\0" * 96000)
    return wav.getvalue()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Needs FFmpeg")
def test_ffmpeg_uses_fixed_mono_16khz_output():
    async def run():
        output = await normalize(input_wav(), "audio/wav")
        with wave.open(io.BytesIO(output), "rb") as clip:
            assert (clip.getnchannels(), clip.getframerate(), clip.getnframes()) == (1, 16000, 16000)
        with pytest.raises(ValueError):
            await normalize(b"file:///etc/passwd", "audio/wav")

    asyncio.run(run())


@pytest.mark.parametrize("returned", [None, STT])
def test_speech_model_omission_exception_preserves_identity_but_mismatch_fails(returned):
    async def run():
        async with VultrInference("fixture") as client:
            client.models[TTS] = {"output_modalities": [{"type": "speech"}]}
            events = [
                {"type": "speech.audio.delta", "audio": base64.b64encode(input_wav()).decode()},
                {"type": "speech.audio.done", "model": returned},
            ]

            async def request(*args, **kwargs):
                return httpx.Response(200, text="\n".join("data: " + json.dumps(e) for e in events),
                                      headers={"Content-Type": "text/event-stream"})

            client.request = request
            if returned:
                with pytest.raises(ModelIdentityError):
                    await synthesize(client, "Fixture")
            else:
                audio, result = await synthesize(client, "Fixture")
                assert audio == input_wav()
                assert result["identity_validation"] == "catalog_only_user_exception"
                assert result["returned_model"] is None and result["model_id_verified"] is False

    asyncio.run(run())


def test_audio_reservation_uses_duration_and_second_pricing(tmp_path):
    async def run():
        budget = Budget(tmp_path / "budget.json", "0.04")
        model = {"output_modalities": [{"pricing": [{"type": "completion", "unit": "second", "cost_usd": "0.00028"}]}]}
        reservation = await budget.reserve(model, {}, audio_seconds=90)
        settled = await budget.settle(reservation, None)
        assert settled["budget_charge_usd"] == "0.02520"
        with pytest.raises(BudgetExceeded):
            await budget.reserve(model, {}, audio_seconds=90)

    asyncio.run(run())
