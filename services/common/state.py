"""Shared production/twin state normalization; never exports credential secrets."""

def without_secrets(value):
    if isinstance(value, list):
        return [without_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: without_secrets(item) for key, item in value.items()
                if not (key.lower().replace("_", "") in {"secretdata", "privatekey", "apikey"}
                        or key.lower().endswith(("secret", "password", "token")))}
    return value


def snapshot(kc, realm):
    representation = kc.request("GET", realm)
    users = {}
    employees = [u for u in kc.list_all(realm, "users", briefRepresentation="false")
                 if not u.get("serviceAccountClientId") and not u["username"].startswith("service-account-")]
    for user in employees:
        uid = user["id"]
        credentials = kc.request("GET", realm, f"users/{uid}/credentials")
        groups = kc.list_all(realm, f"users/{uid}/groups", briefRepresentation="false")
        mappings = kc.request("GET", realm, f"users/{uid}/role-mappings")
        brute = kc.request("GET", realm, f"attack-detection/brute-force/users/{uid}")
        users[uid] = {
            **{key: user.get(key) for key in ["id", "username", "firstName", "lastName", "email", "enabled", "emailVerified"]},
            "attributes": {key: sorted(value) for key, value in sorted(user.get("attributes", {}).items())},
            "requiredActions": sorted(user.get("requiredActions", [])),
            "groups": sorted(g["path"] for g in groups),
            "realmRoles": sorted(role["name"] for role in mappings.get("realmMappings", [])),
            "clientRoles": {client: sorted(role["name"] for role in data["mappings"])
                            for client, data in sorted(mappings.get("clientMappings", {}).items())},
            "credentials": {c["id"]: {key: c[key] for key in ["id", "type", "createdDate", "userLabel"] if key in c}
                            for c in sorted(credentials, key=lambda c: c["id"])},
            "bruteForce": brute,
        }
    groups = kc.list_all(realm, "groups", briefRepresentation="false")
    roles = kc.list_all(realm, "roles")
    clients = kc.request("GET", realm, "clients")
    normalized = {
        "realm": realm, "settings": without_secrets(representation), "users": dict(sorted(users.items())),
        "groups": {g["id"]: without_secrets(g) for g in sorted(groups, key=lambda g: g["id"])},
        "roles": {role["id"]: without_secrets(role) for role in sorted(roles, key=lambda r: r["id"])},
        "clients": {c["id"]: without_secrets(c) for c in sorted(clients, key=lambda c: c["id"])},
    }
    return normalized


