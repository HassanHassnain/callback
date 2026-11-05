"""Verify P2 against real Keycloak metadata, signed S3 seeds, and DB secret-data hashes."""

import json
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state, ssh  # noqa: E402
from services.common.crypto import digest, verify  # noqa: E402
from services.executor.seed_export import audit_database_hashes, s3_client  # noqa: E402


def main():
    state = load_state()
    report = {"observed_at": datetime.now(UTC).isoformat(), "checks": {}}
    response = httpx.get(state["public_url"] + "/executor-pubkey.json", timeout=30)
    response.raise_for_status()
    jwk = response.json()
    if jwk != state["executor_public_key"] or "d" in jwk:
        raise RuntimeError("Published executor public key differs from the SSH-pinned key")
    report["checks"]["published_public_key"] = {"passed": True, "fingerprint_sha256": digest(jwk)}
    query = """SELECT COALESCE(json_agg(json_build_object(
      'id', c.id, 'realm', r.name, 'type', c.type,
      'secret_data_sha256', encode(sha256(convert_to(COALESCE(c.secret_data,''),'UTF8')),'hex'),
      'secret_value_sha256', encode(sha256(convert_to(COALESCE(c.secret_data::jsonb->>'value',''),'UTF8')),'hex')
      )), '[]'::json)
      FROM credential c JOIN user_entity u ON u.id=c.user_id JOIN realm r ON r.id=u.realm_id
      WHERE r.name IN ('acme','acme-guest');"""
    # Hash inside PostgreSQL. No password hash, salt, or OTP secret leaves its host.
    result = ssh(state, "prod-idp", "cd /opt/callback\ndocker compose exec -T db "
                 "psql -U keycloak -d keycloak -tA -c " + shlex.quote(query) + "\n")
    production_metadata = json.loads(result.stdout)
    env = dotenv_values(ROOT / ".env")
    config = {"object_storage_host": env["OBJECT_STORAGE_HOST"],
              "object_storage_access_key": env["OBJECT_STORAGE_ACCESS_KEY"],
              "object_storage_secret_key": env["OBJECT_STORAGE_SECRET_KEY"]}
    s3 = s3_client(config)
    for realm in ("acme", "acme-guest"):
        pointer = json.loads(s3.get_object(Bucket="cb-seeds", Key=f"latest/{realm}.json")["Body"].read())
        envelope = json.loads(s3.get_object(Bucket="cb-seeds", Key=pointer["object_key"])["Body"].read())
        seed = envelope["payload"]
        verify(jwk, seed, envelope["signature"])
        if pointer["seed_sha256"] != digest(seed):
            raise RuntimeError("Seed object hash differs from its pointer")
        if digest(seed["normalized_state"]) != seed["prod_state_digest"]:
            raise RuntimeError("Production state digest does not match normalized metadata")
        users = seed["normalized_state"]["users"]
        admins = [u for u in users.values() if "/admins" in u["groups"]]
        dana = next(u for u in users.values() if u["username"] == "dana.whitfield")
        if len(users) != 40 or len(admins) != 14:
            raise RuntimeError("Wrong employee/admin count in the real exported state")
        if not any(c["type"] == "otp" for c in dana["credentials"].values()):
            raise RuntimeError("Dana has no production OTP credential")
        if dana["attributes"].get("tier") != ["privileged"]:
            raise RuntimeError("Dana does not have the authoritative privileged tier")
        for user in users.values():
            for credential in user["credentials"].values():
                if not set(credential).issubset({"id", "type", "createdDate", "userLabel"}):
                    raise RuntimeError("Normalized state contains non-metadata credential fields")
        audit = audit_database_hashes(seed, [m for m in production_metadata if m["realm"] == realm])
        report["checks"][realm] = {"passed": True, "employees": len(users), "admins": len(admins),
            "dana_otp_present": True, "dana_tier": "privileged", "seed_signature_valid": True,
            "seed_key": pointer["object_key"], "version": pointer["version"], **audit}
    prod = state["resources"]["prod-idp"]["vpc_ip"]
    script = f"""python3 - <<'PY'
import socket,json
try:
 with socket.create_connection(({prod!r},8080),timeout=3): connected=True
except OSError: connected=False
print(json.dumps({{'connected':connected}}))
PY
"""
    connected = json.loads(ssh(state, "control", script).stdout)["connected"]
    if connected:
        raise RuntimeError("Control can reach the real Docker-published Keycloak port")
    report["checks"]["control_isolated_from_real_keycloak"] = {"passed": True}
    r = ssh(state, "prod-idp", """python3 - <<'PY'
import json,subprocess
from pathlib import Path
d=json.loads(subprocess.check_output(['docker','inspect','callback-keycloak-1']))[0]
keys={e.split('=',1)[0] for e in d['Config']['Env']}
assert 'KC_BOOTSTRAP_ADMIN_PASSWORD' not in keys
assert not any(line.startswith('BOOTSTRAP_ADMIN_PASSWORD=') for line in Path('/opt/callback/.env').read_text().splitlines())
print('Bootstrap credential removed from IdP host env and container')
PY
""")
    report["checks"]["bootstrap_env_removed"] = {"passed": True, "observation": r.stdout.strip()}
    report["all_passed"] = True
    path = ROOT / "docs/infra" / ("P2-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print("P2 identity, seed signature and production-secret scrub checks passed: " + str(path.relative_to(ROOT)))


if __name__ == "__main__":
    main()
