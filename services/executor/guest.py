"""Lease the three designated synthetic judge slots, scoped to acme-guest."""

import json
import secrets
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from services.common.crypto import canonical, digest, verify
from services.common.state import snapshot
from services.executor.enrollment import validate_bundle
from services.executor.keycloak import Keycloak, update_user
from services.executor.seed_export import EXPORT_LOCK
from services.executor.verify import fresh, require

REALM = "acme-guest"
SLOTS = {"isaac.morgan", "ava.bennett", "liam.foster"}
KEY_ATTRIBUTES = {"device_pubkey_jwk", "device_encryption_pubkey_jwk"}
LEASE_SECONDS = 1200


def state_path(config):
    return Path(config["signing_key_path"]).parent / "guest-slots.json"


def read(config):
    path = state_path(config)
    return json.loads(path.read_text()) if path.exists() else {"slots": {}, "last_nightly_reset": None}


def save(config, state):
    path = state_path(config)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(canonical(state))
    temp.chmod(0o600)
    temp.replace(path)


def scoped_digest(current, user_id):
    return digest({"realm": current["realm"], "user": current["users"][user_id],
                   "settings": current["settings"], "groups": current["groups"], "roles": current["roles"],
                   "userProfile": current["userProfile"]})


def lease(config, bundle):
    payload = validate_bundle(bundle)
    username = payload["identity"]
    require(payload["realm"] == REALM and payload["kind"] == "device" and username in SLOTS,
            "GUEST_SCOPE", "Guest enrollment is restricted to the designated synthetic device slots")
    with EXPORT_LOCK:
        state = read(config)
        existing = state["slots"].get(username)
        if existing and not existing["enrolling"] and existing["expires_at"] > time.time():
            require(existing["signing_key"] == payload["public_key"] and existing["encryption_key"] == payload["encryption_public_key"],
                    "GUEST_BUSY", "This guest slot is already in use")
            return existing
        kc = Keycloak(config)
        try:
            if existing:
                reset_slot(kc, username, existing)
                state["slots"].pop(username)
                save(config, state)
            initial = snapshot(kc, REALM)
            user = next((user for user in initial["users"].values() if user["username"] == username), None)
            require(user is not None and user["attributes"].get("tier") == ["standard"]
                    and not set(user["groups"]) & {"/admins", "/executives"}
                    and not KEY_ATTRIBUTES & user["attributes"].keys(),
                    "GUEST_SCOPE", "The guest slot is unavailable or already has a registered device")
            attrs = {**user["attributes"], "device_pubkey_jwk": [canonical(payload["public_key"]).decode()],
                     "device_encryption_pubkey_jwk": [canonical(payload["encryption_public_key"]).decode()]}
            entry = {"id": str(uuid.uuid4()), "username": username, "user_id": user["id"],
                     "signing_key": payload["public_key"], "encryption_key": payload["encryption_public_key"],
                     "expires_at": int(time.time()) + LEASE_SECONDS,
                     "required_actions_before": user["requiredActions"], "enrolling": True}
            state["slots"][username] = entry
            save(config, state)
            update_user(kc, REALM, user["id"], {"attributes": attrs})
            current = snapshot(kc, REALM)
            entry["user_state"] = current["users"][user["id"]]
            require(all(entry["user_state"]["attributes"].get(attr) == attrs[attr] for attr in KEY_ATTRIBUTES),
                    "GUEST_ENROLLMENT", "Guest key registration did not verify")
            entry["scope_digest"] = scoped_digest(current, user["id"])
            entry["enrolling"] = False
            save(config, state)
            return entry
        except Exception:
            entry = state["slots"].get(username)
            if entry and entry.get("enrolling"):
                entry["expires_at"] = 0
                save(config, state)
            raise
        finally:
            kc.client.close()


def check_apply(config, change_set, current):
    require(change_set["realm"] == REALM, "GUEST_SCOPE", "Guest proof is valid only in the synthetic guest realm")
    effects = change_set["effects"]
    require(len(effects) == 1 and effects[0]["type"] == "user.password.reset",
            "GUEST_SCOPE", "Guest judges can approve only one temporary reset for their own slot")
    effect = effects[0]
    uid = effect["target"]["user_id"]
    username = effect["target"]["username"]
    entry = read(config)["slots"].get(username)
    require(username in SLOTS and entry and entry["id"] == change_set["guest_lease"] and entry["user_id"] == uid
            and not entry["enrolling"] and entry["expires_at"] > time.time(),
            "GUEST_SCOPE", "The guest lease expired or does not match the effect target")
    return scoped_digest(current, uid)


def reset_slot(kc, username, entry):
    uid = entry["user_id"]
    user = kc.request("GET", REALM, "users/" + uid)
    attrs = user.get("attributes", {})
    require(username in SLOTS and user["username"] == username and attrs.get("tier") == ["standard"],
            "GUEST_SCOPE", "Refusing to reset a different user")
    for attr, field in [("device_pubkey_jwk", "signing_key"), ("device_encryption_pubkey_jwk", "encryption_key")]:
        value = [canonical(entry[field]).decode()]
        require(not attrs.get(attr) or attrs[attr] == value, "GUEST_SCOPE", "Device key changed since enrollment")
        attrs.pop(attr, None)
    kc.request("PUT", REALM, "users/" + uid + "/reset-password", body={
        "type": "password", "temporary": False, "value": secrets.token_urlsafe(32)})
    update_user(kc, REALM, uid, {"attributes": attrs, "requiredActions": entry["required_actions_before"]})


def reset(config, proof):
    payload = proof["payload"]
    require(set(payload) == {"purpose", "realm", "username", "lease_id", "ts"}
            and payload["purpose"] == "guest_reset" and payload["realm"] == REALM,
            "GUEST_SCOPE", "Invalid guest reset proof")
    fresh(payload["ts"])
    with EXPORT_LOCK:
        state = read(config)
        username = payload["username"]
        entry = state["slots"].get(username)
        require(entry and entry["id"] == payload["lease_id"], "GUEST_SCOPE", "The guest lease no longer exists")
        verify(entry["signing_key"], payload, proof["signature"])
        kc = Keycloak(config)
        try:
            reset_slot(kc, username, entry)
            state["slots"].pop(username)
            save(config, state)
        finally:
            kc.client.close()
    return {"reset": True}


def nightly(config):
    with EXPORT_LOCK:
        state = read(config)
        day = datetime.now(UTC).date().isoformat()
        if state["last_nightly_reset"] == day and not any(
                entry["expires_at"] <= time.time() for entry in state["slots"].values()):
            return
        kc = Keycloak(config)
        try:
            for username, entry in list(state["slots"].items()):
                if entry["expires_at"] <= time.time():
                    reset_slot(kc, username, entry)
                    state["slots"].pop(username)
                    save(config, state)
            if not state["slots"]:
                state["last_nightly_reset"] = day
                save(config, state)
        finally:
            kc.client.close()
