"""Frozen proposals, independently checked decisions, and encrypted-only forwarding."""

import hashlib
import json
import time

from services.common.contracts import ApplyRequest, original
from services.common.crypto import verify
from services.control.policy import evaluate


def request_for(call, signatures=None):
    context = {"call_status": call["status"], "twin": call["twin"], "destroy_proof": call.get("destroy_proof"),
        "transcript_sha256": hashlib.sha256(json.dumps(call["transcript"], sort_keys=True).encode()).hexdigest(),
        "models": call["model_calls"], "egress_events": call["egress"], "policy": call["policy"],
        "workload_origin": call.get("workload_origin", "live_planner"),
        "simulated_device": call["realm"] == "acme-guest",
        "snapshot_quality": call.get("snapshot_quality", {"complete": False, "quality": "unreported"})}
    return original(ApplyRequest.model_validate({"change_set": call["change_set"], "change_set_hash": call["change_set_hash"],
        "signatures": call.get("signatures", []) if signatures is None else signatures, "context": context}))


async def decide(engine, call, signed):
    if call["status"] not in {"AWAITING_DEVICE", "AWAITING_APPROVER"} or not call.get("destroy_proof"):
        raise ValueError("This call has no frozen, destroyed proposal awaiting a decision")
    if time.time() - call.get("approval_requested_epoch", call["created_epoch"]) > 3600:
        raise ValueError("This frozen proposal has expired; start a fresh request")
    if call["policy"]["outcome"] == "REJECT":
        raise ValueError("Rejected changes cannot be approved")
    decision = original(signed)
    signatures = call.get("signatures", []) + [decision]
    if len(signatures) > 10:
        raise ValueError("Decision limit reached")
    body = request_for(call, signatures)
    response = await engine.executor.post("/decisions/verify", json=body)
    response.raise_for_status()
    verified = response.json()
    call["signatures"] = signatures
    call["verified_decisions"] = verified
    policy = evaluate(call["effects"], call["seed_state"], device_users=verified["devices"],
        risk=call["risk"].get("social_engineering", 0), moderation=any(m["flagged"] for m in call["moderation"]))
    call["policy"] = policy
    ready = (set(policy["requires_device"]) <= set(verified["devices"])
             and (not policy["requires_human"] or bool(verified["approvers"])))
    if verified["denials"] or ready:
        call["status"] = "SUBMITTING"
        engine.save(call)
        try:
            response = await engine.executor.post("/apply", json=request_for(call))
            response.raise_for_status()
            result = response.json()
            receipt = result["receipt"]
            verify(engine.public_key, receipt["payload"], receipt["signature"])
            if receipt["payload"]["call_id"] != call["call_id"] or receipt["payload"]["change_set_hash"] != call["change_set_hash"]:
                raise ValueError("Executor receipt binding differs from the proposal")
            call["receipt"] = receipt
            call["production_status"] = receipt["payload"]["status"]
            call["status"] = receipt["payload"]["status"]
            call["storage_pending"] = result.get("storage_pending", False)
        except Exception:
            call["status"] = "RECONCILE_REQUIRED"
            call["production_status"] = "UNKNOWN_PENDING_RECEIPT"
            engine.save(call)
            raise
    else:
        call["status"] = "AWAITING_APPROVER" if set(policy["requires_device"]) <= set(verified["devices"]) else "AWAITING_DEVICE"
    engine.save(call)
    return engine.public(call)
