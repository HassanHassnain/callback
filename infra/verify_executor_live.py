"""Real P5 executor checks in acme-guest only; device keys/proposals are simulated."""
import copy
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state, ssh  # noqa: E402
from services.common.crypto import digest, load_or_create_key, public_jwk, sign, verify  # noqa: E402
from services.common.sealed import unseal_for_test  # noqa: E402
from services.control.effects import derive  # noqa: E402


def rpc(state, path, body=None):
    script = "cd /opt/callback\n.venv/bin/python - <<'CALLBACK_RPC'\nimport httpx,json\n"
    script += "r=httpx.request(" + repr("GET" if body is None else "POST") + "," + repr("http://10.77.0.6:8081" + path)
    if body is not None:
        script += ",json=json.loads(" + repr(json.dumps(body)) + ")"
    script += ",timeout=120,trust_env=False)\nr.raise_for_status()\nprint(r.text)\nCALLBACK_RPC\n"
    result = ssh(state, "control", script, timeout=150, check=False)
    if result.returncode:
        raise RuntimeError("Executor RPC failed: " + path + " " + result.stderr[-400:])
    return json.loads(result.stdout)


def enrollment(key, encryption, username):
    payload = {"kind": "device", "realm": "acme-guest", "identity": username, "public_key": public_jwk(key),
        "encryption_public_key": {**public_jwk(encryption), "key_ops": []}, "nonce": str(uuid.uuid4()), "ts": datetime.now(UTC).isoformat()}
    return {"payload": payload, "signature": sign(key, payload)}


def proposal(seed, after, key, username, decision="approve"):
    before = seed["payload"]["normalized_state"]
    changes = {"call_id": str(uuid.uuid4()), "realm": "acme-guest", "seed_version": seed["payload"]["version"],
        "prod_state_digest": digest(before), "effects": derive(before, after), "created_at": datetime.now(UTC).isoformat()}
    hashed = digest(changes)
    payload = {"change_set_hash": hashed, "decision": decision, "username": username, "ts": datetime.now(UTC).isoformat()}
    return {"change_set": changes, "change_set_hash": hashed, "signatures": [{"kind": "device", "payload": payload, "signature": sign(key, payload)}],
        "context": {"simulation": "Executor integration test: simulated device and synthetic proposal; real guest Keycloak mutation", "call_status": "AWAITING_DEVICE"}}


