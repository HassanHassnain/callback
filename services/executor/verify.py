"""Independent signature, policy-floor and CAS checks; never evaluates caller code."""

import json
from collections import Counter
from datetime import UTC, datetime

from services.common.contracts import original
from services.common.crypto import digest, verify
from services.common.sealed import public_key


class Refusal(RuntimeError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(detail)


def require(condition, code, detail):
    if not condition:
        raise Refusal(code, detail)


def validate_hash(request):
    change_set = original(request.change_set)
    actual = digest(change_set)
    require(actual == request.change_set_hash, "HASH_MISMATCH", "Canonical change-set hash differs from the submitted hash")
    require(all(s.payload.change_set_hash == actual for s in request.signatures),
            "HASH_MISMATCH", "A decision covers a different change-set hash")
    require(all(e.realm == request.change_set.realm for e in request.change_set.effects),
            "REALM_MISMATCH", "Effect realm differs from change-set realm")
    return change_set


def fresh(timestamp):
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        require(value.tzinfo is not None, "STALE_SIGNATURE", "Signature timestamp needs a timezone")
        age = (datetime.now(UTC) - value).total_seconds()
    except (ValueError, TypeError) as exc:
        raise Refusal("STALE_SIGNATURE", "Invalid signature timestamp") from exc
    require(-60 <= age <= 600, "STALE_SIGNATURE", "Decision is expired or too far in the future")


def registered(user, attribute):
    values = user.get("attributes", {}).get(attribute, [])
    require(len(values) == 1, "UNENROLLED_DEVICE", "Target has no single registered device key")
    try:
        jwk = json.loads(values[0])
        public_key(jwk)
    except (ValueError, KeyError, TypeError) as exc:
        raise Refusal("INVALID_DEVICE_KEY", "Production device public key is invalid") from exc
    return jwk


def verify_decisions(request, current, approvers):
    users = {u["username"]: u for u in current["users"].values()}
    affected = {e.target.username for e in request.change_set.effects if e.target.user_id}
    devices, operators, denials = set(), set(), []
    realm = request.change_set.realm
    for signed in request.signatures:
        payload = original(signed.payload)
        fresh(payload["ts"])
        if signed.kind == "device":
            require(payload.get("username") in users and payload.get("username") in affected and not payload.get("approver_id"),
                    "INVALID_SIGNATURE", "Device decision has an unknown or ambiguous identity")
            jwk = registered(users[payload["username"]], "device_pubkey_jwk")
        else:
            identifier = payload.get("approver_id")
            require(identifier in approvers and not payload.get("username"),
                    "UNKNOWN_APPROVER", "Approver key is not pinned")
            pinned = approvers[identifier]
            require(realm in pinned["realms"], "APPROVER_SCOPE", "Approver key is not allowed in this realm")
            jwk = pinned["public_key"]
        try:
            verify(jwk, payload, signed.signature)
        except Exception as exc:
            raise Refusal("INVALID_SIGNATURE", "Decision signature did not verify") from exc
        if payload["decision"] == "deny":
            denials.append({"kind": signed.kind, "identity": payload.get("username") or payload.get("approver_id")})
        elif signed.kind == "device":
            devices.add(payload["username"])
        else:
            operators.add(payload["approver_id"])
    return devices, operators, denials


SUPPORTED = {"user.password.reset", "credential.otp.removed", "user.required_action.added", "user.required_action.removed",
             "user.email.changed", "user.enabled.changed", "user.attribute.changed", "user.unlocked",
             "group.member.added", "group.member.removed", "role.granted", "role.revoked"}


def policy_floor(change_set, current, devices, operators):
    effects = change_set["effects"]
    require(bool(effects), "NO_CHANGE", "Empty change set cannot be applied")
    require(not any(e["type"] == "egress.attempted" for e in effects), "EGRESS_REJECTED", "Egress attempts are never applicable")
    targets = {e["target"]["user_id"] for e in effects if e["target"].get("user_id")}
    require(len(targets) <= 3 and all(n <= 5 for n in Counter(e["type"] for e in effects).values()),
            "BULK_REJECTED", "Bulk effect limit exceeded")
    require(all(e["type"] in SUPPORTED for e in effects), "UNSUPPORTED_EFFECT", "This executor cannot apply the requested effect type")
    human = False
    for effect in effects:
        uid = effect["target"]["user_id"]
        require(uid in current["users"], "UNKNOWN_TARGET", "Effect target does not exist in production")
        user = current["users"][uid]
        require(effect["target"]["username"] == user["username"], "TARGET_MISMATCH", "Target ID and username do not match production")
        kind, username = effect["type"], user["username"]
        tier = user.get("attributes", {}).get("tier", [])
        privileged = tier == ["privileged"] or bool(set(user.get("groups", [])) & {"/admins", "/executives"})
        standard = tier == ["standard"] and not privileged
        simple = kind in {"user.password.reset", "user.unlocked"} or (kind == "user.required_action.added" and effect["after"] == "CONFIGURE_TOTP")
        sensitive = kind in {"credential.otp.removed", "user.email.changed"} or (
            kind == "user.attribute.changed" and effect["after"]["attribute"] in {"phone", "device_pubkey_jwk", "device_encryption_pubkey_jwk", "tier"}) or (
            kind == "group.member.added" and effect["after"]["group"] in {"/admins", "/executives"})
        if privileged or sensitive or simple:
            require(username in devices, "DEVICE_REQUIRED", "Registered target device must approve this exact change set")
        if privileged or sensitive or not (standard and simple):
            human = True
        if kind == "user.password.reset":
            require(effect["after"] == {"changed": True, "temporary": True}, "INVALID_EFFECT", "Production resets must be temporary and executor-generated")
    require(not human or bool(operators), "APPROVER_REQUIRED", "A pinned human approver must approve this change set")
    return {"human_required": human, "verified_devices": sorted(devices), "verified_approvers": sorted(operators)}


def cas(change_set, current):
    require(digest(current) == change_set["prod_state_digest"], "DRIFT", "Production state differs from the signed seed")
    for effect in change_set["effects"]:
        require(effect_value(effect, current) == effect["before"], "DRIFT", "An effect precondition does not match production")


def effect_value(effect, current):
    user = current["users"][effect["target"]["user_id"]]
    kind, expected = effect["type"], effect["before"]
    if kind == "user.password.reset":
        actual = {"credentials": {k: v for k, v in user["credentials"].items() if v["type"] == "password"}}
    elif kind == "credential.otp.removed":
        actual = user["credentials"].get(expected["id"])
    elif kind == "user.email.changed":
        actual = user["email"]
    elif kind == "user.enabled.changed":
        actual = user["enabled"]
    elif kind == "user.attribute.changed":
        actual = {"attribute": expected["attribute"], "value": user["attributes"].get(expected["attribute"])}
    elif kind == "user.unlocked":
        actual = user["bruteForce"]
    elif kind.startswith("group.member."):
        actual = {"group": expected["group"], "member": expected["group"] in user["groups"]}
    elif kind.startswith("role."):
        scope = expected["scope"]
        roles = user["realmRoles"] if scope == "realm" else user["clientRoles"].get(scope.removeprefix("client:"), [])
        actual = {"scope": scope, "role": expected["role"], "granted": expected["role"] in roles}
    elif kind == "user.required_action.added":
        actual = None if effect["after"] not in user["requiredActions"] else effect["after"]
    else:
        actual = expected if expected in user["requiredActions"] else None
    return actual
