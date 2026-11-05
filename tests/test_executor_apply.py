"""Executor transaction behavior, including irreversible delivery and rollback."""
import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import ec

from services.common.contracts import ApplyRequest
from services.common.crypto import digest, public_jwk, sign, verify
from services.common.sealed import unseal_for_test
from services.control.effects import derive
from services.executor.apply import ApplyService
from test_executor_verification import UID, request_fixture


def setup_service(tmp_path, monkeypatch, *, email=False, fail_verify=False):
    import services.executor.apply as module
    raw, state, key = request_fixture()
    state["users"][UID]["emailVerified"] = True
    encryption = ec.generate_private_key(ec.SECP256R1())
    state["users"][UID]["attributes"]["device_encryption_pubkey_jwk"] = [json.dumps(public_jwk(encryption))]
    target = copy.deepcopy(state)
    if email:
        target["users"][UID]["email"] = "new@acme.test"
    else:
        target["users"][UID]["credentials"]["p"]["createdDate"] = 2
        target["users"][UID]["requiredActions"] = ["UPDATE_PASSWORD"]
    raw["change_set"]["effects"] = derive(state, target)
    raw["change_set"]["prod_state_digest"] = digest(state)
    raw["change_set_hash"] = digest(raw["change_set"])
    raw["signatures"][0]["payload"]["change_set_hash"] = raw["change_set_hash"]
    raw["signatures"][0]["signature"] = sign(key, raw["signatures"][0]["payload"])
    if email:
        approver = ec.generate_private_key(ec.SECP256R1())
        (tmp_path / "approvers.json").write_text(json.dumps({"human": {"public_key": public_jwk(approver), "realms": ["acme"]}}))
        payload = {"change_set_hash": raw["change_set_hash"], "decision": "approve", "approver_id": "human", "ts": datetime.now(UTC).isoformat()}
        raw["signatures"].append({"kind": "approver", "payload": payload, "signature": sign(approver, payload)})
    calls = []
    kc = SimpleNamespace(client=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(module, "Keycloak", lambda config: kc)
    monkeypatch.setattr(module, "snapshot", lambda *args: copy.deepcopy(state))
    def mutate(client, realm, effect, current, temporary=None):
        calls.append((effect["type"], temporary))
        if effect["type"] == "user.password.reset":
            state["users"][UID]["credentials"]["p"]["createdDate"] = 2
            state["users"][UID]["requiredActions"] = ["UPDATE_PASSWORD"]
        else:
            state["users"][UID]["email"] = effect["after"]
            state["users"][UID]["emailVerified"] = effect.get("_restore_email_verified", False)
    monkeypatch.setattr(module, "mutate", mutate)
    if fail_verify:
        monkeypatch.setattr(module, "same_effects", lambda *args: False)
    monkeypatch.setattr(module, "s3_client", lambda c: SimpleNamespace(put_object=lambda **kwargs: None))
    monkeypatch.setattr(module, "export_all", lambda *args: None)
    signing = ec.generate_private_key(ec.SECP256R1())
    service = ApplyService({"signing_key_path": str(tmp_path / "executor.pem"), "receipts_bucket": "test"}, signing)
    return service, ApplyRequest.model_validate(raw), state, calls, encryption, signing


def test_verified_reset_is_idempotent_and_only_ciphertext_is_persisted(tmp_path, monkeypatch):
    service, request, state, calls, encryption, signing = setup_service(tmp_path, monkeypatch)
    result = service.apply(request)
    assert result["receipt"]["payload"]["status"] == "APPLIED_VERIFIED"
    verify(public_jwk(signing), result["receipt"]["payload"], result["receipt"]["signature"])
    assert service.apply(request)["idempotent"] and len(calls) == 1
    with service.db() as db:
        box = json.loads(db.execute("SELECT box FROM deliveries").fetchone()[0])
    plaintext = unseal_for_test(encryption, box)["temporary_password"]
    assert plaintext == calls[0][1]
    assert all(plaintext.encode() not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_failed_postverify_reverts_and_verifies_reversible_field(tmp_path, monkeypatch):
    service, request, state, calls, _, _ = setup_service(tmp_path, monkeypatch, email=True, fail_verify=True)
    result = service.apply(request)["receipt"]["payload"]
    assert result["status"] == "FAILED_VERIFY" and result["reason"]["alarm"]
    assert state["users"][UID]["email"] == "sam@acme.test"
    assert result["rollback"] == [{"effect_id": request.change_set.effects[0].id, "reverted": True}]
    assert len(calls) == 2
    assert state["users"][UID]["emailVerified"] is True
    assert result["prod_state_digest_before"] == result["prod_state_digest_after"]


def test_started_execution_is_never_repeated(tmp_path, monkeypatch):
    service, request, _, calls, _, _ = setup_service(tmp_path, monkeypatch)
    with service.db() as db:
        db.execute("INSERT INTO executions VALUES (?,?,?,NULL)", (request.change_set.call_id, request.change_set_hash, "STARTED"))
    result = service.apply(request)["receipt"]["payload"]
    assert result["status"] == "REFUSED" and result["reason"]["code"] == "INDETERMINATE" and not calls
