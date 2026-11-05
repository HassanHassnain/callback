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
    # Exercise CAS against a real, narrowly scoped synthetic fixture change.
    uid = sam["id"]
    drift_body = proposal(seed, {**copy.deepcopy(before)}, keys["sam.rivera"][0], "sam.rivera")
    drift_after = copy.deepcopy(before)
    drift_after["users"][uid]["credentials"][next(k for k,v in drift_after["users"][uid]["credentials"].items() if v["type"] == "password")]["createdDate"] += 1
    drift_after["users"][uid]["requiredActions"] = sorted(set(drift_after["users"][uid]["requiredActions"]) | {"UPDATE_PASSWORD"})
    drift_body = proposal(seed, drift_after, keys["sam.rivera"][0], "sam.rivera")
    prior_email = before["users"][uid]["email"]
    def set_email(value):
        script = "cd /opt/callback\ndocker compose exec -T executor /opt/callback/.venv/bin/python - <<'DRIFT'\nfrom services.executor.keycloak import Keycloak,config_from_file\nk=Keycloak(config_from_file())\nk.request('PUT','acme-guest','users/" + uid + "',body={'email':" + repr(value) + "})\nk.client.close()\nDRIFT\n"
        ssh(state, "executor", script)
    try:
        set_email("p5-drift-probe@acme.test")
        drift = rpc(state, "/apply", drift_body)["receipt"]
        report["checks"]["real_drift_refused"] = drift["payload"]["reason"]["code"] == "DRIFT"
        report["receipts"].append(drift)
    finally:
        set_email(prior_email)
    report["checks"]["main_realm_unchanged"] = rpc(state, "/seeds/latest/acme")["payload"]["prod_state_digest"] == original_main
    report["all_passed"] = all(report["checks"].values())
    destination = ROOT / "docs/infra" / ("P5-executor-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"checks": report["checks"], "all_passed": report["all_passed"], "evidence": str(destination)}), flush=True)
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
