import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_claim_skips_ready_record_until_initial_snapshot_exists(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner_id": "test-owner", "api_secret": "synthetic-test-secret"}))
    monkeypatch.setenv("SANDBOX_CONFIG", str(config))
    spec = importlib.util.spec_from_file_location("callback_daemon_readiness_test", Path("services/twin/daemon.py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    base = {"realm": "acme", "status": "READY", "claimed": False, "seed_version": "v1"}
    module.RECORDS.update({"warming": {**base, "twin_id": "warming"},
                           "complete": {**base, "twin_id": "complete", "initial_snapshot": {"users": {}}}})
    module.SEEDS["acme"] = {"payload": {"version": "v1"}}

    async def run():
        result = await module.claim("acme")
        assert result["twin_id"] == "complete"
        assert module.RECORDS["warming"]["claimed"] is False
        with pytest.raises(HTTPException) as error:
            await module.claim("acme")
        assert error.value.status_code == 425

    asyncio.run(run())
