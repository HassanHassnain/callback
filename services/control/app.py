"""P4 text-call API. Production apply remains explicitly disabled until P5."""

import asyncio
import contextlib
import json
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.control.budget import Budget
from services.control.engine import Engine
from services.control.inference import VultrInference, redact
from services.control.models import DECISION, MODERATION, PLANNER, VISION


async def monitor(app):
    while True:
        try:
            await app.state.engine.sync_seeds()
            usage = await app.state.inference.provider_usage()
            app.state.usage_observed = time.monotonic()
            app.state.monitor_error = None
            path = app.state.engine.root / "provider-usage.json"
            path.write_text(json.dumps(usage))
            path.chmod(0o600)
        except Exception as exc:
            app.state.monitor_error = type(exc).__name__
        for call in list(app.state.engine.calls.values()):
            if call["status"] in {"ACTIVE", "AWAITING_DEVICE"} and time.time() - call["created_epoch"] > 900:
                call["status"] = "EXPIRED"
            if call["status"] in {"ERROR", "CANCELLED", "EXPIRED", "ABORTED_RESTART"} and not call.get("destroy_proof"):
                with contextlib.suppress(httpx.HTTPError):
                    call["destroy_proof"] = (await app.state.engine.sandbox.destroy(call["twin"]["twin_id"]))["destroy_proof"]
                app.state.engine.save(call)
        await asyncio.sleep(45)


@asynccontextmanager
async def lifespan(app):
    config = json.loads(Path(os.environ.get("CONTROL_CONFIG", "/opt/callback/control-private/config.json")).read_text())
    app.state.config = config
    app.state.budget = Budget(Path(config["private_dir"]) / "budget.json", str(config.get("daily_budget_usd", 20)))
    inference = VultrInference(os.environ.get("VULTR_INFERENCE_API_KEY", ""), budget=app.state.budget)
    await inference.catalog()
    for model in (PLANNER, VISION, DECISION, MODERATION):
        inference.require_model(model)
    app.state.inference = inference
    app.state.engine = Engine(config, inference)
    await app.state.engine.recover_calls()
    app.state.usage_observed = 0
    app.state.monitor_error = "initializing"
    app.state.tasks = set()
    app.state.creation_lock = asyncio.Lock()
    app.state.rates = defaultdict(deque)
    await app.state.engine.sync_seeds()
    task = asyncio.create_task(monitor(app))
    try:
        yield
    finally:
        task.cancel()
        for pending in app.state.tasks:
            pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await app.state.engine.sandbox.client.aclose()
        await app.state.engine.executor.aclose()
        await inference._client.aclose()


app = FastAPI(title="Callback control", lifespan=lifespan)


@app.middleware("http")
async def boundary(request: Request, call_next):
    if request.method in {"POST", "PUT", "DELETE"}:
        if request.headers.get("origin") not in (None, app.state.config["public_url"]):
            return JSONResponse({"error": "Origin rejected"}, status_code=403)
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > 128000):
            return JSONResponse({"error": "Request too large"}, status_code=413)
        if request.headers.get("transfer-encoding") or (length is None and request.headers.get("content-type") == "application/json"):
            return JSONResponse({"error": "A bounded request body is required"}, status_code=411)
        ip = request.client.host
        timestamps = app.state.rates[ip]
        current = time.monotonic()
        while timestamps and timestamps[0] < current - 60:
            timestamps.popleft()
        if len(timestamps) >= 20:
            return JSONResponse({"error": "Rate limit; try again shortly"}, status_code=429)
        timestamps.append(current)
    return await call_next(request)


def get_call(call_id):
    call = app.state.engine.calls.get(call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    return call


def models_ready():
    if time.monotonic() - app.state.usage_observed > 120:
        raise HTTPException(503, "Inference usage monitor is not current")


class NewCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    realm: Literal["acme", "acme-guest"] = "acme"


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)


@app.get("/health")
async def health():
    pool = await app.state.engine.sandbox.request("GET", "/health")
    return {"status": "ok" if not app.state.monitor_error else "initializing", "phase": "P4",
            "application_ready": not app.state.monitor_error, "apply_ready": False,
            "warm_twins": pool["ready"], "monitor_error": app.state.monitor_error,
            "budget": app.state.budget.data, "synthetic_identities": True}


@app.get("/api/calls")
def calls():
    return [{key: c.get(key) for key in ["call_id", "realm", "status", "created_at", "production_status"]}
            for c in list(app.state.engine.calls.values())[-30:]][::-1]


@app.post("/api/calls")
async def create_call(body: NewCall):
    async with app.state.creation_lock:
        return await create_call_locked(body)


async def create_call_locked(body):
    models_ready()
    engine = app.state.engine
    if sum(not c.get("destroy_proof") or c.get("busy")
           for c in engine.calls.values()) >= 3:
        raise HTTPException(429, "Three calls are already active")
    try:
        result = await engine.create(body.realm)
        call = get_call(result["call_id"])
        call["created_epoch"] = time.time()
        engine.save(call)
        return engine.public(call)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Twin is warming; retry shortly") from exc
    except RuntimeError as exc:
        raise HTTPException(503, redact(str(exc))) from exc


@app.get("/api/calls/{call_id}")
def read_call(call_id: str):
    return app.state.engine.public(get_call(call_id))


@app.post("/api/calls/{call_id}/turn", status_code=202)
async def turn(call_id: str, body: Turn):
    models_ready()
    call = get_call(call_id)
    if call["status"] != "ACTIVE" or call.get("busy"):
        raise HTTPException(409, "Call is pending, ended or already processing")
    call["busy"] = True

    async def run():
        try:
            await app.state.engine.turn(call_id, body.text)
        finally:
            call["busy"] = False
            app.state.engine.save(call)

    task = asyncio.create_task(run())
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return {"status": "processing", "call_id": call_id}


@app.post("/api/calls/{call_id}/cancel")
async def cancel(call_id: str):
    call = get_call(call_id)
    call["status"] = "CANCELLED"
    result = await app.state.engine.sandbox.destroy(call["twin"]["twin_id"])
    call["destroy_proof"] = result["destroy_proof"]
    app.state.engine.save(call)
    return app.state.engine.public(call)


@app.get("/api/screenshots/{identifier}")
def screenshot(identifier: str):
    if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
        raise HTTPException(404)
    path = app.state.engine.root / "screenshots" / (identifier + ".png")
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")
