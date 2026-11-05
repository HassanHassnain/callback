"""Deterministic rules. Risk signals may escalate; seed tier is authoritative."""

from collections import Counter


def evaluate(effects, seed_state, *, compromised=False, device_users=(), risk=0, moderation=False):
    rules, reject = [], []
    if compromised:
        reject.append("R1")
    if any(e["type"] == "egress.attempted" for e in effects):
        reject.append("R2")
    users = {e["target"]["user_id"] for e in effects if e["target"].get("user_id")}
    if len(users) > 3 or any(n > 5 for n in Counter(e["type"] for e in effects).values()):
        reject.append("R3")
    if reject:
        return {"outcome": "REJECT", "rule_ids": reject, "requires_device": [], "requires_human": False,
                "first_reject": reject[0]}
    human, device, auto = False, set(), bool(effects)
    for effect in effects:
        kind, uid = effect["type"], effect["target"].get("user_id")
        user = seed_state["users"].get(uid, {})
        username = user.get("username", effect["target"].get("username"))
        tier = user.get("attributes", {}).get("tier", [None])
        standard = tier == ["standard"]
        if kind in {"realm.changed", "user.created", "user.deleted", "client.secret.changed", "role.granted"}:
            rules.append("R4")
            human = True
        if tier == ["privileged"]:
            rules.append("R5")
            device.add(username)
            human = True
        sensitive = (kind in {"credential.otp.removed", "user.email.changed"}
            or (kind == "user.attribute.changed" and effect["after"]["attribute"] in {"phone", "device_pubkey_jwk", "tier"})
            or (kind == "group.member.added" and effect["after"]["group"] in {"/admins", "/executives"}))
        if sensitive:
            rules.append("R6")
            device.add(username)
            human = True
        auto_kind = kind in {"user.password.reset", "user.unlocked"} or (
            kind == "user.required_action.added" and effect["after"] == "CONFIGURE_TOTP")
        if kind == "user.password.reset" and effect["after"].get("temporary") is not True:
            auto_kind = False
        if standard and auto_kind:
            rules.append("R7")
            device.add(username)
        else:
            auto = False
        if device_users and username not in device_users:
            rules.append("R8")
            human = True
    if risk >= 0.6 or moderation:
        rules.append("R9")
        human = True
    if not auto and not human:
        rules.append("DEFAULT")
        human = True
    if not effects:
        return {"outcome": "NO_CHANGE", "rule_ids": [], "requires_device": [], "requires_human": False}
    return {"outcome": "HUMAN_REQUIRED" if human else ("AUTO" if device <= set(device_users) else "DEVICE_REQUIRED"),
            "auto_eligible": auto and not human, "rule_ids": list(dict.fromkeys(rules)),
            "requires_device": sorted(device - {None}), "requires_human": human}
