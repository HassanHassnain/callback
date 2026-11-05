"""Derive typed effects from trusted snapshots, independent of agent claims."""

from collections import Counter
from datetime import UTC, datetime

from services.common.crypto import digest


def derive(before, after, *, tool_call_ids=()):
    if before["realm"] != after["realm"]:
        raise ValueError("Cannot compare different realms")
    realm, effects = before["realm"], []

    def add(kind, user, old, new, reversible=True):
        effect = {"type": kind, "realm": realm,
                  "target": {"user_id": user.get("id"), "username": user.get("username")},
                  "before": old, "after": new, "reversible": reversible,
                  "evidence": {"tool_call_ids": list(tool_call_ids)}}
        if not reversible:
            effect["irreversible_reason"] = "Original credential material is never exported"
        effect["id"] = digest({k: v for k, v in effect.items() if k != "evidence"})[:24]
        effects.append(effect)

    for uid in sorted(before["users"].keys() | after["users"].keys()):
        old, new = before["users"].get(uid), after["users"].get(uid)
        if old is None:
            add("user.created", new, None, new)
            continue
        if new is None:
            add("user.deleted", old, old, None, False)
            continue
        for field, kind in [("enabled", "user.enabled.changed"), ("email", "user.email.changed")]:
            if old.get(field) != new.get(field):
                add(kind, old, old.get(field), new.get(field))
        for attr in sorted(old["attributes"].keys() | new["attributes"].keys()):
            a, b = old["attributes"].get(attr), new["attributes"].get(attr)
            if a != b:
                add("user.attribute.changed", old, {"attribute": attr, "value": a},
                    {"attribute": attr, "value": b})
        password_before = {k: v for k, v in old["credentials"].items() if v["type"] == "password"}
        password_after = {k: v for k, v in new["credentials"].items() if v["type"] == "password"}
        password_changed = password_before != password_after
        if password_changed:
            add("user.password.reset", old, {"credentials": password_before},
                {"changed": True, "temporary": "UPDATE_PASSWORD" in new["requiredActions"]}, False)
        for cid, credential in old["credentials"].items():
            if credential["type"] == "otp" and cid not in new["credentials"]:
                add("credential.otp.removed", old, credential, None, False)
        # Every credential delta not represented above remains visible and gated.
        known_before = {k: v for k, v in old["credentials"].items() if v["type"] not in {"otp", "password"}}
        known_after = {k: v for k, v in new["credentials"].items() if v["type"] != "password"
                       and not (v["type"] == "otp" and k in old["credentials"] and v == old["credentials"][k])}
        for cid in sorted(known_before.keys() | known_after.keys()):
            value = known_after.get(cid)
            if known_before.get(cid) != value:
                add("realm.changed", old, {"path": f"users/{uid}/credentials/{cid}", "value": old["credentials"].get(cid)},
                    {"path": f"users/{uid}/credentials/{cid}", "value": value})
        for action in sorted(set(old["requiredActions"]) ^ set(new["requiredActions"])):
            if password_changed and action == "UPDATE_PASSWORD" and action in new["requiredActions"]:
                continue  # Temporary-password flag is part of the reset itself.
            added = action in new["requiredActions"]
            add("user.required_action." + ("added" if added else "removed"), old,
                None if added else action, action if added else None)
        for group in sorted(set(old["groups"]) ^ set(new["groups"])):
            member = group in new["groups"]
            add("group.member." + ("added" if member else "removed"), old,
                {"group": group, "member": not member}, {"group": group, "member": member})
        scopes = {"realm": (old["realmRoles"], new["realmRoles"])}
        scopes.update({"client:" + c: (old["clientRoles"].get(c, []), new["clientRoles"].get(c, []))
                       for c in old["clientRoles"].keys() | new["clientRoles"].keys()})
        for scope, (a, b) in sorted(scopes.items()):
            for role in sorted(set(a) ^ set(b)):
                granted = role in b
                add("role." + ("granted" if granted else "revoked"), old,
                    {"scope": scope, "role": role, "granted": not granted},
                    {"scope": scope, "role": role, "granted": granted})
        if old.get("bruteForce") != new.get("bruteForce"):
            unlocked = old.get("bruteForce", {}).get("disabled") and not new.get("bruteForce", {}).get("disabled")
            add("user.unlocked" if unlocked else "realm.changed", old,
                old.get("bruteForce"), new.get("bruteForce"))
        covered = {"id", "enabled", "email", "attributes", "credentials", "requiredActions",
                   "groups", "realmRoles", "clientRoles", "bruteForce"}
        for field in sorted(old.keys() | new.keys()):
            if field not in covered and old.get(field) != new.get(field):
                add("realm.changed", old, {"path": f"users/{uid}/{field}", "value": old.get(field)},
                    {"path": f"users/{uid}/{field}", "value": new.get(field)})
    for section in ["settings", "groups", "roles", "clients"]:
        if before.get(section) != after.get(section):
            add("realm.changed", {}, {"path": section, "value": before.get(section)},
                {"path": section, "value": after.get(section)})
    return effects


def egress_effects(realm, events):
    results = []
    for event in events:
        if event["kind"] not in {"http", "dns"} or event.get("allowed"):
            continue
        effect = {"type": "egress.attempted", "realm": realm, "target": {"user_id": None, "username": None},
                  "before": None, "after": event, "reversible": False,
                  "irreversible_reason": "Network attempts cannot be applied to identity production",
                  "evidence": {"tool_call_ids": []}}
        effect["id"] = digest(effect)[:24]
        results.append(effect)
    return results


def change_set(call, effects):
    return {"call_id": call["call_id"], "realm": call["realm"], "seed_version": call["seed_version"],
            "prod_state_digest": call["prod_state_digest"], "effects": effects,
            "created_at": datetime.now(UTC).isoformat()}


def compare_claims(effects, claims):
    counts = Counter((e["type"], e["target"].get("username")) for e in effects)
    declared = Counter((c["type"], c.get("username")) for c in claims)
    return [{"effect_id": e["id"], "mismatch": declared[(e["type"], e["target"].get("username"))] < counts[(e["type"], e["target"].get("username"))]}
            for e in effects]
