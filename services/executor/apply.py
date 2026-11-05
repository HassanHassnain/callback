"""Typed REST mutations, independent post-verify, reversible rollback, signed receipts."""

import copy
import json
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from services.common.contracts import original
from services.common.crypto import canonical, digest, public_jwk, sign
from services.common.sealed import seal
from services.common.state import snapshot
from services.control.effects import derive
from services.executor.keycloak import Keycloak
from services.executor.seed_export import EXPORT_LOCK, export_all, s3_client
from services.executor.verify import Refusal, cas, policy_floor, registered, require, validate_hash, verify_decisions

REVERSIBLE = {"user.email.changed", "user.enabled.changed", "user.attribute.changed", "group.member.added",
    "group.member.removed", "role.granted", "role.revoked", "user.required_action.added", "user.required_action.removed"}


def timestamp():
    return datetime.now(UTC).isoformat()


def core(effect):
    return {key: effect[key] for key in ["type", "realm", "target", "before", "after"]}


def same_effects(expected, actual):
    return sorted(digest(core(e)) for e in expected) == sorted(digest(core(e)) for e in actual)


def preflight(effects, current):
    require(len({e["id"] for e in effects}) == len(effects), "DUPLICATE_EFFECT", "Effect IDs must be unique")
    require(len({digest(core(e)) for e in effects}) == len(effects), "DUPLICATE_EFFECT", "Duplicate operations are not allowed")
    for effect in effects:
        kind, after = effect["type"], effect["after"]
        uid = effect["target"]["user_id"]
        if kind == "user.password.reset":
            registered(current["users"][uid], "device_encryption_pubkey_jwk")
        elif kind == "credential.otp.removed":
            require(effect["before"].get("type") == "otp" and after is None, "INVALID_EFFECT", "OTP removal payload is invalid")
            actions = current["users"][uid]["requiredActions"]
            require("CONFIGURE_TOTP" in actions or any(e["target"]["user_id"] == uid and e["type"] == "user.required_action.added"
                and e["after"] == "CONFIGURE_TOTP" for e in effects), "INVALID_EFFECT", "OTP removal requires an approved re-enrollment action")
        elif kind in {"user.required_action.added", "user.required_action.removed"}:
            action = after if kind.endswith("added") else effect["before"]
            require(action in {"CONFIGURE_TOTP", "UPDATE_PASSWORD", "VERIFY_EMAIL", "UPDATE_PROFILE", "TERMS_AND_CONDITIONS"},
                    "INVALID_EFFECT", "Unsupported required action")
        elif kind == "user.enabled.changed":
            require(type(after) is bool and type(effect["before"]) is bool, "INVALID_EFFECT", "Enabled state must be boolean")
        elif kind == "user.email.changed":
            require(isinstance(after, str) and len(after) <= 320 and "@" in after, "INVALID_EFFECT", "Email representation is invalid")
        elif kind == "user.attribute.changed":
            require(isinstance(after, dict) and set(after) == {"attribute", "value"}, "INVALID_EFFECT", "Invalid attribute effect")
            name, value = after["attribute"], after["value"]
            require(isinstance(name, str) and 0 < len(name) <= 128 and name not in {"email", "username", "credentials", "enabled", "groups", "requiredActions"},
                    "INVALID_EFFECT", "Attribute name is not allowed")
            require(value is None or (isinstance(value, list) and len(value) <= 10 and all(isinstance(v, str) and len(v) <= 4096 for v in value)),
                    "INVALID_EFFECT", "Attribute values must be bounded strings")
            if name == "tier":
                require(value in (["standard"], ["privileged"]), "INVALID_EFFECT", "Tier must remain authoritative")
        elif kind.startswith("group.member."):
            require(isinstance(after, dict) and set(after) == {"group", "member"} and type(after["member"]) is bool,
                    "INVALID_EFFECT", "Invalid membership effect")
            require(any(g.get("path") == after["group"] for g in current["groups"].values()), "UNKNOWN_GROUP", "Group does not exist in production")
        elif kind.startswith("role."):
            require(isinstance(after, dict) and set(after) == {"scope", "role", "granted"} and type(after["granted"]) is bool,
                    "INVALID_EFFECT", "Invalid role effect")
    # Preserve the fixture's security invariant rather than silently adding an
    # unapproved tier change when membership is elevated.
    prospective = copy.deepcopy(current["users"])
    for effect in effects:
        user = prospective[effect["target"]["user_id"]]
        if effect["type"] == "user.attribute.changed":
            name, value = effect["after"]["attribute"], effect["after"]["value"]
            if value is None:
                user["attributes"].pop(name, None)
            else:
                user["attributes"][name] = value
        if effect["type"].startswith("group.member."):
            group = effect["after"]["group"]
            user["groups"] = sorted((set(user["groups"]) | {group}) if effect["after"]["member"] else (set(user["groups"]) - {group}))
    for user in prospective.values():
        require(not (set(user["groups"]) & {"/admins", "/executives"}) or user["attributes"].get("tier") == ["privileged"],
                "TIER_INVARIANT", "Privileged membership needs an explicitly approved privileged tier")


