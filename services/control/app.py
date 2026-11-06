"""Callback call, approval, voice and evidence APIs."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import hmac
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from services.common.contracts import SignedDecision, OperatorProof
from services.control import voice
from services.control.budget import Budget, BudgetExceeded
from services.control.engine import Engine
from services.control.inference import InferenceError, VultrInference, redact
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
        engine = app.state.engine
        for call in list(engine.calls.values()):
            try:
                if call["status"] == "ACTIVE" and time.time() - call["created_epoch"] > 900:
                    call["status"] = "EXPIRED"
                elif call["status"] in {"AWAITING_DEVICE", "AWAITING_APPROVER"} and time.time() - call.get("approval_requested_epoch", call["created_epoch"]) > 3600:
                    call["status"] = "EXPIRED"
                if call["status"] in {"ERROR", "CANCELLED", "EXPIRED", "ABORTED_RESTART"} and not call.get("destroy_proof"):
                    result = await engine.sandbox.destroy(call["twin"]["twin_id"])
                    call["destroy_proof"] = result["destroy_proof"]
                    engine.save(call)
            except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
                print("Call teardown will retry: " + type(exc).__name__, flush=True)
        # Bound archival work and keep a malformed historical row from starving later calls.
        for closed in engine.calls.values():
            if (closed.get("destroy_proof") and not closed.get("receipt")
                    and time.time() - closed.get("receipt_attempt_epoch", 0) >= 120
                    and closed["status"] in {"COMPROMISED", "REJECTED", "CANCELLED", "ERROR", "EXPIRED",
                                             "ABORTED_RESTART", "CONTAINMENT_VERIFIED", "CONTAINMENT_FAILED", "ENDED"}):
                closed["receipt_attempt_epoch"] = time.time()
                try:
                    await engine.record_closed_call(closed)
                except Exception as exc:
                    print("Closed-call receipt will retry: " + type(exc).__name__, flush=True)
                break
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
    app.state.voice_ready = bool(shutil.which("ffmpeg")) and {voice.TTS, voice.STT} <= inference.models.keys()
    app.state.inference = inference
    app.state.engine = Engine(config, inference)
    await app.state.engine.recover_calls()
    app.state.usage_observed = 0
    app.state.monitor_error = "initializing"
    app.state.tasks = set()
    app.state.creation_lock = asyncio.Lock()
    for path in (app.state.engine.root / "operator-jobs").glob("*.json"):
        job = json.loads(path.read_text())
        if job["status"] == "RUNNING":
            job["status"] = "INTERRUPTED_RESTART"
            path.write_text(json.dumps(job))
            path.chmod(0o600)
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
        audio_upload = request.method == "POST" and re.fullmatch(r"/api/calls/[^/]+/audio", request.url.path)
        limit = voice.UPLOAD_LIMIT if audio_upload else 128000
        if length is not None and (not length.isdigit() or int(length) > limit):
            return JSONResponse({"error": "Request too large"}, status_code=413)
        if request.headers.get("transfer-encoding") or (length is None and (audio_upload or request.headers.get("content-type") == "application/json")):
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


def authorize_guest(request, call):
    expected = call.get("guest_session_token")
    if expected and not hmac.compare_digest(request.headers.get("x-callback-guest-token", ""), expected):
        raise HTTPException(403, "This guest call belongs to another browser session")


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
    error = app.state.monitor_error
    if not error and time.monotonic() - app.state.usage_observed > 120:
        error = "usage_monitor_stale"
    return {"status": "ok" if not error else "initializing", "phase": "P9", "voice_ready": app.state.voice_ready,
            "application_ready": not error, "apply_ready": True,
            "warm_twins": pool["ready"], "monitor_error": error,
            "budget": app.state.budget.data, "synthetic_identities": True}


@app.get("/api/calls")
def calls():
    return [{key: c.get(key) for key in ["call_id", "realm", "status", "created_at", "production_status"]}
            for c in list(app.state.engine.calls.values())[-30:]][::-1]


@app.post("/api/calls")
async def create_call(body: NewCall):
    async with app.state.creation_lock:
        return await create_call_locked(body)


async def create_call_locked(body, *, guest=None):
    models_ready()
    engine = app.state.engine
    if sum(not c.get("destroy_proof") or bool(c.get("busy"))
           for c in engine.calls.values()) >= 3:
        raise HTTPException(429, "Three calls are already active")
    try:
        await engine.sync_seeds()
        result = await engine.create(body.realm, guest=guest)
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


class GuestProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict
    signature: str = Field(min_length=80, max_length=100)


@app.post("/api/guest/start")
async def start_guest(body: GuestProof):
    models_ready()
    engine = app.state.engine
    async with app.state.creation_lock:
        response = await engine.executor.post("/guest/enroll", json=body.model_dump())
        if response.status_code == 403:
            error = response.json()
            raise HTTPException(409 if error.get("code") == "GUEST_BUSY" else 403,
                                error.get("detail", "Guest device enrollment refused"))
        if not response.is_success:
            raise HTTPException(503, "Guest enrollment is unavailable")
        guest = response.json()
        for call in engine.calls.values():
            if call.get("guest_lease") == guest["id"]:
                return {**engine.public(call), "guest_session_token": call["guest_session_token"]}
        result = await create_call_locked(NewCall(realm="acme-guest"), guest=guest)
        return {**result, "guest_session_token": get_call(result["call_id"])["guest_session_token"]}


@app.post("/api/guest/reset")
async def reset_guest(body: GuestProof):
    engine = app.state.engine
    async with app.state.creation_lock:
        call = next((c for c in engine.calls.values()
                     if c.get("guest_lease") and c["guest_lease"] == body.payload.get("lease_id")), None)
        if call and (call.get("busy") or call["status"] == "SUBMITTING"):
            raise HTTPException(409, "Wait for this call to finish processing")
        response = await engine.executor.post("/guest/reset", json=body.model_dump())
        if not response.is_success:
            raise HTTPException(403 if response.status_code == 403 else 503, "Guest reset refused or unavailable")
        if call and call["status"] in {"ACTIVE", "AWAITING_DEVICE", "AWAITING_APPROVER"}:
            call["status"] = "CANCELLED"
            await engine.destroy_twin(call)
            engine.save(call)
        return response.json()


@app.get("/api/calls/{call_id}")
def read_call(call_id: str):
    return app.state.engine.public(get_call(call_id))


@app.post("/api/calls/{call_id}/turn", status_code=202)
async def turn(call_id: str, body: Turn, request: Request):
    models_ready()
    call = get_call(call_id)
    authorize_guest(request, call)
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


@app.post("/api/calls/{call_id}/audio")
async def audio_turn(call_id: str, request: Request):
    models_ready()
    if not app.state.voice_ready:
        raise HTTPException(503, "Voice is unavailable. Use the text composer.")
    call = get_call(call_id)
    authorize_guest(request, call)
    if call["status"] != "ACTIVE" or call.get("busy"):
        raise HTTPException(409, "Call is pending, ended or already processing")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in voice.FORMATS:
        raise HTTPException(415, "Use a supported microphone recording or the text composer")
    source = request.headers.get("x-callback-audio-source", "microphone")
    if source not in {"microphone", "synthetic_stock"}:
        raise HTTPException(400, "Unrecognized audio source")
    call["busy"] = True
    engine = app.state.engine
    inference = app.state.inference
    started = time.monotonic()
    timing = {"source": source, "started_at": datetime.now(UTC).isoformat()}
    call.setdefault("voice_turns", []).append(timing)
    try:
        normalized = await voice.normalize(await request.body(), content_type)
        timing["normalize_seconds"] = round(time.monotonic() - started, 3)
        transcript, observation = await voice.transcribe(inference, normalized)
        timing["stt"] = observation
        first = len(call["transcript"])
        if call["status"] != "ACTIVE":
            raise HTTPException(409, "Call ended during transcription")
        await engine.turn(call_id, transcript)
        timing["before_tts_seconds"] = round(time.monotonic() - started, 3)
        replies = [entry["text"] for entry in call["transcript"][first:] if entry["role"] == "assistant"]
        reply = replies[-1] if replies else None
        if call["status"] == "AWAITING_DEVICE":
            reply = "The exact proposal is ready for review on the registered device. Production is unchanged."
        elif not reply:
            reply = "Check the call transcript and status for the result."
        try:
            audio, observation = await voice.synthesize(inference, redact(reply)[:450])
        except (InferenceError, BudgetExceeded, httpx.HTTPError, ValueError, TypeError, EOFError) as exc:
            timing["tts_error"] = type(exc).__name__
            return Response(status_code=204)
        timing["tts"] = observation
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
    except BudgetExceeded as exc:
        timing["error"] = type(exc).__name__
        raise HTTPException(429, "Daily inference budget reached") from exc
    except (InferenceError, httpx.HTTPError, ValueError, TypeError, TimeoutError, EOFError, OSError) as exc:
        timing["error"] = type(exc).__name__
        raise HTTPException(422, "Could not process this clip. Try a shorter recording or type the request.") from exc
    finally:
        timing["server_seconds"] = round(time.monotonic() - started, 3)
        call["busy"] = False
        engine.save(call)


@app.post("/api/calls/{call_id}/cancel")
async def cancel(call_id: str, request: Request):
    call = get_call(call_id)
    authorize_guest(request, call)
    if call["status"] not in {"ACTIVE", "AWAITING_DEVICE", "AWAITING_APPROVER"}:
        return app.state.engine.public(call)
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
    # Preserve the signed original and store a separate retargeted variant.
    target = next(u for u in call["seed_state"]["users"].values() if u["username"] == "dana.whitfield")
    old_target = deepcopy(body["change_set"]["effects"][0]["target"])
    body["change_set"]["effects"][0]["target"] = {"user_id": target["id"], "username": target["username"]}
    if old_target == body["change_set"]["effects"][0]["target"]:
        body["change_set"]["seed_version"] += "-tampered"
    call["tampered_change_set"] = deepcopy(body["change_set"])
    demonstration = {"field": "effects[0].target", "before": old_target,
        "after": body["change_set"]["effects"][0]["target"], "signed_hash_unchanged": True}
    response = await app.state.engine.executor.post("/apply", json=body)
    response.raise_for_status()
    result = response.json()
    verify(app.state.engine.public_key, result["receipt"]["payload"], result["receipt"]["signature"])
    result["demonstration"] = demonstration
    call.setdefault("tamper_results", []).append(result["receipt"])
    app.state.engine.save(call)
    return result


@app.post("/api/operator/jobs", status_code=202)
async def operator_job(body: OperatorProof):
    from services.common.contracts import original
    from services.common.crypto import digest
    from services.control.containment import run_containment
    engine = app.state.engine
    proof = original(body)
    response = await engine.executor.post("/operator/verify", json=proof)
    if response.is_error:
        raise HTTPException(403, "Pinned operator signature and realm scope are required")
    payload = proof["payload"]
    root = engine.root / "operator-jobs"
    root.mkdir(exist_ok=True)
    path = root / (payload["nonce"] + ".json")
    async with app.state.creation_lock:
        if path.exists():
            existing = json.loads(path.read_text())
            if existing["request_hash"] != digest(payload):
                raise HTTPException(409, "This operator nonce belongs to another request")
            return existing
        jobs = [json.loads(p.read_text()) for p in root.glob("*.json")]
        if any(j["status"] == "RUNNING" for j in jobs):
            raise HTTPException(409, "An operator containment test is already running")
        if sum(not c.get("destroy_proof") or bool(c.get("busy")) for c in engine.calls.values()) >= 3:
            raise HTTPException(429, "Three calls are already active")
        if payload["action"] == "hostile_replay":
            models_ready()
        job = {"job_id": payload["nonce"], "action": payload["action"], "realm": payload["realm"],
            "operator": payload["approver_id"], "status": "RUNNING", "call_id": None,
            "request_hash": digest(payload), "created_at": datetime.now(UTC).isoformat(),
            "workload_origin": "operator_scripted_fault", "planner_generated": False, "signed_request": proof,
            "stage": "WAITING_FOR_TWIN"}
        def save_job():
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(job))
            temporary.chmod(0o600)
            temporary.replace(path)
        save_job()
    def progress(identifier):
        job["stage"] = "EXECUTING"
        job["call_id"] = identifier
        save_job()
    async def execute_job():
        try:
            for attempt in range(51):
                try:
                    if payload["action"] == "hostile_replay":
                        result = await replay_hostile(engine, payload["realm"], on_created=progress)
                    else:
                        result = await run_containment(engine, payload["action"], payload["realm"], progress)
                    break
                except httpx.HTTPStatusError as exc:
                    if job["call_id"] is not None or exc.response.status_code not in {425, 503} or attempt == 50:
                        raise
                    await asyncio.sleep(3)
            job["result_status"] = result["status"]
            job["status"] = "FINISHED"
        except Exception as exc:
            job["status"] = "FAILED"
            job["error"] = "Operator workload failed: " + type(exc).__name__
        finally:
            save_job()
    task = asyncio.create_task(execute_job())
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return job


@app.get("/api/operator/jobs/{identifier}")
def read_operator_job(identifier: str):
    if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
        raise HTTPException(404)
    path = app.state.engine.root / "operator-jobs" / (identifier + ".json")
    if not path.exists():
        raise HTTPException(404)
    return json.loads(path.read_text())


@app.get("/api/demo")
def demo_manifest():
    path = Path(app.state.config["directory_path"]).parent / "demo_manifest.json"
    if not path.exists():
        raise HTTPException(503, "Verified demo executions have not been selected yet")
    manifest = json.loads(path.read_text())
    if any(beat["call_id"] not in app.state.engine.calls for beat in manifest["beats"]):
        raise HTTPException(503, "Recorded demo evidence is unavailable")
    return manifest


@app.get("/api/benchmark/latest")
def benchmark_latest():
    path = Path(app.state.config["directory_path"]).parent.parent / "bench/results/latest.json"
    if not path.exists():
        raise HTTPException(404, "No completed benchmark has been published")
    return json.loads(path.read_text())
