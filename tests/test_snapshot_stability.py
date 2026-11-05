from services.common.state import snapshot
from services.control.effects import derive


class KeycloakFixture:
    def __init__(self, scopes):
        self.scopes = scopes

    def request(self, method, realm, endpoint="", **kwargs):
        if endpoint == "clients":
            return [{"id": "client", "publicClient": True, "defaultClientScopes": self.scopes}]
        return {}

    def list_all(self, *args, **kwargs):
        return []


def test_unordered_client_scopes_cannot_create_a_false_realm_effect():
    before = snapshot(KeycloakFixture(["web-origins", "service_account", "profile"]), "acme")
    after = snapshot(KeycloakFixture(["service_account", "profile", "web-origins"]), "acme")
    assert before == after
    assert derive(before, after) == []
