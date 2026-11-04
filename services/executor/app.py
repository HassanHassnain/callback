"""Executor P2 service: signed seed export and public verification key."""

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

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


async def export_loop(config):
    global LAST_EXPORT, LAST_ERROR
    while True:
        try:
            LAST_EXPORT = await asyncio.to_thread(export_once, config)
            LAST_ERROR = None
            print("Signed scrubbed seeds exported for both realms", flush=True)
        except Exception as exc:
            LAST_ERROR = type(exc).__name__
            print("Seed export failed: " + LAST_ERROR, flush=True)
        await asyncio.sleep(120)


@asynccontextmanager
async def lifespan(app):
    app.state.config = config_from_file(os.environ.get("EXECUTOR_CONFIG_PATH", "/run/callback/config.json"))
    app.state.signing_key = load_or_create_key(Path(app.state.config["signing_key_path"]))
    task = asyncio.create_task(export_loop(app.state.config))
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
            "phase": "P2", "last_export": LAST_EXPORT, "last_error_type": LAST_ERROR,
            "apply_ready": False}


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


@app.post("/apply")
def apply_not_ready():
    raise HTTPException(501, "Production apply is not implemented until P5")
