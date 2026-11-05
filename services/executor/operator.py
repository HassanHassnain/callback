"""Verify signed requests for fixed disposable-twin tests; no production mutation."""

import json
from pathlib import Path

from services.common.contracts import original
from services.common.crypto import verify
from services.executor.verify import Refusal, fresh, require


def verify_operator(proof, root):
    payload = original(proof.payload)
    fresh(payload["ts"])
    path = Path(root) / "approvers.json"
    approvers = json.loads(path.read_text()) if path.exists() else {}
    pinned = approvers.get(payload["approver_id"])
    require(pinned is not None, "UNKNOWN_APPROVER", "Operator key is not pinned")
    require(payload["realm"] in pinned["realms"], "APPROVER_SCOPE", "Operator key is outside this realm")
    try:
        verify(pinned["public_key"], payload, proof.signature)
    except Exception as exc:
        raise Refusal("INVALID_SIGNATURE", "Operator request did not verify") from exc
    return {"verified": True, "approver_id": payload["approver_id"], "realm": payload["realm"], "action": payload["action"]}
