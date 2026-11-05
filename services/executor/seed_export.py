"""Export normalized production metadata and sign a secret-scrubbed twin import."""

import copy
import hashlib
import json
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path

import boto3

from services.common.crypto import canonical, digest, load_or_create_key, public_jwk, sign, verify
from services.common.state import snapshot, without_secrets  # noqa: F401
from services.executor.bootstrap import otp_credential

EXPORT_LOCK = threading.Lock()


def build_seed(normalized):
    realm = normalized["realm"]
    users = []
    for user in normalized["users"].values():
        imported = {key: copy.deepcopy(user[key]) for key in [
            "id", "username", "firstName", "lastName", "email", "enabled", "emailVerified",
            "attributes", "requiredActions", "groups", "realmRoles", "clientRoles"]}
        imported["credentials"] = []
        for credential in user["credentials"].values():
            twin = copy.deepcopy(credential)
            if credential["type"] == "password":
                twin.update({"value": secrets.token_urlsafe(32), "temporary": False})
            elif credential["type"] == "otp":
                twin.update(otp_credential())
                twin["id"] = credential["id"]
            else:
                raise RuntimeError("Unsupported credential type; refusing an incomplete seed")
            imported["credentials"].append(twin)
        users.append(imported)
    clients = []
    for client in normalized["clients"].values():
        # Every confidential client receives a twin-only credential. No VPC URLs
        # or real client authentication material enter the import representation.
        entry = {key: copy.deepcopy(value) for key, value in client.items() if key != "secret_fingerprint"}
        entry["redirectUris"] = ["http://localhost:8080/*"]
        if (not entry.get("publicClient") and not entry.get("bearerOnly")
                and entry.get("clientAuthenticatorType", "client-secret") == "client-secret"):
            entry["secret"] = secrets.token_urlsafe(40)
        clients.append(entry)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    state_digest = digest(normalized)
    return {"schema_version": 1, "realm": realm, "version": stamp + "-" + state_digest[:12],
            "created_at": datetime.now(UTC).isoformat(), "prod_state_digest": state_digest,
            "normalized_state": normalized, "scrubbed": True,
            "user_profile": normalized.get("userProfile", {}),
            "realm_import": {**copy.deepcopy(normalized["settings"]),
                "realm": realm, "enabled": True, "sslRequired": "none",
                "registrationAllowed": False, "resetPasswordAllowed": False,
                "groups": [copy.deepcopy(g) for g in normalized["groups"].values()],
                "roles": {"realm": [copy.deepcopy(r) for r in normalized["roles"].values()]},
                "clients": clients, "users": users}}


def assert_scrubbed(seed, credential_audit, client_secret):
    encoded = canonical(seed)
    if client_secret.encode() in encoded or b"-----BEGIN" in encoded:
        raise RuntimeError("Credential/private-key material found in seed")
    forbidden = set(credential_audit.get("initial_secret_value_sha256", []))
    production_ids = {cid for user in seed["normalized_state"]["users"].values() for cid in user["credentials"]}
    imported_ids = set()
    for user in seed["realm_import"]["users"]:
        for credential in user["credentials"]:
            imported_ids.add(credential["id"])
            if credential["type"] == "password":
                if "secretData" in credential or "credentialData" in credential:
                    raise RuntimeError("Production password hash data is forbidden in imports")
                raw = credential["value"]
            else:
                raw = json.loads(credential["secretData"])["value"]
            if hashlib.sha256(raw.encode()).hexdigest() in forbidden:
                raise RuntimeError("A production initial secret was reused in the twin")
    if imported_ids != production_ids:
        raise RuntimeError("Seed credential metadata IDs do not match the production snapshot")
    return {"credential_ids_preserved": len(imported_ids), "initial_secrets_reused": False,
            "password_hash_data_present": False}


def s3_client(config):
    return boto3.client("s3", endpoint_url="https://" + config["object_storage_host"],
                        aws_access_key_id=config["object_storage_access_key"],
                        aws_secret_access_key=config["object_storage_secret_key"], region_name="us-east-1")


def export_realm(kc, config, realm):
    normalized = snapshot(kc, realm)
    seed = build_seed(normalized)
    audit = json.loads(Path("/run/callback/initial-credential-audit.json").read_text())
    checks = assert_scrubbed(seed, audit.get(realm, {}), kc.credentials["client_secret"])
    key = load_or_create_key(Path(config["signing_key_path"]))
    jwk = public_jwk(key)
    envelope = {"payload": seed, "signature": sign(key, seed), "signer_public_key": jwk}
    verify(jwk, seed, envelope["signature"])
    storage = s3_client(config)
    object_key = f"seed-{realm}-{seed['version']}.json"
    storage.put_object(Bucket=config["seeds_bucket"], Key=object_key,
                       Body=canonical(envelope), ContentType="application/json")
    pointer = {"object_key": object_key, "seed_sha256": digest(seed), "version": seed["version"],
               "prod_state_digest": seed["prod_state_digest"], "created_at": seed["created_at"]}
    storage.put_object(Bucket=config["seeds_bucket"], Key=f"latest/{realm}.json",
                       Body=canonical(pointer), ContentType="application/json")
    Path(f"/run/callback/latest-{realm}.json").write_bytes(canonical(envelope))
    return {"realm": realm, "employees": len(normalized["users"]),
            "admins": sum("/admins" in u["groups"] for u in normalized["users"].values()),
            "version": seed["version"], "object_key": object_key, "signature_verified": True, **checks}


def export_all(kc, config):
    with EXPORT_LOCK:
        return [export_realm(kc, config, realm) for realm in config["realms"]]


def audit_database_hashes(seed, production_metadata):
    """Compare with secret-data hashes computed inside the production DB host."""
    expected = {item["id"]: item for item in production_metadata}
    checked = 0
    for user in seed["realm_import"]["users"]:
        for credential in user["credentials"]:
            item = expected[credential["id"]]
            if credential["type"] == "password":
                if "secretData" in credential:
                    raise RuntimeError("Seed contains password hash data")
            else:
                hashed = hashlib.sha256(credential["secretData"].encode()).hexdigest()
                value_hash = hashlib.sha256(json.loads(credential["secretData"])["value"].encode()).hexdigest()
                if hashed == item["secret_data_sha256"] or value_hash == item.get("secret_value_sha256"):
                    raise RuntimeError("Seed contains a production OTP secret-data value")
            checked += 1
    return {"production_credential_hash_comparisons": checked, "production_secret_data_reused": False}
