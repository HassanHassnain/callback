"""Stage the two real-phone P5 requests without signing any device decision."""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state  # noqa: E402


def main():
    state = load_state()
    client = httpx.Client(base_url=state["public_url"], timeout=150)
    private = ROOT / ".local/real-phone"
    private.mkdir(exist_ok=True)
    pointer = private / "active.json"
    active = json.loads(pointer.read_text()) if pointer.exists() else {}
    for name in ["sam_reset", "dana_lost_phone"]:
        fixture = yaml.safe_load((ROOT / "fixtures/scripted_calls" / (name + ".yaml")).read_text())
        call = None
        if name in active:
            response = client.get("/api/calls/" + active[name])
            if response.is_success:
                previous = response.json()
                if previous["status"] in {"ACTIVE", "AWAITING_DEVICE", "AWAITING_APPROVER", "APPLIED_VERIFIED", "DENIED"}:
                    call = previous
        if call is None:
            for _ in range(50):
                response = client.post("/api/calls", json={"realm": "acme"})
                if response.status_code in {425, 429, 503}:
                    time.sleep(4)
                    continue
                response.raise_for_status()
                call = response.json()
                break
            else:
                raise RuntimeError("Fresh signed-seed twin is still unavailable")
            active[name] = call["call_id"]
            pointer.write_text(json.dumps(active))
            pointer.chmod(0o600)
        print(name, call["call_id"], call["status"], flush=True)
        sent = sum(t["role"] == "user" for t in call["transcript"])
        for text in fixture["messages"][sent:]:
            if call["status"] != "ACTIVE":
                break
            response = client.post("/api/calls/" + call["call_id"] + "/turn", json={"text": text})
            response.raise_for_status()
            for _ in range(240):
                time.sleep(1)
                response = client.get("/api/calls/" + call["call_id"])
                response.raise_for_status()
                call = response.json()
                if not call.get("busy"):
                    break
            print(name, call["status"], [e["type"] for e in call["effects"]], call.get("policy"), flush=True)
        raw = private / (call["call_id"] + ".json")
        raw.write_text(json.dumps(call))
        raw.chmod(0o600)
        report = {"observed_at": datetime.now(UTC).isoformat(), "acceptance": "Staging only; real phone decisions still required",
            "device": "Hassan's registered physical phone; no simulated signer", "fixture": name,
            "call": {k: call.get(k) for k in ["call_id", "realm", "status", "effects", "policy", "model_calls",
                "change_set_hash", "destroy_proof", "production_status"]}}
        path = ROOT / "docs/infra" / ("P5-real-phone-stage-" + name + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
        path.write_text(json.dumps(report, indent=2) + "\n")
        if call["status"] not in {"AWAITING_DEVICE", "AWAITING_APPROVER", "APPLIED_VERIFIED", "DENIED"}:
            raise RuntimeError("Request did not reach real-device confirmation; inspect preserved evidence")
    print("Real-phone requests ready:", json.dumps(active), flush=True)


if __name__ == "__main__":
    main()
