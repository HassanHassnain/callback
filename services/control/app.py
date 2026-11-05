"""P4 text-call API. Production apply remains explicitly disabled until P5."""

import asyncio
import contextlib
import json
import os
import re
import hmac
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.common.contracts import SignedDecision
from services.control.budget import Budget
from services.control.engine import Engine
from services.control.inference import VultrInference, redact
from services.control.models import DECISION, MODERATION, PLANNER, VISION
from services.control.faults import replay_hostile


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
            if call["status"] in {"ACTIVE", "AWAITING_DEVICE", "AWAITING_APPROVER"} and time.time() - call["created_epoch"] > 900:
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


@app.post("/internal/faults/hostile-replay")
async def hostile_replay(request: Request):
    expected = app.state.config.get("operator_token")
    if not expected or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + expected):
        raise HTTPException(403, "Private operator endpoint")
    models_ready()
    try:
        return await replay_hostile(app.state.engine)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        raise HTTPException(code if code in {425, 429, 503} else 502, "Operator twin is warming or unavailable") from exc


@app.get("/health")
async def health():
    pool = await app.state.engine.sandbox.request("GET", "/health")
    return {"status": "ok" if not app.state.monitor_error else "initializing", "phase": "P5",
            "application_ready": not app.state.monitor_error, "apply_ready": True,
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
    if sum(not c.get("destroy_proof") or bool(c.get("busy"))
           for c in engine.calls.values()) >= 3:
        raise HTTPException(429, "Three calls are already active")
    try:
        await engine.sync_seeds()
        result = await engine.create(body.realm)
        call = get_call(result["call_id"])
        call["created_epoch"] = time.time()
        engine.save(call)
        return engine.public(call)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Twin is warming; retry shortly") from exc
    except httpx.TransportError as exc:
        raise HTTPException(503, "Identity services are reconnecting; retry shortly") from exc
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


@app.post("/api/enrollments")
async def enroll(body: dict):
    from services.executor.enrollment import validate_bundle
    from services.common.crypto import digest
    try:
        payload = validate_bundle(body)
    except Exception as exc:
        raise HTTPException(400, "Enrollment proof did not verify") from exc
    root = app.state.engine.root / "enrollments"
    root.mkdir(exist_ok=True)
    identifier = digest(payload)
    path = root / (identifier + ".json")
    if not path.exists() and len(list(root.glob("*.json"))) >= 300:
        raise HTTPException(429, "Enrollment queue is full")
    path.write_text(json.dumps(body))
    path.chmod(0o600)
    return {"enrollment_id": identifier, "fingerprint": digest(payload["public_key"]), "pinned": False}


def enrollment_bundle(identifier):
    if not re.fullmatch(r"[a-f0-9]{64}", identifier):
        raise HTTPException(404)
    path = app.state.engine.root / "enrollments" / (identifier + ".json")
    if not path.is_file():
        raise HTTPException(404, "Enrollment not found")
    return json.loads(path.read_text())


@app.get("/api/enrollments/{identifier}")
def read_enrollment(identifier: str):
    return enrollment_bundle(identifier)


@app.get("/api/enrollments/{identifier}/status")
async def enrollment_status(identifier: str):
    try:
        response = await app.state.engine.executor.post("/enrollment/status", json=enrollment_bundle(identifier))
    except httpx.TransportError as exc:
        raise HTTPException(503, "Executor is reconnecting; enrollment request is preserved") from exc
    if response.is_error:
        raise HTTPException(502, "Executor enrollment check is unavailable")
    return response.json()


@app.get("/api/device/requests")
def device_requests(realm: Literal["acme", "acme-guest"], username: str):
    return [app.state.engine.public(c) for c in app.state.engine.calls.values()
            if c["realm"] == realm and c.get("confirmation_frozen") and any(e["target"].get("username") == username for e in c["effects"])
            and c["status"] in {"AWAITING_DEVICE", "AWAITING_APPROVER", "SUBMITTING", "APPLIED_VERIFIED", "DENIED", "REFUSED", "FAILED_VERIFY"}][-20:][::-1]


@app.post("/api/calls/{call_id}/decisions")
async def decision(call_id: str, body: SignedDecision):
    from services.control.approvals import decide
    engine = app.state.engine
    get_call(call_id)
    async with engine.locks[call_id]:
        try:
            return await decide(engine, get_call(call_id), body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(403, "Executor rejected the decision; its identity, scope, signature or timestamp did not verify") from exc


@app.post("/api/device/delivery")
async def delivery(body: dict):
    response = await app.state.engine.executor.post("/delivery", json=body)
    if response.is_error:
        raise HTTPException(403, "Encrypted delivery is unavailable or the registered device proof is invalid")
    return response.json()


@app.get("/api/receipts/{identifier}")
async def receipt(identifier: str):
    if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
        raise HTTPException(404)
    response = await app.state.engine.executor.get("/receipts/" + identifier)
    if response.is_error:
        raise HTTPException(response.status_code, "Receipt is not ready")
    return response.json()


@app.post("/api/calls/{call_id}/tamper")
async def tamper(call_id: str):
    from copy import deepcopy
    from services.control.approvals import request_for
    from services.common.crypto import verify
    call = get_call(call_id)
    if not call.get("signatures"):
        raise HTTPException(409, "A signed change set is required for this tamper test")
    body = deepcopy(request_for(call))
    # Keep the signed hash while changing the actual data.
    body["change_set"]["seed_version"] += "-tampered"
    response = await app.state.engine.executor.post("/apply", json=body)
    response.raise_for_status()
    result = response.json()
    verify(app.state.engine.public_key, result["receipt"]["payload"], result["receipt"]["signature"])
    call.setdefault("tamper_results", []).append(result["receipt"])
    app.state.engine.save(call)
    return result