def mutate(kc, realm, effect, current, temporary=None):
    kind, uid = effect["type"], effect["target"]["user_id"]
    path, after = "users/" + uid, effect["after"]
    if kind == "user.password.reset":
        kc.request("PUT", realm, path + "/reset-password", body={"type": "password", "temporary": True, "value": temporary})
    elif kind == "credential.otp.removed":
        kc.request("DELETE", realm, path + "/credentials/" + effect["before"]["id"])
    elif kind.startswith("user.required_action."):
        actions = set(kc.request("GET", realm, path).get("requiredActions", []))
        if kind.endswith("added"):
            actions.add(after)
        else:
            actions.discard(effect["before"])
        kc.request("PUT", realm, path, body={"requiredActions": sorted(actions)})
    elif kind == "user.email.changed":
        kc.request("PUT", realm, path, body={"email": after})
    elif kind == "user.enabled.changed":
        kc.request("PUT", realm, path, body={"enabled": after})
    elif kind == "user.attribute.changed":
        attributes = kc.request("GET", realm, path).get("attributes", {})
        if after["value"] is None:
            attributes.pop(after["attribute"], None)
        else:
            attributes[after["attribute"]] = after["value"]
        kc.request("PUT", realm, path, body={"attributes": attributes})
    elif kind == "user.unlocked":
        kc.request("DELETE", realm, "attack-detection/brute-force/users/" + uid)
    elif kind.startswith("group.member."):
        group = next(g for g in current["groups"].values() if g.get("path") == after["group"])
        kc.request("PUT" if after["member"] else "DELETE", realm, path + "/groups/" + group["id"])
    elif kind.startswith("role."):
        scope = after["scope"]
        if scope == "realm":
            role = next((r for r in current["roles"].values() if r["name"] == after["role"]), None)
            endpoint = path + "/role-mappings/realm"
        else:
            client = next((c for c in current["clients"].values() if c["clientId"] == scope.removeprefix("client:")), None)
            require(client is not None, "UNKNOWN_ROLE", "Role client does not exist")
            role = next((r for r in kc.request("GET", realm, "clients/" + client["id"] + "/roles") if r["name"] == after["role"]), None)
            endpoint = path + "/role-mappings/clients/" + client["id"]
        require(role is not None, "UNKNOWN_ROLE", "Role does not exist")
        kc.request("POST" if after["granted"] else "DELETE", realm, endpoint, body=[{"id": role["id"], "name": role["name"]}])


