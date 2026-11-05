"""Seed synthetic realms through the executor, never through control."""

import base64
import copy
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

from services.executor.keycloak import Keycloak, config_from_file


def otp_credential():
    return {"type": "otp", "userLabel": "Registered authenticator (synthetic)",
            "secretData": json.dumps({"value": base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")}),
            "credentialData": json.dumps({"subType": "totp", "digits": 6, "counter": 0,
                                           "period": 30, "algorithm": "HmacSHA1"})}


def provision():
    config = config_from_file(os.environ.get("EXECUTOR_CONFIG_PATH", "/run/callback/config.json"))
    admin = Keycloak(config, bootstrap=True)
    source = json.loads(Path("fixtures/realm_acme.json").read_text())
    audit_path = Path("/run/callback/initial-credential-audit.json")
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    for realm in config["realms"]:
        existing = admin.request("GET", realm, missing=True)
        if existing is None:
            fixture = copy.deepcopy(source)
            fixture["realm"] = realm
            raw_hashes = []
            for user in fixture["users"]:
                if realm != "acme":
                    user["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "callback:" + realm + ":" + user["username"]))
                password = secrets.token_urlsafe(32)
                user["credentials"] = [{"type": "password", "value": password, "temporary": False}]
                raw_hashes.append(hashlib.sha256(password.encode()).hexdigest())
                if user.pop("fixture_otp_enabled"):
                    credential = otp_credential()
                    user["credentials"].append(credential)
                    raw_hashes.append(hashlib.sha256(json.loads(credential["secretData"])["value"].encode()).hexdigest())
            admin.create_realm(fixture)
            audit[realm] = {"initial_secret_value_sha256": raw_hashes}
            audit_path.write_text(json.dumps(audit, indent=2))
            audit_path.chmod(0o600)
            print(f"Created {realm} with 40 synthetic employee accounts", flush=True)
        clients = admin.request("GET", realm, "clients", params={"clientId": "callback-executor"})
        if not clients:
            admin.request("POST", realm, "clients", body={"clientId": "callback-executor", "enabled": True,
                "protocol": "openid-connect", "publicClient": False, "serviceAccountsEnabled": True,
                "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
                "secret": admin.credentials["client_secret"]})
            clients = admin.request("GET", realm, "clients", params={"clientId": "callback-executor"})
        client = clients[0]
        stored = admin.request("GET", realm, f"clients/{client['id']}/client-secret")["value"]
        if not secrets.compare_digest(stored, admin.credentials["client_secret"]):
            raise RuntimeError("Existing executor client secret differs; refusing implicit rotation")
        service_user = admin.request("GET", realm, f"clients/{client['id']}/service-account-user")
        management = admin.request("GET", realm, "clients", params={"clientId": "realm-management"})[0]
        role = admin.request("GET", realm, f"clients/{management['id']}/roles/realm-admin")
        admin.request("POST", realm,
            f"users/{service_user['id']}/role-mappings/clients/{management['id']}", body=[role])
        # Make the two authoritative fields admin-managed. Preserve the stock
        # profile fields, rather than replacing the realm's profile configuration.
        profile = admin.request("GET", realm, "users/profile")
        known = {item["name"] for item in profile.get("attributes", [])}
        for name in ("tier", "device_pubkey_jwk", "device_encryption_pubkey_jwk", "employee_id", "phone"):
            if name not in known:
                profile.setdefault("attributes", []).append({"name": name, "multivalued": False,
                    "permissions": {"view": ["admin"], "edit": ["admin"]}})
        admin.request("PUT", realm, "users/profile", body=profile)
        print(f"Configured realm-scoped executor service account for {realm}", flush=True)
    # Prove steady-state service credentials work independently of bootstrap.
    steady = Keycloak(config)
    for realm in config["realms"]:
        employees = [u for u in steady.list_all(realm, "users") if not u.get("serviceAccountClientId")
                     and not u["username"].startswith("service-account-")]
        if len(employees) != 40:
            raise RuntimeError(f"Expected 40 synthetic employees in {realm}, got {len(employees)}")
    print("Executor client credentials verified for both realms", flush=True)


if __name__ == "__main__":
    provision()
