"""SSH-only public-key pinning. No private device key ever leaves its browser."""

import argparse
import json
import uuid
from pathlib import Path

from services.common.crypto import canonical, digest, verify
from services.common.sealed import public_key
from services.executor.keycloak import Keycloak, config_from_file, update_user
from services.executor.seed_export import EXPORT_LOCK, export_all
from services.executor.verify import fresh, require


def validate_bundle(bundle, *, check_time=True):
    require(set(bundle) == {"payload", "signature"}, "INVALID_ENROLLMENT", "Unexpected enrollment fields")
    payload = bundle["payload"]
    kind = payload.get("kind")
    fields = {"kind", "realm", "identity", "public_key", "ts", "nonce"}
    if kind == "device":
        fields.add("encryption_public_key")
    require(kind in {"device", "approver"} and set(payload) == fields, "INVALID_ENROLLMENT", "Invalid enrollment payload")
    require(payload["realm"] in {"acme", "acme-guest"}, "INVALID_ENROLLMENT", "Invalid realm")
    require(isinstance(payload["identity"], str) and 0 < len(payload["identity"]) <= 128,
            "INVALID_ENROLLMENT", "Invalid identity")
    require(len(payload["nonce"]) == 36, "INVALID_ENROLLMENT", "Invalid enrollment nonce")
    uuid.UUID(payload["nonce"])
    if check_time:
        fresh(payload["ts"])
    public_key(payload["public_key"])
    if kind == "device":
        public_key(payload["encryption_public_key"])
    verify(payload["public_key"], payload, bundle["signature"])
    return payload


def pin(bundle, config):
    payload = validate_bundle(bundle, check_time=False)
    root = Path(config["signing_key_path"]).parent
    with EXPORT_LOCK:
        if payload["kind"] == "approver":
            path = root / "approvers.json"
            data = json.loads(path.read_text()) if path.exists() else {}
            item = {"public_key": payload["public_key"], "realms": [payload["realm"]]}
            require(payload["identity"] not in data or data[payload["identity"]] == item,
                    "KEY_ALREADY_PINNED", "Existing approver key is preserved; use a new identity")
            data[payload["identity"]] = item
            path.write_bytes(canonical(data))
            path.chmod(0o600)
        else:
            kc = Keycloak(config)
            try:
                realm = payload["realm"]
                users = kc.request("GET", realm, "users", params={"username": payload["identity"], "exact": "true"})
                require(len(users) == 1, "UNKNOWN_TARGET", "Exact employee not found")
                profile = kc.request("GET", realm, "users/profile")
                known = {a["name"] for a in profile.get("attributes", [])}
                for name in ["device_pubkey_jwk", "device_encryption_pubkey_jwk"]:
                    if name not in known:
                        profile.setdefault("attributes", []).append({"name": name, "multivalued": False,
                            "permissions": {"view": ["admin"], "edit": ["admin"]}})
                kc.request("PUT", realm, "users/profile", body=profile)
                user = kc.request("GET", realm, "users/" + users[0]["id"])
                attrs = user.get("attributes", {})
                for attr, field in [("device_pubkey_jwk", "public_key"), ("device_encryption_pubkey_jwk", "encryption_public_key")]:
                    value = canonical(payload[field]).decode()
                    require(not attrs.get(attr) or attrs[attr] == [value], "KEY_ALREADY_PINNED",
                            "Existing device key is preserved; replacement requires a separate reviewed ceremony")
                    attrs[attr] = [value]
                update_user(kc, realm, user["id"], {"attributes": attrs})
                updated = kc.request("GET", realm, "users/" + user["id"])
                require(all(updated["attributes"].get(a) == attrs[a] for a in ["device_pubkey_jwk", "device_encryption_pubkey_jwk"]),
                        "ENROLLMENT_VERIFY", "Production public-key readback failed")
                export_all(kc, config)
            finally:
                kc.client.close()
        history = root / "enrollments"
        history.mkdir(exist_ok=True)
        path = history / (digest(payload) + ".json")
        path.write_bytes(canonical(bundle))
        path.chmod(0o600)
    return {"pinned": True, "kind": payload["kind"], "realm": payload["realm"],
            "identity": payload["identity"], "fingerprint": digest(payload["public_key"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args()
    print(json.dumps(pin(json.loads(Path(args.bundle).read_text()), config_from_file())))