class ApplyService:
    def __init__(self, config, key):
        self.config, self.key = config, key
        self.root = Path(config["signing_key_path"]).parent
        self.db_path = self.root / "apply.sqlite3"
        self.receipts = self.root / "receipts"
        self.receipts.mkdir(exist_ok=True)
        with closing(self.db()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS executions (call_id TEXT PRIMARY KEY, hash TEXT, status TEXT, receipt_id TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS deliveries (call_id TEXT, username TEXT, realm TEXT, hash TEXT, box TEXT, PRIMARY KEY(call_id,username))")
        self.db_path.chmod(0o600)

    def db(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def receipt(self, request, status, *, before=None, after=None, reason=None, actual=None, rollback=None, trusted=False):
        rid = str(uuid.uuid4())
        payload = {"receipt_id": rid, "call_id": request.change_set.call_id, "realm": request.change_set.realm,
            "created_at": timestamp(), "status": status, "change_set_hash": request.change_set_hash,
            "prod_state_digest_before": digest(before) if before else None,
            "prod_state_digest_after": digest(after) if after else None,
            "reason": reason, "effects": original(request.change_set)["effects"] if trusted else [],
            "signatures": [original(s) for s in request.signatures] if trusted else [],
            "actual_effects": actual or [], "rollback": rollback or [],
            "verified": status == "APPLIED_VERIFIED", "context": request.context if trusted else {}}
        envelope = {"payload": payload, "signature": sign(self.key, payload), "signer_public_key": public_jwk(self.key)}
        path = self.receipts / (rid + ".json")
        path.write_bytes(canonical(envelope))
        path.chmod(0o600)
        storage_pending = False
        try:
            s3_client(self.config).put_object(Bucket=self.config["receipts_bucket"], Key=rid + ".json",
                Body=canonical(envelope), ContentType="application/json")
        except Exception:
            storage_pending = True
        return {"receipt": envelope, "storage_pending": storage_pending}

    def apply(self, request):
        with EXPORT_LOCK:
            before = None
            try:
                change_set = validate_hash(request)
                with closing(self.db()) as db:
                    prior = db.execute("SELECT hash,status,receipt_id FROM executions WHERE call_id=?", (change_set["call_id"],)).fetchone()
                if prior:
                    require(prior[0] == request.change_set_hash, "CALL_REPLAY", "Call ID already belongs to another hash")
                    require(prior[2] is not None, "INDETERMINATE", "Previous execution needs reconciliation; it will not be repeated")
                    return {"receipt": json.loads((self.receipts / (prior[2] + ".json")).read_text()), "idempotent": True}
                kc = Keycloak(self.config)
                try:
                    before = snapshot(kc, change_set["realm"])
                    approvers_path = self.root / "approvers.json"
                    approvers = json.loads(approvers_path.read_text()) if approvers_path.exists() else {}
                    devices, operators, denials = verify_decisions(request, before, approvers)
                    if denials:
                        result = self.receipt(request, "DENIED", before=before, after=before,
                            reason={"code": "SIGNED_DENIAL", "actors": denials}, trusted=True)
                        self.finish(change_set, "DENIED", result)
                        return result
                    require(request.context.get("call_status") != "COMPROMISED", "COMPROMISED", "Compromised calls are never applicable")
                    policy_floor(change_set, before, devices, operators)
                    cas(change_set, before)
                    preflight(change_set["effects"], before)
                    with closing(self.db()) as db, db:
                        db.execute("INSERT INTO executions VALUES (?,?,?,NULL)", (change_set["call_id"], request.change_set_hash, "STARTED"))
                    try:
                        for effect in change_set["effects"]:
                            temporary = None
                            if effect["type"] == "user.password.reset":
                                user = before["users"][effect["target"]["user_id"]]
                                encryption_key = registered(user, "device_encryption_pubkey_jwk")
                                temporary = secrets.token_urlsafe(24)
                                binding = {"call_id": change_set["call_id"], "realm": change_set["realm"],
                                           "username": user["username"], "change_set_hash": request.change_set_hash}
                                box = seal(encryption_key, {"temporary_password": temporary, "required_action": "UPDATE_PASSWORD"}, binding)
                                with closing(self.db()) as db, db:
                                    db.execute("INSERT INTO deliveries VALUES (?,?,?,?,?)", (change_set["call_id"], user["username"],
                                        change_set["realm"], request.change_set_hash, json.dumps(box)))
                            mutate(kc, change_set["realm"], effect, before, temporary)
                        after = snapshot(kc, change_set["realm"])
                        actual = derive(before, after, production_before=before)
                        require(same_effects(change_set["effects"], actual), "FAILED_VERIFY", "Production post-state differs from the approved effects")
                    except Exception as exc:
                        rollback = []
                        for effect in reversed(change_set["effects"]):
                            if effect["type"] not in REVERSIBLE:
                                rollback.append({"effect_id": effect["id"], "reverted": False, "reason": "Irreversible through provider API"})
                                continue
                            inverse = copy.deepcopy(effect)
                            inverse["before"], inverse["after"] = effect["after"], effect["before"]
                            if effect["type"].startswith("user.required_action."):
                                inverse["type"] = "user.required_action.removed" if effect["type"].endswith("added") else "user.required_action.added"
                            try:
                                mutate(kc, change_set["realm"], inverse, before)
                                rollback.append({"effect_id": effect["id"], "reverted": True})
                            except Exception:
                                rollback.append({"effect_id": effect["id"], "reverted": False, "reason": "Provider rollback failed"})
                        after = snapshot(kc, change_set["realm"])
                        result = self.receipt(request, "FAILED_VERIFY", before=before, after=after,
                            reason={"code": "FAILED_VERIFY", "error_type": type(exc).__name__, "alarm": True},
                            actual=derive(before, after, production_before=before), rollback=rollback, trusted=True)
                        self.finish(change_set, "FAILED_VERIFY", result)
                        return result
                    result = self.receipt(request, "APPLIED_VERIFIED", before=before, after=after, actual=actual, trusted=True)
                    self.finish(change_set, "APPLIED_VERIFIED", result)
                    try:
                        export_all(kc, self.config)
                    except Exception:
                        result["seed_export_pending"] = True
                    return result
                finally:
                    kc.client.close()
            except Refusal as exc:
                return self.receipt(request, "REFUSED", before=before, after=before,
                    reason={"code": exc.code, "detail": exc.detail})

    def finish(self, change_set, status, result):
        with closing(self.db()) as db, db:
            db.execute("INSERT INTO executions VALUES (?,?,?,?) ON CONFLICT(call_id) DO UPDATE SET status=excluded.status,receipt_id=excluded.receipt_id",
                (change_set["call_id"], digest(change_set), status, result["receipt"]["payload"]["receipt_id"]))
        try:
            s3_client(self.config).put_object(Bucket=self.config["receipts_bucket"], Key=change_set["call_id"] + ".json",
                Body=canonical(result["receipt"]), ContentType="application/json")
        except Exception:
            result["storage_pending"] = True
