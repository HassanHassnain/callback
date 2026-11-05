import copy
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from services.common.contracts import ApplyRequest
from services.common.crypto import digest, public_jwk, sign
from services.control.effects import derive
from services.executor.verify import Refusal, cas, policy_floor, validate_hash, verify_decisions


UID = "11111111-1111-4111-8111-111111111111"


def request_fixture(tier="standard"):
    key = ec.generate_private_key(ec.SECP256R1())
    user = {"id": UID, "username": "sam.rivera", "email": "sam@acme.test", "enabled": True,
        "attributes": {"tier": [tier], "device_pubkey_jwk": [json.dumps(public_jwk(key))]},
        "groups": [], "realmRoles": [], "clientRoles": {}, "bruteForce": {"disabled": False},
        "requiredActions": [], "credentials": {"p": {"id": "p", "type": "password", "createdDate": 1}}}
    current = {"realm": "acme", "users": {UID: user}, "settings": {}, "groups": {}, "roles": {}, "clients": {}}
    after = copy.deepcopy(current)
    after["users"][UID]["credentials"]["p"]["createdDate"] = 2
    after["users"][UID]["requiredActions"] = ["UPDATE_PASSWORD"]
    change_set = {"call_id": "22222222-2222-4222-8222-222222222222", "realm": "acme", "seed_version": "v1",
        "prod_state_digest": digest(current), "effects": derive(current, after), "created_at": datetime.now(UTC).isoformat()}
    hashed = digest(change_set)
    payload = {"change_set_hash": hashed, "decision": "approve", "username": "sam.rivera", "ts": datetime.now(UTC).isoformat()}
    raw = {"change_set": change_set, "change_set_hash": hashed,
           "signatures": [{"kind": "device", "payload": payload, "signature": sign(key, payload)}]}
    return raw, current, key


def test_standard_reset_needs_actual_registered_key_and_exact_hash():
    raw, state, _ = request_fixture()
    request = ApplyRequest.model_validate(raw)
    canonical = validate_hash(request)
    devices, operators, denied = verify_decisions(request, state, {})
    assert devices == {"sam.rivera"} and not denied
    assert not policy_floor(canonical, state, devices, operators)["human_required"]
    cas(canonical, state)
    raw["change_set"]["effects"][0]["target"]["username"] = "dana.whitfield"
    with pytest.raises(Refusal) as error:
        validate_hash(ApplyRequest.model_validate(raw))
    assert error.value.code == "HASH_MISMATCH"


def test_privileged_floor_cannot_be_relaxed_by_control():
    raw, state, _ = request_fixture("privileged")
    request = ApplyRequest.model_validate(raw)
    devices, operators, _ = verify_decisions(request, state, {})
    with pytest.raises(Refusal) as error:
        policy_floor(validate_hash(request), state, devices, operators)
    assert error.value.code == "APPROVER_REQUIRED"


def test_guest_approver_cannot_authorize_main_realm():
    raw, state, _ = request_fixture("privileged")
    approver = ec.generate_private_key(ec.SECP256R1())
    payload = {"change_set_hash": raw["change_set_hash"], "decision": "approve", "approver_id": "guest", "ts": datetime.now(UTC).isoformat()}
    raw["signatures"].append({"kind": "approver", "payload": payload, "signature": sign(approver, payload)})
    with pytest.raises(Refusal) as error:
        verify_decisions(ApplyRequest.model_validate(raw), state, {"guest": {"public_key": public_jwk(approver), "realms": ["acme-guest"]}})
    assert error.value.code == "APPROVER_SCOPE"


def test_production_drift_and_stale_decision_are_refused():
    raw, state, key = request_fixture()
    changed = copy.deepcopy(state)
    changed["users"][UID]["email"] = "changed@acme.test"
    with pytest.raises(Refusal) as error:
        cas(raw["change_set"], changed)
    assert error.value.code == "DRIFT"
    payload = raw["signatures"][0]["payload"]
    payload["ts"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    raw["signatures"][0]["signature"] = sign(key, payload)
    with pytest.raises(Refusal) as error:
        verify_decisions(ApplyRequest.model_validate(raw), state, {})
    assert error.value.code == "STALE_SIGNATURE"


def test_signed_deny_is_not_an_approval():
    raw, state, key = request_fixture()
    payload = raw["signatures"][0]["payload"]
    payload["decision"] = "deny"
    raw["signatures"][0]["signature"] = sign(key, payload)
    devices, operators, denied = verify_decisions(ApplyRequest.model_validate(raw), state, {})
    assert not devices and not operators and denied == [{"kind": "device", "identity": "sam.rivera"}]
