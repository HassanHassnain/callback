import asyncio

import httpx
import pytest

from services.control.inference import (
    InferenceError,
    ModelIdentityError,
    VultrInference,
    assert_model,
    redact,
)


@pytest.mark.parametrize("response", [{}, {"model": "fallback-model"}, {"model": None}])
def test_wrong_or_missing_response_identity_is_rejected(response):
    with pytest.raises(ModelIdentityError):
        assert_model("requested-model", response)


def test_exact_response_identity_is_accepted():
    assert_model("requested-model", {"model": "requested-model"})


def test_redaction_covers_configured_secrets_and_bearer(monkeypatch):
    monkeypatch.setenv("VULTR_API_KEY", "synthetic-test-secret")
    assert redact("synthetic-test-secret Bearer synthetic-token") == "[REDACTED] [REDACTED]"


def test_unknown_model_is_refused_before_network():
    async def check():
        async with VultrInference("synthetic-key") as client:
            with pytest.raises(InferenceError, match="absent"):
                await client.json("chat/completions", model="unknown", messages=[])
    asyncio.run(check())


def test_transport_retries_transient_failure_but_rejects_model_fallback():
    async def check():
        calls = []

        def handler(request):
            calls.append(request)
            assert request.url.host == "api.vultrinference.com"
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"model": "fallback"})

        async with VultrInference("synthetic-key") as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(
                base_url="https://api.vultrinference.com/v1/",
                transport=httpx.MockTransport(handler),
            )
            client.models = {"expected": {"id": "expected"}}
            with pytest.raises(ModelIdentityError):
                await client.json("chat/completions", model="expected", messages=[])
            assert len(calls) == 2
    asyncio.run(check())
