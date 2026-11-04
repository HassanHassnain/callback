"""Vultr-only transport with catalog validation and fail-closed model identity."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from typing import Any

import httpx

BASE_URL = "https://api.vultrinference.com/v1"
RETRYABLE = {429, 502, 503, 504, 529}


class InferenceError(RuntimeError):
    pass


class ModelIdentityError(InferenceError):
    pass


def redact(text: str) -> str:
    """Redact configured secrets and common credential shapes before diagnostics."""
    for name, value in os.environ.items():
        if len(value) >= 8 and any(x in name for x in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"(?i)(bearer\s+|sk[-_])[A-Za-z0-9._-]+", "[REDACTED]", text)


def assert_model(requested: str, response: dict[str, Any]) -> None:
    """Do not substitute the requested ID when the provider omits its ID."""
    returned = response.get("model")
    if returned != requested:
        raise ModelIdentityError(
            f"Model identity check failed: requested {requested!r}, returned {returned!r}"
        )


class VultrInference:
    def __init__(self, key: str, *, timeout: float = 90, retries: int = 2):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL + "/",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=httpx.Timeout(timeout, connect=15),
            follow_redirects=False,
        )
        self._has_key = bool(key)
        self._retries = retries
        self.models: dict[str, dict[str, Any]] = {}
        self._limits: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(16))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def catalog(self) -> dict[str, Any]:
        response = await self._client.get("models")
        if not response.is_success:
            raise InferenceError(f"Model catalog: HTTP {response.status_code}")
        data = response.json()
        self.models = {model["id"]: model for model in data["data"]}
        if not self.models:
            raise InferenceError("Provider returned an empty model catalog")
        for model in self.models:
            self._limits[model] = asyncio.Semaphore(8 if model.startswith("glm-5") else 16)
        return data

    def require_model(self, model: str) -> None:
        if model not in self.models:
            raise InferenceError(f"Model {model!r} absent from the live Vultr catalog")

    async def request(self, path: str, *, model: str, body: dict[str, Any]) -> httpx.Response:
        # The base URL is deliberately fixed. Never forward credentials to another host.
        if path not in {"chat/completions", "systemone", "audio/speech", "audio/transcriptions"}:
            raise InferenceError("Unsupported inference route")
        if body.get("model") != model:
            raise ModelIdentityError("Request model and declared model differ")
        self.require_model(model)
        if not self._has_key:
            raise InferenceError("VULTR_INFERENCE_API_KEY is missing")
        async with self._limits[model]:
            for attempt in range(self._retries + 1):
                response = await self._client.post(path, json=body)
                if response.status_code in RETRYABLE and attempt < self._retries:
                    delay = response.headers.get("retry-after", "")
                    try:
                        seconds = float(delay)
                    except ValueError:
                        seconds = float(2 ** attempt)
                    if not 0 <= seconds <= 60:
                        raise InferenceError("Provider requested a retry after more than 60 seconds")
                    await asyncio.sleep(seconds)
                    continue
                if not response.is_success:
                    # Avoid logging request headers, credentials, or entire provider errors.
                    try:
                        error = response.json().get("error", {})
                        detail = error.get("message", "") if isinstance(error, dict) else str(error)
                    except ValueError:
                        detail = "non-JSON provider error"
                    raise InferenceError(
                        redact(f"{path}: HTTP {response.status_code}: {detail[:400]}")
                    )
                return response
        raise InferenceError("Retry budget exhausted")

    async def json(self, path: str, *, model: str, **body: Any) -> dict[str, Any]:
        response = await self.request(path, model=model, body={"model": model, **body})
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise InferenceError("Expected a JSON response") from exc
        assert_model(model, data)
        return data
