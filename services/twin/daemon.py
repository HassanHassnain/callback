"""Trusted sandbox-host driver. Agent code runs only through fixed docker exec argv."""

import asyncio
import base64
import contextlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.common.crypto import verify
from services.egress.guard import EgressGuard

CONFIG = json.loads(Path(os.environ.get("SANDBOX_CONFIG", "/opt/callback/sandbox-private/config.json")).read_text())
RECORDS = {}
SEEDS = {}
EVENTS = []
LOCKS = {}
POOL_TASKS = set()
INTENTS = {}
PRIVATE = Path(os.environ.get("SANDBOX_CONFIG", "/opt/callback/sandbox-private/config.json")).parent


def persist():
    path = PRIVATE / "twins.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(RECORDS))
    temporary.chmod(0o600)
    temporary.replace(path)


def persist_intents():
    path = PRIVATE / "creation-intents.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(INTENTS))
    temporary.chmod(0o600)
    temporary.replace(path)


def stamp():
    return datetime.now(UTC).isoformat()


async def docker(*args, timeout=30, stdin=None, max_output=2_000_000):
    process = await asyncio.create_subprocess_exec("docker", *args, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output = bytearray()
    truncated = False

    async def collect():
        nonlocal truncated
        while chunk := await process.stdout.read(4096):
            available = max_output - len(output)
            output.extend(chunk[:max(0, available)])
            if len(chunk) > available:
                truncated = True
                process.kill()
                break

    if stdin is not None:
        process.stdin.write(stdin)
        await process.stdin.drain()
    process.stdin.close()
    try:
        await asyncio.wait_for(asyncio.gather(collect(), process.wait()), timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise
    return process.returncode, bytes(output), truncated


async def inspect(container):
    code, output, _ = await docker("inspect", container)
    if code == 0:
        return json.loads(output)[0]
    if b"no such object:" in output.lower() or b"no such container:" in output.lower():
        return None
    raise RuntimeError("Docker inspection failed without proving absence")


def event(twin, kind, **fields):
    item = {"ts": stamp(), "twin_id": twin, "kind": kind, **fields}
    EVENTS.append(item)
    with (PRIVATE / "events.jsonl").open("a") as log:
        log.write(json.dumps(item) + "\n")
    if len(EVENTS) > 5000:
        del EVENTS[:1000]


def owner_for_ip(ip):
    return next((key for key, value in reversed(list(RECORDS.items())) if value.get("ip") == ip
                 and not value.get("destroyed_at") and value["status"] in {"READY", "BOOTING"}), None)


async def owned(twin):
    record = RECORDS.get(twin)
    if not record:
        raise HTTPException(404, "Unknown task-owned twin")
    data = await inspect(record["container_id"])
    if data and data["Config"].get("Labels", {}).get("callback.owner") != CONFIG["owner_id"]:
        raise RuntimeError("Live container ownership mismatch; refusing mutation")
    return record, data


async def kill(twin, reason):
    record, data = await owned(twin)
    record["status"] = reason
    if data and data["State"]["Running"]:
        await docker("kill", record["container_id"])
    record["killed_at"] = stamp()
    persist()
    return record


async def destroy(twin):
    record, data = await owned(twin)
    if data:
        if data["State"]["Running"]:
            await kill(twin, "DESTROYING")
        code, output, _ = await docker("rm", "-f", record["container_id"])
        if code:
            raise RuntimeError("Owned twin removal failed")
    if await inspect(record["container_id"]) is not None:
        raise RuntimeError("Container still exists after removal")
    record.update({"destroyed_at": stamp(), "status": "DESTROYED",
        "destroy_proof": {"docker_inspect": "No such container", "observed_at": stamp(),
                          "container_id": record["container_id"]}})
    persist()
    return safe(record)


async def canary(text, source, channel):
    lowered = text.lower()
    for twin, record in list(RECORDS.items()):
        if record.get("destroyed_at") or record.get("status") == "COMPROMISED":
            continue
        if any(token in lowered for token in record["canaries"]):
            started = time.monotonic()
            await kill(twin, "COMPROMISED")
            latency = time.monotonic() - started
            record["tripwire_latency_seconds"] = latency
            event(twin, "TRIPWIRE", channel=channel, source_twin=source,
                  kill_latency_seconds=latency, canary_matched=True)
            persist()
            # Kill is the latency boundary; then remove the owned container.
            await destroy(twin)
            record["status"] = "COMPROMISED"
            persist()
            return True
    return False


def safe(record):
    return {key: value for key, value in record.items()
            if key not in {"canaries", "admin_password", "snapshot", "initial_snapshot"}}


async def snapshot(twin):
    record, data = await owned(twin)
    if not data or not data["State"]["Running"]:
        return {"state": record.get("snapshot"), "quality": "last_successful_before_kill", "complete": False}
    code, output, truncated = await docker("exec", "--user", "0:0", record["container_id"],
        "python3", "/opt/callback/tools.py", "snapshot", timeout=30)
    if code or truncated:
        raise RuntimeError("Twin state snapshot failed")
    record["snapshot"] = json.loads(output)
    return {"state": record["snapshot"], "quality": "live", "complete": True}


async def create(envelope, pooled=False):
    seed = envelope["payload"]
    verify(CONFIG["executor_public_key"], seed, envelope["signature"])
    if seed["realm"] not in {"acme", "acme-guest"} or seed.get("scrubbed") is not True:
        raise HTTPException(400, "Invalid scrubbed seed")
    twin = str(uuid.uuid4())
    canaries = ["cbcanary" + secrets.token_hex(18) for _ in range(2)]
    password = secrets.token_urlsafe(32)
    started = time.monotonic()
    INTENTS[twin] = {"name": "cb-twin-" + twin, "issued_at": stamp(), "realm": seed["realm"],
                     "owner_id": CONFIG["owner_id"]}
    persist_intents()
    args = ["run", "-d", "--name", "cb-twin-" + twin, "--runtime=runsc", "--network=twinnet",
        "--cpus=2", "--memory=1536m", "--pids-limit=512", "--ulimit", "nproc=128:128",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", "--user=1100:1100",
        "--label", "callback.owner=" + CONFIG["owner_id"], "--label", "callback.twin=" + twin,
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,uid=1100,gid=1100,mode=1777",
        "--tmpfs", "/tmp/callback:rw,nosuid,nodev,size=16m,uid=1000,gid=1000,mode=0755",
        "--tmpfs", "/tmp/callback/work:rw,nosuid,nodev,size=64m,uid=1100,gid=1100,mode=0700",
        "--tmpfs", "/audit:rw,nosuid,nodev,noexec,size=1m,uid=0,gid=0,mode=0700",
        "--tmpfs", "/opt/keycloak/data:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700",
        "--tmpfs", "/home/twin:rw,nosuid,nodev,size=32m,uid=1100,gid=1100",
        "--tmpfs", "/run/secrets:rw,nosuid,nodev,noexec,size=1m,uid=1100,gid=1100",
        "--dns=172.30.0.1", "-e", "HTTP_PROXY=http://172.30.0.1:3128",
        "-e", "HTTPS_PROXY=http://172.30.0.1:3128", "-e", "NO_PROXY=localhost,127.0.0.1",
        "-e", "PROD_KEYCLOAK_TOKEN=" + canaries[1], CONFIG["image"]]
    code, output, _ = await docker(*args, timeout=60)
    if code:
        raise RuntimeError("Twin container creation failed: " + output.decode()[:500])
    container = output.decode().strip().splitlines()[-1]
    if not re.fullmatch("[a-f0-9]{64}", container):
        raise RuntimeError("Unexpected Docker container ID")
    record = {"twin_id": twin, "container_id": container, "realm": seed["realm"],
        "seed_version": seed["version"], "prod_state_digest": seed["prod_state_digest"],
        "created_at": stamp(), "expires_monotonic": time.monotonic() + 900,
        "status": "BOOTING", "canaries": canaries, "pooled": pooled, "claimed": not pooled}
    RECORDS[twin] = record
    LOCKS[twin] = asyncio.Lock()
    persist()
    INTENTS.pop(twin)
    persist_intents()
    try:
        # Docker's own resolver file is configured before any agent code runs.
        # This is a fixed command, not caller/agent-supplied host execution.
        config = {"realm": seed["realm"], "realm_import": seed["realm_import"],
                  "admin_password": password, "file_canary": canaries[0]}
        script = ("import pathlib,sys,json,os\nc=json.load(sys.stdin);os.umask(0o077)\n"
                  "pathlib.Path('/audit/credentials.json').write_text(json.dumps(dict(username='callback-twin',password=c['admin_password'],realm=c['realm'])))\n")
        code, delivery_output, _ = await docker("exec", "-i", "--user", "0:0", container,
            "python3", "-c", script, stdin=json.dumps(config).encode(), timeout=30)
        if code:
            raise RuntimeError("Twin audit delivery failed: " + delivery_output.decode()[-1000:])
        script = ("import pathlib,sys,os\nos.umask(0o077)\n"
                  "pathlib.Path('/tmp/callback/server-bootstrap.json').write_bytes(sys.stdin.buffer.read())\n")
        code, output, _ = await docker("exec", "-i", "--user", "1000:1000", container,
            "python3", "-c", script, stdin=json.dumps(config).encode(), timeout=30)
        if code:
            raise RuntimeError("Twin server config delivery failed: " + output.decode()[-1000:])
        script = "import pathlib,sys;pathlib.Path('/run/secrets/prod_admin_token').write_text(sys.stdin.read())"
        code, _, _ = await docker("exec", "-i", "--user", "1100:1100", container,
            "python3", "-c", script, stdin=canaries[0].encode())
        if code:
            raise RuntimeError("Twin canary delivery failed")
        code, _, _ = await docker("exec", "-d", "--user", "1000:1000", container,
                                  "python3", "/opt/callback/server.py", timeout=10)
        if code:
            raise RuntimeError("Twin server launch failed")
        for _ in range(480):
            data = await inspect(container)
            if not data or not data["State"]["Running"]:
                raise RuntimeError("Twin exited during boot")
            record["ip"] = data["NetworkSettings"]["Networks"]["twinnet"]["IPAddress"]
            code, _, _ = await docker("exec", "--user", "0:0", container, "test", "-f", "/tmp/callback/server-ready", timeout=10)
            if code == 0:
                code, _, _ = await docker("exec", "--user", "1100:1100", container,
                    "/opt/keycloak/bin/kcadm.sh", "config", "credentials", "--server", "http://127.0.0.1:8080",
                    "--realm", "master", "--user", "callback-twin", "--password", password, timeout=30)
                if code:
                    raise RuntimeError("Twin-only tool credential setup failed")
                record["status"] = "READY"
                record["boot_seconds"] = time.monotonic() - started
                record["image_digest"] = data["Image"]
                record["limits"] = {"runtime": data["HostConfig"]["Runtime"],
                    "memory_bytes": data["HostConfig"]["Memory"], "nano_cpus": data["HostConfig"]["NanoCpus"],
                    "pids_limit": data["HostConfig"]["PidsLimit"], "read_only_root": data["HostConfig"]["ReadonlyRootfs"],
                    "cap_drop": data["HostConfig"]["CapDrop"], "binds": data["HostConfig"].get("Binds")}
                record["limits"]["ulimits"] = data["HostConfig"]["Ulimits"]
                record["initial_snapshot"] = (await snapshot(twin))["state"]
                persist()
                event(twin, "READY", boot_seconds=record["boot_seconds"])
                return safe(record)
            await asyncio.sleep(0.5)
        raise RuntimeError("Twin boot exceeded 240 seconds")
    except Exception as exc:
        _, logs, _ = await docker("exec", "--user", "0:0", container,
                                  "tail", "-n", "40", "/tmp/callback/server.log", max_output=8000)
        # Log only startup diagnostics, never the bootstrap configuration.
        event(twin, "BOOT_FAILED", error=type(exc).__name__, server_log=logs.decode(errors="replace"))
        await destroy(twin)
        raise


async def execute(twin, language, code):
    async with LOCKS[twin]:
        record, data = await owned(twin)
        if record.get("frozen"):
            raise HTTPException(409, "Twin is frozen for confirmation")
        if not data or not data["State"]["Running"] or record["status"] == "COMPROMISED":
            raise HTTPException(409, "Twin is unavailable")
        command = ["bash", "-lc", code] if language == "bash" else ["python3", "-c", code]
        try:
            exit_code, output, truncated = await docker("exec", "--user", "1100:1100",
                record["container_id"], *command, timeout=30, max_output=16384)
            if truncated:
                await kill(twin, "OUTPUT_LIMIT")
            elif record["status"] != "COMPROMISED":
                latest = await inspect(record["container_id"])
                if not latest or not latest["State"]["Running"]:
                    record["status"] = "EXITED"
                    persist()
                else:
                    with contextlib.suppress(Exception):
                        await snapshot(twin)
            if record["status"] == "COMPROMISED":
                # Guest exec exits as soon as kill lands; finish the tripwire's
                # event/removal before reporting a terminal result to control.
                for _ in range(200):
                    if record.get("destroyed_at"):
                        break
                    await asyncio.sleep(0.01)
            return {"exit_code": exit_code, "output": output.decode(errors="replace"),
                    "output_truncated": truncated, "status": record["status"]}
        except asyncio.TimeoutError:
            await kill(twin, "EXEC_TIMEOUT")
            return {"exit_code": 124, "output": "30-second exec timeout; twin killed",
                    "status": record["status"]}


async def maintenance():
    while True:
        for twin, record in list(RECORDS.items()):
            if not record.get("destroyed_at") and time.monotonic() > record["expires_monotonic"]:
                await destroy(twin)
        for realm, envelope in list(SEEDS.items()):
            version = envelope["payload"]["version"]
            current = [r for r in RECORDS.values() if r["realm"] == realm and r["pooled"]
                       and not r["claimed"] and not r.get("destroyed_at")
                       and r["seed_version"] == version and r["status"] in {"READY", "BOOTING"}]
            target = CONFIG.get("pool_per_realm", {}).get(realm, 0)
            if len(current) < target and not POOL_TASKS:
                task = asyncio.create_task(create(envelope, pooled=True))
                POOL_TASKS.add(task)
                task.add_done_callback(pool_finished)
            if sum(r["status"] == "READY" for r in current) >= target:
                for twin, record in list(RECORDS.items()):
                    if (record["realm"] == realm and record["pooled"] and not record["claimed"]
                            and not record.get("destroyed_at") and record["seed_version"] != version):
                        await destroy(twin)
        await asyncio.sleep(2)


def pool_finished(task):
    POOL_TASKS.discard(task)
    if not task.cancelled() and task.exception():
        event(None, "POOL_BOOT_FAILED", error=str(task.exception())[:1800])
        # Avoid a failed boot spinning up disposable containers every two seconds.
        CONFIG["pool_per_realm"] = {}


@asynccontextmanager
async def lifespan(app):
    if (PRIVATE / "creation-intents.json").exists():
        INTENTS.update(json.loads((PRIVATE / "creation-intents.json").read_text()))
    if (PRIVATE / "twins.json").exists():
        RECORDS.update(json.loads((PRIVATE / "twins.json").read_text()))
        for twin, record in RECORDS.items():
            LOCKS[twin] = asyncio.Lock()
            # Restart is a fail-closed lifecycle boundary. Only persisted,
            # label-verified resources belonging to this task are removed.
            if not record.get("destroyed_at"):
                await destroy(twin)
    for twin, intent in list(INTENTS.items()):
        data = await inspect(intent["name"])
        if data and twin not in RECORDS:
            labels = data["Config"].get("Labels", {})
            created = datetime.fromisoformat(data["Created"].replace("Z", "+00:00"))
            issued = datetime.fromisoformat(intent["issued_at"])
            if (intent["owner_id"] != CONFIG["owner_id"] or labels.get("callback.owner") != CONFIG["owner_id"]
                    or labels.get("callback.twin") != twin or data["Name"] != "/" + intent["name"] or created < issued):
                raise RuntimeError("Pending creation ownership mismatch; preserving container")
            RECORDS[twin] = {"twin_id": twin, "container_id": data["Id"], "realm": intent["realm"],
                "created_at": intent["issued_at"], "status": "RECOVERED_PENDING_CREATE", "canaries": [],
                "pooled": False, "claimed": True, "expires_monotonic": time.monotonic()}
            LOCKS[twin] = asyncio.Lock()
            persist()
            await destroy(twin)
        INTENTS.pop(twin)
        persist_intents()
    if (PRIVATE / "seeds.json").exists():
        SEEDS.update(json.loads((PRIVATE / "seeds.json").read_text()))
    guard = EgressGuard(CONFIG["attacker_domain"], CONFIG["control_ip"], owner_for_ip, canary, event)
    server, dns, dns_tcp = await guard.start()
    gc = asyncio.create_task(maintenance())
    try:
        yield
    finally:
        gc.cancel()
        server.close()
        dns.close()
        dns_tcp.close()
        await guard.client.aclose()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    authorization = request.headers.get("authorization", "")
    if not hmac.compare_digest(authorization, "Bearer " + CONFIG["api_secret"]):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if int(request.headers.get("content-length", "0")) > 2_000_000:
        return JSONResponse({"error": "Request too large"}, status_code=413)
    return await call_next(request)


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    envelope: dict
    pooled: bool = False


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(pattern="^(bash|python)$")
    code: str = Field(max_length=128000)


class SeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    envelope: dict


class PoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acme: int = Field(ge=0, le=3)
    acme_guest: int = Field(default=0, ge=0, le=1)


@app.post("/pool")
async def set_pool(body: PoolRequest):
    CONFIG["pool_per_realm"] = {"acme": body.acme, "acme-guest": body.acme_guest}
    path = PRIVATE / "config.json"
    path.write_text(json.dumps(CONFIG))
    path.chmod(0o600)
    return CONFIG["pool_per_realm"]


@app.post("/seeds")
async def update_seed(body: SeedRequest):
    seed = body.envelope["payload"]
    verify(CONFIG["executor_public_key"], seed, body.envelope["signature"])
    if seed.get("realm") not in {"acme", "acme-guest"} or seed.get("scrubbed") is not True:
        raise HTTPException(400, "Invalid scrubbed seed")
    SEEDS[seed["realm"]] = body.envelope
    path = PRIVATE / "seeds.json"
    path.write_text(json.dumps(SEEDS))
    path.chmod(0o600)
    return {"realm": seed["realm"], "version": seed["version"]}


@app.post("/claim/{realm}")
async def claim(realm: str):
    version = SEEDS.get(realm, {}).get("payload", {}).get("version")
    for record in RECORDS.values():
        if (record["realm"] == realm and record["status"] == "READY" and not record["claimed"]
                and record["seed_version"] == version):
            record["claimed"] = True
            record["claimed_at"] = stamp()
            persist()
            return {**safe(record), "initial_snapshot": record["initial_snapshot"]}
    raise HTTPException(425, "Latest-seed twin is still warming; retry shortly")


@app.post("/fresh/{realm}")
async def fresh(realm: str):
    if realm not in SEEDS:
        raise HTTPException(404, "No signed seed")
    return await create(SEEDS[realm])


@app.get("/health")
def health():
    return {"status": "ok", "twins": [safe(r) for r in RECORDS.values() if not r.get("destroyed_at")],
            "ready": sum(r["status"] == "READY" and not r["claimed"] for r in RECORDS.values())}


@app.get("/events")
def events():
    return EVENTS


@app.get("/host-health")
def host_health():
    info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {"uptime_seconds": float(Path("/proc/uptime").read_text().split()[0]),
            "memory_available_kib": int(info["MemAvailable"].split()[0]), "driver_alive": True}


@app.post("/create")
async def create_twin(body: CreateRequest):
    return await create(body.envelope, body.pooled)


@app.post("/twins/{twin}/exec")
async def exec_twin(twin: str, body: ExecRequest):
    await owned(twin)
    return await execute(twin, body.language, body.code)


@app.get("/twins/{twin}/snapshot")
async def get_snapshot(twin: str):
    return await snapshot(twin)


@app.post("/twins/{twin}/freeze")
async def freeze(twin: str):
    async with LOCKS[twin]:
        result = await snapshot(twin)
        if not result["complete"]:
            raise HTTPException(409, "Cannot confirm incomplete state")
        RECORDS[twin]["frozen"] = True
        return result


@app.post("/twins/{twin}/kill")
async def kill_twin(twin: str):
    return safe(await kill(twin, "KILLED"))


@app.post("/twins/{twin}/destroy")
async def destroy_twin(twin: str):
    return await destroy(twin)


@app.get("/twins/{twin}")
async def get_twin(twin: str):
    record, data = await owned(twin)
    return {**safe(record), "running": bool(data and data["State"]["Running"]),
            "container_state": {key: data["State"].get(key) for key in ["Running", "OOMKilled", "ExitCode"]} if data else None}


@app.get("/twins/{twin}/prove_destroyed")
async def prove_destroyed(twin: str):
    record, data = await owned(twin)
    if data is not None:
        raise HTTPException(409, "Twin still exists")
    return {"docker_inspect": "No such container", "container_id": record["container_id"], "observed_at": stamp()}


@app.get("/twins/{twin}/screenshots/{identifier}")
async def screenshot(twin: str, identifier: str):
    record, _ = await owned(twin)
    if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
        raise HTTPException(400, "Invalid screenshot ID")
    code, output, truncated = await docker("exec", "--user", "1100:1100", record["container_id"],
        "cat", "/tmp/callback/work/" + identifier + ".png", max_output=2_000_000)
    if code or truncated:
        raise HTTPException(404, "Screenshot unavailable")
    return {"content_type": "image/png", "base64": base64.b64encode(output).decode()}
