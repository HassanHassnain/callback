import json
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from services.common.contracts import OperatorProof
from services.common.crypto import public_jwk, sign
from services.executor.operator import verify_operator
from services.executor.verify import Refusal


def test_operator_workload_requires_actual_pinned_key_and_realm_scope(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "approvers.json").write_text(json.dumps({"guest": {"public_key": public_jwk(key), "realms": ["acme-guest"]}}))
    payload = {"purpose": "operator_test", "action": "fork_limit", "realm": "acme-guest", "approver_id": "guest",
        "nonce": str(uuid.uuid4()), "ts": datetime.now(UTC).isoformat()}
    proof = OperatorProof.model_validate({"payload": payload, "signature": sign(key, payload)})
    assert verify_operator(proof, tmp_path)["verified"]
    payload["realm"] = "acme"
    with pytest.raises(Refusal) as error:
        verify_operator(OperatorProof.model_validate({"payload": payload, "signature": sign(key, payload)}), tmp_path)
    assert error.value.code == "APPROVER_SCOPE"
    payload["realm"] = "acme-guest"
    payload["action"] = "filesystem"
    with pytest.raises(Refusal) as error:
        verify_operator(OperatorProof.model_validate({"payload": payload, "signature": proof.signature}), tmp_path)
    assert error.value.code == "INVALID_SIGNATURE"
