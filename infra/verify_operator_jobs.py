"""Public fixed-workload API checks; simulated guest operator, real gVisor execution."""

import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state  # noqa: E402
from services.common.crypto import load_or_create_key, sign, verify  # noqa: E402


def main():
    state = load_state()
    client = httpx.Client(base_url=state["public_url"], timeout=150)
    key_path = ROOT / ".local/guest-p5/approver-sign.pem"
    if not key_path.is_file():
        raise RuntimeError("Run the explicit guest executor fixture enrollment first")
    key = load_or_create_key(key_path)
    report = {"observed_at": datetime.now(UTC).isoformat(), "simulated": "guest operator signer; workloads, host checks, tripwire and receipts are real", "cases": {}}
    path = ROOT / "docs/infra" / ("P6-operator-jobs-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    for action in ["fork_limit", "memory_limit", "filesystem", "hostile_replay"]:
        payload = {"purpose": "operator_test", "action": action, "realm": "acme-guest", "approver_id": "simulated-p5-approver",
            "nonce": str(uuid.uuid4()), "ts": datetime.now(UTC).isoformat()}
        body = {"payload": payload, "signature": sign(key, payload)}
        response = client.post("/api/operator/jobs", json=body)
        response.raise_for_status()
        job = response.json()
        repeated = client.post("/api/operator/jobs", json=body)
        repeated.raise_for_status()
        tampered = {"payload": {**payload, "action": "filesystem" if action != "filesystem" else "fork_limit"}, "signature": body["signature"]}
        rejected = client.post("/api/operator/jobs", json=tampered)
        for _ in range(300):
            if job["status"] != "RUNNING":
                break
            time.sleep(1)
            response = client.get("/api/operator/jobs/" + job["job_id"])
            response.raise_for_status()
            job = response.json()
        print(action, job["status"], job.get("result_status"), flush=True)
        checks = {"duplicate_nonce_same_job": repeated.json()["job_id"] == job["job_id"],
            "tampered_operator_signature_rejected": rejected.status_code == 403,
            "job_finished": job["status"] == "FINISHED"}
        call = None
        if job.get("call_id"):
            response = client.get("/api/calls/" + job["call_id"])
            response.raise_for_status()
            call = response.json()
            checks.update({"guest_scope_preserved": call["realm"] == "acme-guest",
                "destroyed": bool(call.get("destroy_proof")), "signed_closed_receipt": bool(call.get("receipt"))})
            if call.get("receipt"):
                receipt = call["receipt"]
                verify(state["executor_public_key"], receipt["payload"], receipt["signature"])
                checks["receipt_no_identity_mutation"] = receipt["payload"]["reason"]["record_only"] is True
                checks["production_unchanged"] = receipt["payload"]["prod_state_digest_before"] == receipt["payload"]["prod_state_digest_after"]
            if action == "hostile_replay":
                checks.update({"compromised": call["status"] == "COMPROMISED",
                    "r1_r2_r3": {"R1", "R2", "R3"} <= set(call.get("policy", {}).get("rule_ids", [])),
                    "actual_14_otp_removals": sum(e["type"] == "credential.otp.removed" for e in call["effects"]) == 14,
                    "tripwire_under_one_second": any(e.get("kind") == "TRIPWIRE" and e["kill_latency_seconds"] < 1 for e in call["egress"]),
                    "operator_replay_labelled": call.get("workload_origin") == "operator_scripted_fault" and call.get("simulated_claims") is True})
            else:
                checks["containment_verified"] = call["status"] == "CONTAINMENT_VERIFIED" and all(call["containment_result"]["checks"].values())
        report["cases"][action] = {"job": job, "checks": checks, "passed": all(checks.values()),
            "call": {k: call.get(k) for k in ["call_id", "realm", "status", "effects", "policy", "egress", "containment_result", "destroy_proof", "receipt"]} if call else None}
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(action, checks, flush=True)
        if not all(checks.values()):
            raise SystemExit(1)
    report["all_passed"] = all(c["passed"] for c in report["cases"].values())
    path.write_text(json.dumps(report, indent=2) + "\n")
    print("Operator jobs:", report["all_passed"], str(path), flush=True)


if __name__ == "__main__":
    main()
