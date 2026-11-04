"""Deploy P2 executor, seed via its privileged path, and publish only its public key."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.deploy import deploy as deploy_control  # noqa: E402
from infra.provision import save_state  # noqa: E402
from infra.remote import load_state, ssh, upload  # noqa: E402


def main(args):
    state = load_state()
    staging = ROOT / ".local/deploy/executor"
    staging.mkdir(parents=True, exist_ok=True)
    compose = {"services": {"executor": {"image": "callback-executor:local",
        "build": {"context": ".", "dockerfile": "services/executor/Dockerfile"},
        "restart": "unless-stopped", "mem_limit": "640m",
        "environment": {"EXECUTOR_CONFIG_PATH": "/run/callback/config.json"},
        "volumes": ["./executor-private:/run/callback"],
        "ports": [state["resources"]["executor"]["vpc_ip"] + ":8081:8081"]}}}
    path = staging / "compose.yaml"
    path.write_text(yaml.safe_dump(compose))
    upload(state, "executor", [ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / ".dockerignore",
                               ROOT / "services", ROOT / "fixtures", path])
    print("Building executor image on its own VM (no secrets in build context)", flush=True)
    ssh(state, "executor", "set -e\ncd /opt/callback\ndocker compose build executor\n", timeout=180)
    if args.build_only:
        print("Executor image built", flush=True)
        return
    print("Seeding real identity realms from executor over pinned TLS", flush=True)
    result = ssh(state, "executor", "set -e\ncd /opt/callback\n"
        "docker compose run --rm --no-deps executor /opt/callback/.venv/bin/python -m services.executor.bootstrap\n",
        timeout=120)
    print(result.stdout.strip(), flush=True)
    print("Exporting and signing scrubbed seeds", flush=True)
    result = ssh(state, "executor", "set -e\ncd /opt/callback\n"
        "docker compose run --rm --no-deps executor /opt/callback/.venv/bin/python - <<'PY'\n"
        "import json\nfrom services.executor.keycloak import config_from_file\n"
        "from services.executor.app import export_once\nprint(json.dumps(export_once(config_from_file())))\nPY\n",
        timeout=120)
    print(result.stdout.strip(), flush=True)
    ssh(state, "executor", "set -e\ncd /opt/callback\ndocker compose up -d\n", timeout=60)
    result = ssh(state, "executor", "cd /opt/callback\n"
        "docker compose exec -T executor /opt/callback/.venv/bin/python - <<'PY'\n"
        "import json\nfrom pathlib import Path\nfrom services.common.crypto import load_or_create_key,public_jwk\n"
        "print(json.dumps(public_jwk(load_or_create_key(Path('/run/callback/signing-key.pem')))))\nPY\n")
    public_key = json.loads(result.stdout)
    if "d" in public_key or public_key.get("crv") != "P-256":
        raise RuntimeError("Refusing to publish an invalid/private key")
    pub_path = staging / "executor-pubkey.json"
    pub_path.write_text(json.dumps(public_key, indent=2) + "\n")
    upload(state, "control", [pub_path])
    state["executor_public_key"] = public_key
    state["executor_deployed_at"] = datetime.now(UTC).isoformat()
    save_state(state)
    deploy_control(state)
    # Remove the transient bootstrap credential from the IdP container and host
    # env; its only retained copy is protected on executor. Keep DB data intact.
    ssh(state, "prod-idp", """set -euo pipefail
cd /opt/callback
python3 - <<'PY'
from pathlib import Path
import yaml
p=Path('/opt/callback/compose.yaml')
d=yaml.safe_load(p.read_text())
for name in ['KC_BOOTSTRAP_ADMIN_USERNAME','KC_BOOTSTRAP_ADMIN_PASSWORD']:
 d['services']['keycloak']['environment'].pop(name,None)
p.write_text(yaml.safe_dump(d))
p=Path('/opt/callback/.env')
p.write_text('\\n'.join(line for line in p.read_text().splitlines() if not line.startswith('BOOTSTRAP_ADMIN_PASSWORD='))+'\\n')
p.chmod(0o600)
PY
docker compose up -d
""", timeout=60)
    print(state["public_url"] + "/executor-pubkey.json", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", action="store_true")
    main(parser.parse_args())
