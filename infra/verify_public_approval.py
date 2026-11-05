"""Real public planner/twin/approval path; simulated registered guest device only."""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state  # noqa: E402
from services.common.crypto import digest, load_or_create_key, sign, verify  # noqa: E402
from services.common.sealed import unseal_for_test  # noqa: E402


def main():
    state = load_state()
    client = httpx.Client(base_url=state["public_url"], timeout=150)
    if "--resume" in sys.argv:
        call = client.get("/api/calls/" + sys.argv[sys.argv.index("--resume") + 1]).json()
    else:
        for _ in range(40):
            response = client.post("/api/calls", json={"realm": "acme-guest"})
            if response.status_code in {425, 429, 503}:
                time.sleep(3)
                continue
            response.raise_for_status()
            call = response.json()
            break
        else:
            raise RuntimeError("Guest twin did not become available")
    print("Guest call", call["call_id"], flush=True)
    messages = [
        "I'm Sam Rivera from Sales, employee ACME-1002. Please stage a temporary password reset. I will approve the exact changes on my registered device.",
        "Yes, please stage that temporary password reset for sam.rivera now and send its exact changes to my registered device. I understand staging does not change production.",
        "Please complete the staging and request device confirmation, then end the call. I am ready to review the actual effects.",
    ]
    if "--resume" in sys.argv:
        messages = messages[1:]
    for text in messages:
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
        print("Caller turn", call["status"], "effects", len(call["effects"]), flush=True)
    checks = {
        "frozen_destroyed_proposal": call["status"] == "AWAITING_DEVICE"
        and bool(call.get("destroy_proof")),
        "one_sam_reset": len(call["effects"]) == 1
        and call["effects"][0]["type"] == "user.password.reset"
        and call["effects"][0]["target"]["username"] == "sam.rivera",
        "r7_auto_eligible": call.get("policy", {}).get("auto_eligible") is True,
        "exact_proposal_hash": digest(call.get("change_set")) == call.get("change_set_hash"),
        "actual_vultr_models": bool(call["model_calls"])
        and all(m["model_id_verified"] for m in call["model_calls"]),
    }
    if all(checks.values()):
        key = load_or_create_key(ROOT / ".local/guest-p5/sam.rivera-sign.pem")
        payload = {
            "change_set_hash": call["change_set_hash"],
            "decision": "approve",
            "username": "sam.rivera",
            "ts": datetime.now(UTC).isoformat(),
        }
        response = client.post(
            "/api/calls/" + call["call_id"] + "/decisions",
            json={"kind": "device", "payload": payload, "signature": sign(key, payload)},
        )
        response.raise_for_status()
        call = response.json()
        checks["auto_applied_verified"] = call["status"] == "APPLIED_VERIFIED"
        if call.get("receipt"):
            verify(
                state["executor_public_key"],
                call["receipt"]["payload"],
                call["receipt"]["signature"],
            )
            checks["receipt_signature"] = True
        if checks["auto_applied_verified"]:
            binding = {
                "call_id": call["call_id"],
                "realm": "acme-guest",
                "username": "sam.rivera",
                "change_set_hash": call["change_set_hash"],
            }
            payload = {**binding, "purpose": "delivery", "ts": datetime.now(UTC).isoformat()}
            response = client.post(
                "/api/device/delivery", json={"payload": payload, "signature": sign(key, payload)}
            )
            response.raise_for_status()
            encrypted = response.json()
            private = load_or_create_key(ROOT / ".local/guest-p5/sam.rivera-decrypt.pem")
            secret = unseal_for_test(private, encrypted["box"])["temporary_password"]
            checks["encrypted_public_delivery"] = bool(secret) and secret not in json.dumps(
                [call, encrypted]
            )
            response = client.post("/api/calls/" + call["call_id"] + "/tamper")
            response.raise_for_status()
            refusal = response.json()["receipt"]
            checks["public_tamper_refused"] = (
                refusal["payload"]["reason"]["code"] == "HASH_MISMATCH"
            )
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "realm": "acme-guest",
        "simulated": "device signer and decryptor; real public HTTPS, Vultr planner, twin, effects, executor and Keycloak",
        "checks": checks,
        "all_passed": all(checks.values()),
        "call": call,
    }
    path = (
        ROOT
        / "docs/infra"
        / ("P5-public-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    )
    # Twin throwaway tool output is retained privately; publish bounded evidence.
    report["call"] = {
        k: call.get(k)
        for k in [
            "call_id",
            "realm",
            "status",
            "effects",
            "policy",
            "model_calls",
            "change_set_hash",
            "destroy_proof",
            "receipt",
            "simulated_device",
        ]
    }
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "all_passed": report["all_passed"],
                "checks": checks,
                "call_id": call["call_id"],
                "evidence": str(path),
            }
        ),
        flush=True,
    )
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
