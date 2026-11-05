"""Executor P2 service: signed seed export and public verification key."""

import asyncio
import contextlib
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from services.common.contracts import ApplyRequest
from services.executor.apply import ApplyService
from services.executor.enrollment import validate_bundle
from services.executor.verify import Refusal, registered
from services.common.crypto import load_or_create_key, public_jwk
from services.executor.keycloak import Keycloak, config_from_file
from services.executor.seed_export import export_all

LAST_EXPORT = []
LAST_ERROR = None


def export_once(config):
    kc = Keycloak(config)
    try:
        return export_all(kc, config)
    finally:
        kc.client.close()


async def export_loop(config, service):
    global LAST_EXPORT, LAST_ERROR
    while True:
        try:
            LAST_EXPORT = await asyncio.to_thread(export_once, config)
            LAST_ERROR = None
            await asyncio.to_thread(service.flush_receipts)
            print("Signed scrubbed seeds exported for both realms", flush=True)
        except Exception as exc:
            LAST_ERROR = type(exc).__name__
            print("Seed export failed: " + LAST_ERROR, flush=True)
        await asyncio.sleep(120)


@asynccontextmanager
async def lifespan(app):
    app.state.config = config_from_file(os.environ.get("EXECUTOR_CONFIG_PATH", "/run/callback/config.json"))
    app.state.signing_key = load_or_create_key(Path(app.state.config["signing_key_path"]))
    app.state.apply = ApplyService(app.state.config, app.state.signing_key)
    task = asyncio.create_task(export_loop(app.state.config, app.state.apply))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Callback executor", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok" if LAST_EXPORT and LAST_ERROR is None else "initializing",
            "phase": "P5", "last_export": LAST_EXPORT, "last_error_type": LAST_ERROR,
            "apply_ready": True}


@app.get("/executor-pubkey.json")
def executor_pubkey():
    return public_jwk(app.state.signing_key)


@app.get("/seeds/latest/{realm}")
def latest_seed(realm: str):
    if realm not in app.state.config["realms"]:
        raise HTTPException(404, "Unknown realm")
    path = Path(f"/run/callback/latest-{realm}.json")
    if not path.exists():
        raise HTTPException(503, "Seed export is not ready")
    return json.loads(path.read_text())


@app.middleware("http")
async def bounded(request: Request, call_next):
    if request.method == "POST":
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > 256000 or request.headers.get("transfer-encoding"):
            return JSONResponse({"detail": "A bounded body of at most 256 KB is required"}, status_code=413)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def invalid_body(request, exc):
    # FastAPI's default validation response echoes input. Never reflect untrusted
    # material into receipts, logs or control responses.
    return JSONResponse({"detail": "Invalid typed executor request"}, status_code=422)


@app.exception_handler(Refusal)
async def refused(request, exc):
    return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=403)


@app.post("/apply")
def apply(body: ApplyRequest):
    return app.state.apply.apply(body)


class Proof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict
    signature: str


@app.post("/delivery")
def delivery(body: Proof):
    try:
        return app.state.apply.delivery(body.model_dump())
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(403, "Device proof did not verify") from exc


@app.post("/enrollment/status")
def enrollment_status(body: Proof):
    payload = validate_bundle(body.model_dump(), check_time=False)
    root = Path(app.state.config["signing_key_path"]).parent
    if payload["kind"] == "approver":
        path = root / "approvers.json"
        pinned = json.loads(path.read_text()).get(payload["identity"]) if path.exists() else None
        matched = bool(pinned and pinned["public_key"] == payload["public_key"] and payload["realm"] in pinned["realms"])
    else:
        kc = Keycloak(app.state.config)
        try:
            users = kc.request("GET", payload["realm"], "users", params={"username": payload["identity"], "exact": "true"})
            try:
                matched = len(users) == 1 and registered(users[0], "device_pubkey_jwk") == payload["public_key"] and registered(
                    users[0], "device_encryption_pubkey_jwk") == payload["encryption_public_key"]
            except Refusal:
                matched = False
        finally:
            kc.client.close()
    return {"pinned": matched}


@app.get("/receipts/{identifier}")
def receipt(identifier: str):
    if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
        raise HTTPException(404)
    service = app.state.apply
    path = service.receipts / (identifier + ".json")
    if not path.exists():
        from contextlib import closing
        with closing(service.db()) as db:
            row = db.execute("SELECT receipt_id FROM executions WHERE call_id=?", (identifier,)).fetchone()
        if not row or not row[0]:
            raise HTTPException(404, "Receipt is not ready")
        path = service.receipts / (row[0] + ".json")
    return json.loads(path.read_text())


@app.post("/decisions/verify")
def decisions_verify(body: ApplyRequest):
    from services.executor.verify import validate_hash, verify_decisions
    from services.common.state import snapshot
    validate_hash(body)
    kc = Keycloak(app.state.config)
    try:
        current = snapshot(kc, body.change_set.realm)
        path = Path(app.state.config["signing_key_path"]).parent / "approvers.json"
        devices, operators, denials = verify_decisions(body, current, json.loads(path.read_text()) if path.exists() else {})
        return {"devices": sorted(devices), "approvers": sorted(operators), "denials": denials}
    finally:
        kc.client.close()
