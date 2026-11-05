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


def test_receipt_storage_outage_retries_without_repeating_mutation(tmp_path, monkeypatch):
    import services.executor.apply as module
    service, request, _, calls, _, _ = setup_service(tmp_path, monkeypatch)
    stored = {}
    alias = request.change_set.call_id + ".json"
    offline = True
    class Storage:
        def put_object(self, **kwargs):
            if kwargs["Key"] == alias and offline:
                raise OSError("Injected Object Storage alias outage")
            stored[kwargs["Key"]] = kwargs["Body"]
    monkeypatch.setattr(module, "s3_client", lambda config: Storage())
    result = service.apply(request)
    assert result["receipt"]["payload"]["status"] == "APPLIED_VERIFIED"
    assert result["storage_pending"] and alias not in stored
    offline = False
    service.flush_receipts()
    assert json.loads(stored[alias]) == result["receipt"]
    assert service.apply(request)["idempotent"] and len(calls) == 1


def test_noncanonical_context_is_refused_before_any_mutation(tmp_path, monkeypatch):
    from services.common.contracts import original
    service, request, _, calls, _, _ = setup_service(tmp_path, monkeypatch)
    raw = original(request)
    raw["context"] = {"invalid": float("nan")}
    result = service.apply(ApplyRequest.model_validate(raw))
    assert result["receipt"]["payload"]["status"] == "REFUSED"
    assert result["receipt"]["payload"]["reason"]["code"] == "NON_CANONICAL_REQUEST"
    assert not calls


def test_record_only_signs_observation_without_dispatching_mutation(tmp_path, monkeypatch):
    from services.common.contracts import original
    service, request, _, calls, _, signing = setup_service(tmp_path, monkeypatch)
    body = original(request)
    body["context"] = {"call_status": "COMPROMISED", "simulation": "unit fixture"}
    result = service.record_only(ApplyRequest.model_validate(body))
    payload = result["receipt"]["payload"]
    verify(public_jwk(signing), payload, result["receipt"]["signature"])
    assert payload["status"] == "BLOCKED" and payload["reason"]["record_only"]
    assert not payload["verified"] and not payload["authorization_verified"]
    assert payload["context_provenance"] == "control_reported"
    assert payload["prod_state_digest_before"] == payload["prod_state_digest_after"]
    assert not calls
    assert service.record_only(ApplyRequest.model_validate(body))["idempotent"]
