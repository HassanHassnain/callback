import hashlib
import json

import pytest

from services.executor.seed_export import assert_scrubbed, audit_database_hashes, build_seed, without_secrets


def snapshot_fixture():
    return {"realm": "acme", "settings": {}, "groups": {}, "roles": {}, "clients": {
        "c1": {"id": "c1", "clientId": "callback-executor", "publicClient": False}},
        "users": {"u1": {"id": "u1", "username": "dana.whitfield", "firstName": "Dana",
            "lastName": "Whitfield", "email": "dana@acme.example", "enabled": True,
            "emailVerified": True, "attributes": {"tier": ["privileged"]}, "requiredActions": [],
            "groups": ["/admins"], "realmRoles": [], "clientRoles": {}, "credentials": {
                "p1": {"id": "p1", "type": "password", "createdDate": 1},
                "o1": {"id": "o1", "type": "otp", "createdDate": 2}}}}}


def test_seed_replaces_credentials_and_preserves_metadata_ids():
    seed = build_seed(snapshot_fixture())
    credentials = seed["realm_import"]["users"][0]["credentials"]
    assert {c["id"] for c in credentials} == {"p1", "o1"}
    assert not any("secretData" in c for c in credentials if c["type"] == "password")
    assert json.loads(credentials[1]["secretData"])["value"]
    assert seed["realm_import"]["clients"][0]["secret"]
    assert assert_scrubbed(seed, {}, "synthetic-real-client-secret")["initial_secrets_reused"] is False


def test_seed_rejects_a_reused_production_otp_or_client_secret():
    seed = build_seed(snapshot_fixture())
    otp = seed["realm_import"]["users"][0]["credentials"][1]
    value = json.loads(otp["secretData"])["value"]
    audit = {"initial_secret_value_sha256": [hashlib.sha256(value.encode()).hexdigest()]}
    with pytest.raises(RuntimeError, match="reused"):
        assert_scrubbed(seed, audit, "synthetic-real-client-secret")
    seed["realm_import"]["clients"][0]["secret"] = "synthetic-real-client-secret"
    with pytest.raises(RuntimeError, match="material"):
        assert_scrubbed(seed, {}, "synthetic-real-client-secret")


def test_secret_scrub_preserves_security_policy_fields_for_state_diff():
    value = {"passwordPolicy": "length(12)", "resetPasswordAllowed": False,
             "smtpServer": {"password": "synthetic-password", "host": "smtp.example"},
             "clientSecret": "synthetic-client-secret", "privateKey": "synthetic-private-key"}
    assert without_secrets(value) == {"passwordPolicy": "length(12)", "resetPasswordAllowed": False,
                                       "smtpServer": {"host": "smtp.example"}}


def test_database_secret_data_hash_comparison_rejects_reused_otp():
    seed = build_seed(snapshot_fixture())
    credential = seed["realm_import"]["users"][0]["credentials"][1]
    metadata = [{"id": "p1", "secret_data_sha256": "irrelevant"},
                {"id": "o1", "secret_data_sha256": hashlib.sha256(credential["secretData"].encode()).hexdigest()}]
    with pytest.raises(RuntimeError, match="OTP"):
        audit_database_hashes(seed, metadata)


def test_seed_preserves_user_profile_and_bearer_only_client_configuration():
    state = snapshot_fixture()
    state["userProfile"] = {"attributes": [{"name": "tier", "permissions": {"view": ["admin"], "edit": ["admin"]}}]}
    state["clients"]["builtin"] = {"id": "builtin", "clientId": "realm-management", "bearerOnly": True,
        "publicClient": False, "directAccessGrantsEnabled": False}
    seed = build_seed(state)
    assert seed["user_profile"] == state["userProfile"]
    builtin = next(c for c in seed["realm_import"]["clients"] if c["id"] == "builtin")
    assert builtin["bearerOnly"] and "secret" not in builtin
