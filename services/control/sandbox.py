"""Authenticated VPC client; agent commands can only execute in disposable twins."""

import json
from pathlib import Path

import httpx


class Sandbox:
    def __init__(self, config_path="/opt/callback/control-private/sandbox.json"):
        config = json.loads(Path(config_path).read_text())
        self.client = httpx.AsyncClient(base_url=config["url"], trust_env=False, timeout=300,
            headers={"Authorization": "Bearer " + config["api_secret"]})

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def create(self, envelope):
        return await self.request("POST", "/create", json={"envelope": envelope})

    async def claim(self, realm="acme", *, allow_previous=False):
        return await self.request("POST", "/claim/" + realm, params={"allow_previous": allow_previous})

    async def exec(self, twin, language, code, *, capture_snapshot=False):
        return await self.request("POST", f"/twins/{twin}/exec", json={"language": language, "code": code, **({"capture_snapshot": True} if capture_snapshot else {})})

    async def snapshot(self, twin):
        return await self.request("GET", f"/twins/{twin}/snapshot")

    async def screenshot(self, twin, identifier):
        return await self.request("GET", f"/twins/{twin}/screenshots/{identifier}")

    async def kill(self, twin):
        return await self.request("POST", f"/twins/{twin}/kill")

    async def destroy(self, twin):
        return await self.request("POST", f"/twins/{twin}/destroy")

    async def prove_destroyed(self, twin):
        return await self.request("GET", f"/twins/{twin}/prove_destroyed")
