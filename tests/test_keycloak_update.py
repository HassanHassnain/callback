"""Regression: sparse user PUT clears root profile fields in current Keycloak."""
import copy

from services.executor.keycloak import update_user


def test_typed_update_preserves_profile_but_never_replays_credentials_or_access():
    before = {"id": "u", "username": "sam.rivera", "firstName": "Sam", "lastName": "Rivera",
        "email": "sam@acme.test", "emailVerified": True, "enabled": True, "attributes": {"tier": ["standard"]},
        "requiredActions": [], "credentials": [{"secretData": "never-copy"}], "access": {"manage": True}}
    class Fake:
        def request(self, method, realm, path, body=None):
            if method == "GET":
                return copy.deepcopy(before)
            self.body = body
    kc = Fake()
    update_user(kc, "acme-guest", "u", {"requiredActions": ["CONFIGURE_TOTP"]})
    assert kc.body["email"] == before["email"] and kc.body["firstName"] == "Sam"
    assert kc.body["attributes"] == before["attributes"] and kc.body["enabled"]
    assert kc.body["requiredActions"] == ["CONFIGURE_TOTP"]
    assert "credentials" not in kc.body and "access" not in kc.body
