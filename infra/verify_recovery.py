"""Crash the two task-owned services and verify their automatic recovery."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from infra.remote import load_state, ssh
from services.common.crypto import digest

ROOT = Path(__file__).resolve().parents[1]


def wait_for(test):
    started = time.monotonic()
    while time.monotonic() - started < 150:
        try:
            if test():
                return round(time.monotonic() - started, 3)
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("Owned service failed to recover within 150 seconds")


def main():
    state = load_state()
    base = state["public_url"]
    with httpx.Client(base_url=base, timeout=12) as client:
        assert client.get("/health").json()["application_ready"]
        assert not any(c["status"] in {"ACTIVE", "SUBMITTING"} for c in client.get("/api/calls").json())
        key = digest(client.get("/executor-pubkey.json").json())
        output = ssh(state, "control", """set -e
old=$(systemctl show --property MainPID --value callback-control)
test "$old" -gt 1
systemctl kill --signal=SIGKILL --kill-whom=main callback-control
for _ in $(seq 1 30); do
 new=$(systemctl show --property MainPID --value callback-control)
 if test "$new" -gt 1 && test "$new" != "$old"; then
  printf '%s %s\n' "$old" "$new"; exit 0
 fi
 sleep 1
done
exit 1
""", timeout=45)
        control_pids = [int(p) for p in output.stdout.strip().splitlines()[-1].split()]
        control_ready = wait_for(lambda: client.get("/health").json()["application_ready"])
        output = ssh(state, "executor", """set -e
cd /opt/callback
container=$(docker compose ps -q executor)
test -n "$container"
test "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$container")" = executor
test "$(docker inspect -f '{{.Config.Image}}' "$container")" = callback-executor:local
old=$(docker inspect -f '{{.State.Pid}}' "$container")
test "$old" -gt 1
kill -KILL "$old"
for _ in $(seq 1 30); do
 new=$(docker inspect -f '{{.State.Pid}}' "$container")
 if test "$new" -gt 1 && test "$new" != "$old"; then
  printf '%s %s\n' "$old" "$new"; exit 0
 fi
 sleep 1
done
exit 1
""", timeout=45)
        executor_pids = [int(p) for p in output.stdout.strip().splitlines()[-1].split()]
        executor_url = "http://" + state["resources"]["executor"]["vpc_ip"] + ":8081/health"

        def executor_ready():
            result = ssh(state, "control", "curl -fsS --max-time 4 " + executor_url, check=False, timeout=12)
            return result.returncode == 0 and json.loads(result.stdout)["status"] == "ok"

        executor_elapsed = wait_for(executor_ready)
        assert key == digest(client.get("/executor-pubkey.json").json())
        assert client.get("/api/receipts/68d87ea9-7fd0-47fe-b2c6-d2d95f6ef07d").is_success
        report = {"observed_at": datetime.now(UTC).isoformat(), "control_pids": control_pids,
                  "executor_pids": executor_pids, "control_ready_poll_seconds": control_ready,
                  "executor_ready_poll_seconds": executor_elapsed, "public_key_unchanged": True,
                  "prior_signed_receipt_available": True}
    path = ROOT / "docs/infra" / datetime.now(UTC).strftime("P9-recovery-%Y%m%dT%H%M%SZ.json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
