"""Create deterministic synthetic people; production credentials are generated on executor."""

import json
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    "Dana Whitfield", "Sam Rivera", "Priya Nair", "Marcus Chen", "Aisha Patel",
    "Leo Martinez", "Nina Brooks", "Owen Reed", "Maya Gupta", "Theo Kim",
    "Zoe Turner", "Ethan Wright", "Sofia Lopez", "Noah Clark", "Grace Hughes",
    "Elena Ward", "Isaac Morgan", "Ava Bennett", "Liam Foster", "Olivia Scott",
    "Lucas Reyes", "Chloe Adams", "Daniel Park", "Amara Okafor", "Henry Walsh",
    "Layla Hassan", "Julian Ross", "Mila Carter", "Arjun Mehta", "Alice Green",
    "David Stone", "Sara Ali", "Ben Miller", "Fatima Khan", "Eli Rivers",
    "Yuna Sato", "Hugo Diaz", "Emma Wilson", "Ryan Cole", "Leah Price",
]
ADMIN_INDICES = {0, *range(2, 15)}
EXEC_INDICES = {0, 15, 19}


def build():
    users = []
    directory = []
    for i, name in enumerate(NAMES):
        first, last = name.split()
        username = name.lower().replace(" ", ".")
        department = ("finance" if i == 0 or 10 <= i <= 14 else "engineering") if i in ADMIN_INDICES else [
            "sales", "engineering", "finance", "sales"][i % 4]
        if i == 1:
            department = "sales"
        groups = [department]
        if i in ADMIN_INDICES:
            groups.append("admins")
        if i in EXEC_INDICES:
            groups.append("executives")
        privileged = i in ADMIN_INDICES or i in EXEC_INDICES
        title = {0: "Chief Financial Officer", 1: "Sales Associate", 2: "IT Administrator",
                 15: "Chief Executive Officer", 19: "VP Operations"}.get(i,
                    "Identity Administrator" if i in ADMIN_INDICES else department.title() + " Specialist")
        employee_id = f"ACME-{1001 + i}"
        users.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "callback:acme:" + username)),
                      "username": username, "firstName": first, "lastName": last,
                      "email": username + "@acme.example", "emailVerified": True, "enabled": True,
                      "attributes": {"tier": ["privileged" if privileged else "standard"],
                                     "employee_id": [employee_id]},
                      "groups": sorted(groups), "requiredActions": [],
                      "fixture_otp_enabled": privileged or i % 2 == 0})
        directory.append({"employee_id": employee_id, "username": username, "name": name,
                          "title": title, "department": department,
                          "manager": "Elena Ward" if privileged else "Ava Bennett",
                          "masked_phone": f"+1 ••• ••• {100 + i:04d}",
                          "location": ["Seattle", "Chicago", "Austin", "Remote"][i % 4]})
    realm = {"realm": "acme", "displayName": "Acme — synthetic demo organization", "enabled": True,
             "registrationAllowed": False, "resetPasswordAllowed": False, "sslRequired": "all",
             "groups": [{"name": name} for name in ["admins", "finance", "engineering", "sales", "executives"]],
             "users": users}
    for path, data in [("realm_acme.json", realm), ("hr_directory.json", {
        "synthetic": True, "authoritative_for_tier": False, "employees": directory,
    })]:
        (ROOT / "fixtures" / path).write_text(json.dumps(data, indent=2) + "\n")
    personas = {"synthetic": True, "personas": [
        {"username": "dana.whitfield", "tier": "privileged", "scenario": "lost-phone MFA reset", "otp": True},
        {"username": "sam.rivera", "tier": "standard", "scenario": "legitimate password reset", "otp": False},
        {"username": "priya.nair", "tier": "privileged", "scenario": "IT administrator", "otp": True},
    ]}
    (ROOT / "fixtures/personas.yaml").write_text(yaml.safe_dump(personas, sort_keys=False))
    assert len(users) == 40
    assert sum("admins" in u["groups"] for u in users) == 14
    print("Built 40 synthetic employees, including 14 admins; no production credentials in fixtures.")


if __name__ == "__main__":
    build()
