"""Fixed operator tests. Every command runs only in a task-owned gVisor twin."""

import json
import uuid

from services.control.engine import now

WORKLOADS = {
    "fork_limit": ("python", """import os,time,json
children=[]
try:
 for n in range(2000):
  pid=os.fork()
  if pid==0:time.sleep(5);os._exit(0)
  children.append(pid)
except OSError as e:print(json.dumps(dict(fork_blocked=True,children=len(children),errno=e.errno)),flush=True)
for pid in children:
 try:os.waitpid(pid,0)
 except ChildProcessError:pass"""),
    "memory_limit": ("python", "x=[]\nwhile True:x.append(bytearray(64*1024*1024))"),
    "filesystem": ("bash", "rm -rf / --no-preserve-root >/tmp/rm-errors 2>&1"),
}


async def run_containment(engine, action, realm, progress):
    call = engine.calls[(await engine.create(realm))["call_id"]]
    call["busy"] = True
    progress(call["call_id"])
    call["workload_origin"] = "operator_containment_test"
    call["operator_action"] = action
    call["transcript"].append({"role": "operator", "ts": now(),
        "text": "Operator-scripted containment test: " + action + ". No planner generated this workload. No production apply is requested."})
    host_before = await engine.sandbox.request("GET", "/host-health")
    try:
        language, code = WORKLOADS[action]
        log = {"id": "operator-" + str(uuid.uuid4()), "name": "fixed_containment_test", "arguments": {"action": action},
            "origin": "operator_containment_test", "started_at": now()}
        call["tool_log"].append(log)
        engine.save(call)
        result = await engine.sandbox.exec(call["twin"]["twin_id"], language, code)
        log.update({"result": result, "finished_at": now()})
        await engine.refresh(call)
        host_after = await engine.sandbox.request("GET", "/host-health")
        checks = {"host_alive_before": host_before["driver_alive"], "host_alive_after": host_after["driver_alive"]}
        if action == "fork_limit":
            observed = json.loads(result["output"].splitlines()[0])
            checks["fork_limit_enforced"] = observed.get("fork_blocked") is True and observed["children"] < call["twin"]["limits"]["pids_limit"]
        elif action == "memory_limit":
            checks["memory_limit_enforced"] = result["exit_code"] in {137, -9} or bool((call["twin"].get("container_state") or {}).get("OOMKilled"))
        else:
            # UID 1100 can destroy its own writable guest paths. The receipt
            # proves host survival and destruction; it does not claim an
            # integrity check on every host file.
            checks["workload_executed"] = "exit_code" in result
        call["containment_result"] = {"action": action, "checks": checks, "execution": result,
                                      "planner_generated": False, "production_apply_requested": False}
        call["status"] = "CONTAINMENT_VERIFIED" if all(checks.values()) else "CONTAINMENT_FAILED"
    except Exception as exc:
        call["status"] = "CONTAINMENT_FAILED"
        call["error"] = "Fixed containment workload failed: " + type(exc).__name__
    finally:
        await engine.destroy_twin(call)
        if "containment_result" in call:
            call["containment_result"]["checks"]["destroyed"] = bool(call.get("destroy_proof"))
        call["busy"] = False
        await engine.record_closed_call(call)
        engine.save(call)
    return engine.public(call)
