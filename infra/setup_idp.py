"""Bootstrap real Keycloak/Postgres with executor-local credentials and pinned TLS."""

import json
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.provision import save_state  # noqa: E402
from infra.remote import load_state, ssh, upload  # noqa: E402


def main():
    state = load_state()
    ip = state["resources"]["prod-idp"]["vpc_ip"]
    ssh(state, "executor", """set -euo pipefail
install -d -m 0700 /opt/callback/executor-private
python3 - <<'PY'
import json,secrets,os
from pathlib import Path
p=Path('/opt/callback/executor-private/credentials.json')
if not p.exists():
 p.write_text(json.dumps({'bootstrap_username':'callback-bootstrap','bootstrap_password':secrets.token_urlsafe(32),'client_secret':secrets.token_urlsafe(40)}))
 p.chmod(0o600)
os.chown(p,1000,1000)
PY
if [ ! -f /opt/callback/executor-private/signing-key.pem ]; then
  umask 077
  openssl ecparam -name prime256v1 -genkey -noout -out /opt/callback/executor-private/signing-key.pem
fi
chown -R 1000:1000 /opt/callback/executor-private
""")
    # Only the one-time Keycloak bootstrap password is bridged in memory to
    # its verifier. It is never logged or persisted on the Mac. The executor
    # signing private key and steady-state client secret never pass through the Mac.
    credentials = json.loads(ssh(state, "executor",
        "python3 - <<'PY'\nimport json\nd=json.load(open('/opt/callback/executor-private/credentials.json'))\n"
        "print(json.dumps({k:d[k] for k in ['bootstrap_username','bootstrap_password']}))\nPY\n").stdout)
    bootstrap = shlex.quote(credentials["bootstrap_password"])
    script = f"""set -euo pipefail
install -d -m 0750 -o root -g 1000 /opt/callback/idp-private
if [ ! -f /opt/callback/idp-private/server.key ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj '/CN=cb-prod-idp' \\
    -addext 'subjectAltName=IP:{ip},DNS:cb-prod-idp' \\
    -keyout /opt/callback/idp-private/server.key -out /opt/callback/idp-private/server.crt >/dev/null 2>&1
  chown root:1000 /opt/callback/idp-private/server.key /opt/callback/idp-private/server.crt
  chmod 640 /opt/callback/idp-private/server.key
  chmod 644 /opt/callback/idp-private/server.crt
fi
chown 1000:0 /opt/callback/idp-private/server.key
chmod 600 /opt/callback/idp-private/server.key
if [ ! -f /opt/callback/.env ]; then
  umask 077
  python3 - <<'PY'
import secrets
from pathlib import Path
Path('/opt/callback/.env').write_text('PG_PASSWORD='+secrets.token_urlsafe(32)+'\\n')
PY
fi
if ! grep -q '^BOOTSTRAP_ADMIN_PASSWORD=' /opt/callback/.env; then
  printf 'BOOTSTRAP_ADMIN_PASSWORD=%s\\n' {bootstrap} >> /opt/callback/.env
fi
chmod 600 /opt/callback/.env
systemctl disable --now callback-p1-probe
"""
    # Never print this script: it contains the transient bootstrap credential.
    ssh(state, "prod-idp", script)
    public_cert = ssh(state, "prod-idp", "cat /opt/callback/idp-private/server.crt\n").stdout
    cert_script = "cat > /opt/callback/executor-private/idp-ca.crt <<'CALLBACK_CERT'\n" + public_cert + "CALLBACK_CERT\n"
    ssh(state, "executor", cert_script)
    env = dotenv_values(ROOT / ".env")
    config = {"prod_url": "https://" + ip + ":8080", "tls_ca": "/run/callback/idp-ca.crt",
              "credentials_path": "/run/callback/credentials.json",
              "signing_key_path": "/run/callback/signing-key.pem",
              "seeds_bucket": "cb-seeds", "receipts_bucket": "cb-receipts",
              "object_storage_host": env["OBJECT_STORAGE_HOST"],
              "object_storage_access_key": env["OBJECT_STORAGE_ACCESS_KEY"],
              "object_storage_secret_key": env["OBJECT_STORAGE_SECRET_KEY"],
              "realms": ["acme", "acme-guest"]}
    ssh(state, "executor", "umask 077\ncat > /opt/callback/executor-private/config.json <<'CALLBACK_CONFIG'\n"
        + json.dumps(config) + "\nCALLBACK_CONFIG\nchown -R 1000:1000 /opt/callback/executor-private\n")
    compose = {"services": {
        "db": {"image": "postgres:17-alpine", "restart": "unless-stopped", "mem_limit": "768m",
               "environment": {"POSTGRES_USER": "keycloak", "POSTGRES_DB": "keycloak",
                               "POSTGRES_PASSWORD": "${PG_PASSWORD}"},
               "volumes": ["keycloak_db:/var/lib/postgresql/data"],
               "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U keycloak -d keycloak"],
                               "interval": "5s", "timeout": "3s", "retries": 30}},
        "keycloak": {"image": "quay.io/keycloak/keycloak:26.8.1", "command": ["start"],
                     "restart": "unless-stopped", "mem_limit": "2304m",
                     "environment": {"KC_DB": "postgres", "KC_DB_URL": "jdbc:postgresql://db:5432/keycloak",
                                     "KC_DB_USERNAME": "keycloak", "KC_DB_PASSWORD": "${PG_PASSWORD}",
                                     "KC_HOSTNAME": "https://" + ip + ":8080", "KC_HTTP_ENABLED": "false",
                                     "KC_HTTPS_CERTIFICATE_FILE": "/run/tls/server.crt",
                                     "KC_HTTPS_CERTIFICATE_KEY_FILE": "/run/tls/server.key",
                                     "KC_BOOTSTRAP_ADMIN_USERNAME": "callback-bootstrap",
                                     "KC_BOOTSTRAP_ADMIN_PASSWORD": "${BOOTSTRAP_ADMIN_PASSWORD}",
                                     "JAVA_OPTS_KC_HEAP": "-XX:InitialRAMPercentage=30 -XX:MaxRAMPercentage=65"},
                     "ports": [ip + ":8080:8443"],
                     "volumes": ["./idp-private/server.crt:/run/tls/server.crt:ro",
                                 "./idp-private/server.key:/run/tls/server.key:ro"],
                     "depends_on": {"db": {"condition": "service_healthy"}}},
    }, "volumes": {"keycloak_db": {}}}
    staging = ROOT / ".local/deploy/prod-idp"
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / "compose.yaml"
    path.write_text(yaml.safe_dump(compose))
    upload(state, "prod-idp", [path])
    ssh(state, "prod-idp", "set -e\ncd /opt/callback\ndocker compose up -d\n", timeout=60)
    state["identity_provider_deployed"] = True
    state["identity_provider_deployed_at"] = datetime.now(UTC).isoformat()
    save_state(state)
    print("Started real Keycloak 26.8.1 + PostgreSQL with executor-pinned TLS; no credentials displayed.")


if __name__ == "__main__":
    main()
