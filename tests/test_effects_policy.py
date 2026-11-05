import copy

from services.control.effects import compare_claims, derive, egress_effects
from services.control.policy import evaluate


def state():
    users = {}
    for uid, name, tier in [("sam", "sam.rivera", "standard"), ("dana", "dana.whitfield", "privileged")]:
        users[uid] = {"id": uid, "username": name, "email": name + "@acme.test", "enabled": True,
            "attributes": {"tier": [tier]}, "groups": [], "realmRoles": [], "clientRoles": {},
            "requiredActions": [], "bruteForce": {"disabled": False},
            "credentials": {"password-" + uid: {"id": "password-" + uid, "type": "password", "createdDate": 1},
                            "otp-" + uid: {"id": "otp-" + uid, "type": "otp"}}}
    return {"realm": "acme", "users": users, "settings": {}, "groups": {}, "roles": {}, "clients": {}}


def test_temporary_password_reset_is_one_effect_and_needs_sams_exact_device():
    before = state()
    after = copy.deepcopy(before)
    after["users"]["sam"]["credentials"]["password-sam"]["createdDate"] = 2
    after["users"]["sam"]["requiredActions"] = ["UPDATE_PASSWORD"]
    effects = derive(before, after)
    assert [e["type"] for e in effects] == ["user.password.reset"]
    assert evaluate(effects, before)["outcome"] == "DEVICE_REQUIRED"
    assert evaluate(effects, before, device_users=["sam.rivera"])["outcome"] == "AUTO"
    decision = evaluate(effects, before, device_users=["dana.whitfield"])
    assert decision["outcome"] == "HUMAN_REQUIRED" and "R8" in decision["rule_ids"]


def test_otp_removal_and_forged_downgrade_cannot_escape_privileged_seed_tier():
    before = state()
    after = copy.deepcopy(before)
    del after["users"]["dana"]["credentials"]["otp-dana"]
    after["users"]["dana"]["attributes"]["tier"] = ["standard"]
    effects = derive(before, after)
    decision = evaluate(effects, before, device_users=["dana.whitfield"])
    assert decision["requires_human"] and decision["requires_device"] == ["dana.whitfield"]
    assert {"R5", "R6"} <= set(decision["rule_ids"])
    assert any(row["mismatch"] for row in compare_claims(effects, [{"type": "user.password.reset", "username": "dana.whitfield"}]))


def test_compromise_and_egress_are_both_logged_and_first_reject_wins():
    effects = egress_effects("acme", [{"kind": "dns", "allowed": False, "host": "evil.test"}])
    decision = evaluate(effects, state(), compromised=True)
    assert decision["outcome"] == "REJECT"
    assert decision["rule_ids"] == ["R1", "R2"] and decision["first_reject"] == "R1"


def test_bulk_limit_and_risk_can_only_escalate():
    before = state()
    after = copy.deepcopy(before)
    after["users"]["sam"]["credentials"]["password-sam"]["createdDate"] = 2
    after["users"]["sam"]["requiredActions"] = ["UPDATE_PASSWORD"]
    effects = derive(before, after)
    assert evaluate(effects * 6, before)["first_reject"] == "R3"
    decision = evaluate(effects, before, device_users=["sam.rivera"], risk=0.6)
    assert decision["requires_human"] and "R9" in decision["rule_ids"]


def test_unknown_user_field_or_credential_deletion_is_never_silent():
    before = state()
    before["users"]["sam"]["credentials"]["new-kind"] = {"id": "new-kind", "type": "future-passkey"}
    after = copy.deepcopy(before)
    del after["users"]["sam"]["credentials"]["new-kind"]
    after["users"]["sam"]["username"] = "different-user"
    effects = derive(before, after)
    assert len(effects) == 2 and all(e["type"] == "realm.changed" for e in effects)
    assert evaluate(effects, before)["requires_human"]


def test_password_cas_uses_signed_production_metadata_after_clone_rehash():
    production = state()
    twin = copy.deepcopy(production)
    twin["users"]["sam"]["credentials"]["password-sam"]["createdDate"] = 100
    changed = copy.deepcopy(twin)
    changed["users"]["sam"]["credentials"]["password-sam"]["createdDate"] = 101
    changed["users"]["sam"]["requiredActions"] = ["UPDATE_PASSWORD"]
    effect = derive(twin, changed, production_before=production)[0]
    assert effect["before"]["credentials"]["password-sam"]["createdDate"] == 1


def test_client_secret_rotation_is_visible_without_exporting_its_value():
    before = state()
    before["clients"] = {"client": {"id": "client", "secret_fingerprint": "twin-original"}}
    after = copy.deepcopy(before)
    after["clients"]["client"]["secret_fingerprint"] = "twin-new"
    production = copy.deepcopy(before)
    production["clients"]["client"]["secret_fingerprint"] = "production-original"
    effects = derive(before, after, production_before=production)
    assert len(effects) == 1 and effects[0]["type"] == "client.secret.changed"
    assert effects[0]["before"]["fingerprint"] == "production-original"
    assert evaluate(effects, production)["requires_human"]