def main():
    state = load_state()
    root = ROOT / ".local/guest-p5"
    root.mkdir(exist_ok=True)
    root.chmod(0o700)
    original_main = rpc(state, "/seeds/latest/acme")["payload"]["prod_state_digest"]
    keys = {}
    for username in ["sam.rivera", "dana.whitfield"]:
        key = load_or_create_key(root / (username + "-sign.pem"))
        encryption = load_or_create_key(root / (username + "-decrypt.pem"))
        keys[username] = (key, encryption)
        path = root / (username + "-bundle.json")
        path.write_text(json.dumps(enrollment(key, encryption, username)))
        subprocess.run(["uv", "run", "python", "infra/enroll_device.py", "--realm", "acme-guest", "--user", username, "--bundle", str(path)], cwd=ROOT, check=True)
    report = {"observed_at": datetime.now(UTC).isoformat(), "realm": "acme-guest", "simulated": "device keys and proposals; real executor, signatures, REST mutations, storage, post-verify", "checks": {}, "receipts": []}
    seed = rpc(state, "/seeds/latest/acme-guest")
    verify(state["executor_public_key"], seed["payload"], seed["signature"])
    before = seed["payload"]["normalized_state"]
    sam = next(u for u in before["users"].values() if u["username"] == "sam.rivera")
    after = copy.deepcopy(before)
    pw = next(c for c in after["users"][sam["id"]]["credentials"].values() if c["type"] == "password")
    pw["createdDate"] = (pw.get("createdDate") or 0) + 1
    after["users"][sam["id"]]["requiredActions"] = sorted(set(sam["requiredActions"]) | {"UPDATE_PASSWORD"})
    body = proposal(seed, after, keys["sam.rivera"][0], "sam.rivera")
    result = rpc(state, "/apply", body)
    receipt = result["receipt"]
    verify(state["executor_public_key"], receipt["payload"], receipt["signature"])
    report["checks"]["sam_real_apply_postverified"] = receipt["payload"]["status"] == "APPLIED_VERIFIED"
    report["checks"]["signed_receipt"] = True
    report["receipts"].append(receipt)
    if not report["checks"]["sam_real_apply_postverified"]:
        raise RuntimeError("Guest apply did not verify: " + json.dumps(receipt["payload"]["reason"]))
    delivery = {"call_id": body["change_set"]["call_id"], "realm": "acme-guest", "username": "sam.rivera",
        "change_set_hash": body["change_set_hash"], "purpose": "delivery", "ts": datetime.now(UTC).isoformat()}
    encrypted = rpc(state, "/delivery", {"payload": delivery, "signature": sign(keys["sam.rivera"][0], delivery)})
    plaintext = unseal_for_test(keys["sam.rivera"][1], encrypted["box"])
    report["checks"]["only_registered_key_decrypts"] = bool(plaintext.get("temporary_password")) and plaintext["required_action"] == "UPDATE_PASSWORD"
    report["checks"]["no_plaintext_in_response_or_receipt"] = plaintext["temporary_password"] not in json.dumps([encrypted, result])
    repeated = rpc(state, "/apply", body)
    report["checks"]["idempotent_same_receipt"] = repeated.get("idempotent") and repeated["receipt"]["signature"] == receipt["signature"]
    tampered = copy.deepcopy(body)
    tampered["change_set"]["seed_version"] += "-tamper"
    refusal = rpc(state, "/apply", tampered)["receipt"]
    report["checks"]["tamper_hash_mismatch"] = refusal["payload"]["reason"]["code"] == "HASH_MISMATCH"
    report["receipts"].append(refusal)
    seed = rpc(state, "/seeds/latest/acme-guest")
    before = seed["payload"]["normalized_state"]
    dana = next(u for u in before["users"].values() if u["username"] == "dana.whitfield")
    after = copy.deepcopy(before)
    user = after["users"][dana["id"]]
    user["credentials"] = {k:v for k,v in user["credentials"].items() if v["type"] != "otp"}
    user["requiredActions"] = sorted(set(user["requiredActions"]) | {"CONFIGURE_TOTP"})
    deny = proposal(seed, after, keys["dana.whitfield"][0], "dana.whitfield", "deny")
    denied = rpc(state, "/apply", deny)["receipt"]
    report["checks"]["dana_signed_deny_unchanged"] = denied["payload"]["status"] == "DENIED" and denied["payload"]["prod_state_digest_before"] == denied["payload"]["prod_state_digest_after"] == digest(before)
    report["receipts"].append(denied)
    # Deliberate operator fault: after the approved email write, a separate
    # real REST update disables the guest account. Post-verify must observe
    # that extra effect, restore its own reversible email change, and avoid
    # overwriting the unrelated concurrent field. No result is simulated.
    approver = load_or_create_key(root / "approver-sign.pem")
    public = {"kind": "approver", "realm": "acme-guest", "identity": "simulated-p5-approver",
        "public_key": public_jwk(approver), "nonce": str(uuid.uuid4()), "ts": datetime.now(UTC).isoformat()}
    bundle = root / "approver-bundle.json"
    bundle.write_text(json.dumps({"payload": public, "signature": sign(approver, public)}))
    subprocess.run(["uv", "run", "python", "infra/enroll_approver.py", "--realm", "acme-guest", "--approver",
        "simulated-p5-approver", "--bundle", str(bundle)], cwd=ROOT, check=True)
    email_after = copy.deepcopy(before)
    email_after["users"][sam["id"]]["email"] = "p5-rollback-probe@acme.test"
    email_body = proposal(seed, email_after, keys["sam.rivera"][0], "sam.rivera")
    approval = {"change_set_hash": email_body["change_set_hash"], "decision": "approve", "approver_id": "simulated-p5-approver",
        "ts": datetime.now(UTC).isoformat()}
    email_body["signatures"].append({"kind": "approver", "payload": approval, "signature": sign(approver, approval)})
    script = "cd /opt/callback\ndocker compose exec -T executor /opt/callback/.venv/bin/python - <<'ROLLBACK_TEST'\n"
    script += "import json\nfrom pathlib import Path\nimport services.executor.apply as module\nfrom services.executor.keycloak import Keycloak,config_from_file,update_user\nfrom services.common.contracts import ApplyRequest\nfrom services.common.crypto import load_or_create_key\nfrom services.executor.app import export_once\n"
    script += "body=json.loads(" + repr(json.dumps(email_body)) + ")\n"
    script += "assert body['change_set']['realm']=='acme-guest'\nc=config_from_file();real_mutate=module.mutate\n"
    script += "uid=" + repr(sam["id"]) + "\n"
    script += "def with_fault(kc,realm,effect,current,temporary=None):\n assert realm=='acme-guest'\n real_mutate(kc,realm,effect,current,temporary)\n if effect['type']=='user.email.changed' and effect['after']=='p5-rollback-probe@acme.test':\n  update_user(kc,realm,uid,{'enabled':False})\n"
    script += "module.mutate=with_fault\nservice=module.ApplyService(c,load_or_create_key(Path(c['signing_key_path'])))\ntry:\n result=service.apply(ApplyRequest.model_validate(body))\n print(json.dumps(result))\nfinally:\n k=Keycloak(c)\n update_user(k,'acme-guest',uid,{'enabled':True})\n k.client.close()\n export_once(c)\nROLLBACK_TEST\n"
    response = ssh(state,"executor",script,timeout=120,check=False)
    if response.returncode:
        raise RuntimeError("Guest operator rollback test failed: " + response.stderr[-400:])
    rollback = json.loads(response.stdout)["receipt"]
    report["postverify_fault_origin"] = "Operator-scripted real guest REST enabled change; simulated device/approver signatures"
    report["checks"]["real_postverify_mismatch_alarms"] = rollback["payload"]["status"] == "FAILED_VERIFY" and rollback["payload"]["reason"]["alarm"]
    report["checks"]["real_email_rollback_verified"] = bool(rollback["payload"]["rollback"]) and all(r["reverted"] for r in rollback["payload"]["rollback"]) and all(e["type"] != "user.email.changed" for e in rollback["payload"]["actual_effects"])
    report["checks"]["concurrent_change_not_overwritten"] = any(e["type"] == "user.enabled.changed" and e["after"] is False for e in rollback["payload"]["actual_effects"])
    report["receipts"].append(rollback)
    # Exercise CAS against a real, narrowly scoped synthetic fixture change.
    uid = sam["id"]
    drift_after = copy.deepcopy(before)
    drift_after["users"][uid]["credentials"][next(k for k,v in drift_after["users"][uid]["credentials"].items() if v["type"] == "password")]["createdDate"] += 1
    drift_after["users"][uid]["requiredActions"] = sorted(set(drift_after["users"][uid]["requiredActions"]) | {"UPDATE_PASSWORD"})
    drift_body = proposal(seed, drift_after, keys["sam.rivera"][0], "sam.rivera")
    prior_email = before["users"][uid]["email"]
    def set_email(value):
        script = "cd /opt/callback\ndocker compose exec -T executor /opt/callback/.venv/bin/python - <<'DRIFT'\nfrom services.executor.keycloak import Keycloak,config_from_file,update_user\nk=Keycloak(config_from_file())\nupdate_user(k,'acme-guest','" + uid + "',{'email':" + repr(value) + ",\"emailVerified\":" + repr(before["users"][uid]["emailVerified"]) + "})\nk.client.close()\nDRIFT\n"
        ssh(state, "executor", script)
    try:
        set_email("p5-drift-probe@acme.test")
        drift = rpc(state, "/apply", drift_body)["receipt"]
        report["checks"]["real_drift_refused"] = drift["payload"]["reason"]["code"] == "DRIFT"
        report["receipts"].append(drift)
    finally:
        set_email(prior_email)
    ssh(state, "executor", "cd /opt/callback\ndocker compose exec -T executor /opt/callback/.venv/bin/python - <<'EXPORT'\nfrom services.executor.app import export_once\nfrom services.executor.keycloak import config_from_file\nexport_once(config_from_file())\nEXPORT\n", timeout=120)
    report["checks"]["main_realm_unchanged"] = rpc(state, "/seeds/latest/acme")["payload"]["prod_state_digest"] == original_main
    report["all_passed"] = all(report["checks"].values())
    destination = ROOT / "docs/infra" / ("P5-executor-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"checks": report["checks"], "all_passed": report["all_passed"], "evidence": str(destination)}), flush=True)
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
