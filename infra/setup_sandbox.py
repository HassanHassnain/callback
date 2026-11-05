"""Deploy the owned sandbox host, authenticated driver, and signed seed cache."""

import json
import secrets
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.deploy import configure_host, deploy  # noqa: E402
from infra.provision import save_state  # noqa: E402
from infra.remote import load_state, ssh, upload  # noqa: E402
from services.common.crypto import verify  # noqa: E402
from services.executor.seed_export import s3_client  # noqa: E402


def sync_seeds(state):
    env = dotenv_values(ROOT / ".env")
    storage = s3_client({"object_storage_host": env["OBJECT_STORAGE_HOST"],
                         "object_storage_access_key": env["OBJECT_STORAGE_ACCESS_KEY"],
                         "object_storage_secret_key": env["OBJECT_STORAGE_SECRET_KEY"]})
    envelopes = []
    for realm in ("acme", "acme-guest"):
        pointer = json.loads(storage.get_object(Bucket="cb-seeds", Key=f"latest/{realm}.json")["Body"].read())
        envelope = json.loads(storage.get_object(Bucket="cb-seeds", Key=pointer["object_key"])["Body"].read())
        verify(state["executor_public_key"], envelope["payload"], envelope["signature"])
        envelopes.append(envelope)
    # Only scrubbed seeds cross to the sandbox host. No storage credential does.
    script = "cd /opt/callback\n.venv/bin/python - <<'PY'\nimport json,httpx\nfrom pathlib import Path\n"
    script += "c=json.loads(Path('control-private/sandbox.json').read_text())\n"
    script += "with httpx.Client(base_url=c['url'],headers={'Authorization':'Bearer '+c['api_secret']},timeout=30) as h:\n"
    for envelope in envelopes:
        script += " r=h.post('/seeds',json={'envelope':" + repr(envelope) + "});r.raise_for_status()\n"
    script += "print('Two signed scrubbed seed pointers synchronized')\nPY\n"
    print(ssh(state, "control", script, timeout=60).stdout.strip(), flush=True)


def main():
    state = load_state()
    staging = ROOT / ".local/deploy/sandbox"
    staging.mkdir(parents=True, exist_ok=True)
    config_path = staging / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {"api_secret": secrets.token_urlsafe(48)}
    state["attacker_domain"] = "it-diagnostics-" + state["resources"]["control"]["main_ip"].replace(".", "-") + ".sslip.io"
    config.update({"owner_id": state["owner_id"], "executor_public_key": state["executor_public_key"],
        "image": state.get("twin_image", "callback/twin:p4"), "control_ip": state["resources"]["control"]["main_ip"],
        "attacker_domain": state["attacker_domain"], "pool_per_realm": config.get("pool_per_realm", {"acme": 2, "acme-guest": 0})})
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    control = staging / "sandbox.json"
    control.write_text(json.dumps({"url": "http://" + state["resources"]["sandbox"]["vpc_ip"] + ":8082",
                                   "api_secret": config["api_secret"]}))
    control.chmod(0o600)
    save_state(state)
    configure_host(state, "sandbox")
    upload(state, "sandbox", [ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / "services"])
    upload(state, "control", [ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / "services"])
    for role in ("control", "sandbox"):
        ssh(state, role, "set -e\napt-get update -qq\napt-get install -y -qq python3-venv >/dev/null\n"
            "cd /opt/callback\npython3 -m venv .bootstrap-venv\n.bootstrap-venv/bin/pip -q install uv==0.11.8\n"
            ".bootstrap-venv/bin/uv sync --frozen --no-dev >/dev/null\n", timeout=180)
    # Explicit file destinations; remote private directories never enter images.
    for role, folder, file in [("sandbox", "sandbox-private", config_path), ("control", "control-private", control)]:
        content = file.read_text()
        script = "umask 077\ninstall -d -m 700 /opt/callback/" + folder + "\n"
        script += "cat > /opt/callback/" + folder + "/" + file.name + " <<'CALLBACK_PRIVATE'\n" + content + "\nCALLBACK_PRIVATE\n"
        ssh(state, role, script)
    script = """set -euo pipefail
cd /opt/callback
python3 - <<'PY'
import json,subprocess
from pathlib import Path
c=json.loads(Path('sandbox-private/config.json').read_text())
r=subprocess.run(['docker','network','inspect','twinnet'],capture_output=True)
if r.returncode == 0:
 d=json.loads(r.stdout)[0]
 assert d.get('Labels',{}).get('callback.owner')==c['owner_id'], 'Refusing to alter preexisting network'
 assert d['Internal'] and d['IPAM']['Config'][0]['Subnet']=='172.30.0.0/24'
else:
 subprocess.run(['docker','network','create','--internal','--subnet=172.30.0.0/24',
   '--opt','com.docker.network.bridge.enable_icc=false','--label','callback.owner='+c['owner_id'],'twinnet'],check=True,stdout=subprocess.DEVNULL)
PY
cat > /etc/systemd/system/callback-sandbox.service <<'UNIT'
[Unit]
Description=Callback isolated twin driver and egress guard
After=docker.service callback-firewall.service network-online.target
Requires=docker.service
[Service]
WorkingDirectory=/opt/callback
Environment=SANDBOX_CONFIG=/opt/callback/sandbox-private/config.json
ExecStart=/opt/callback/.venv/bin/uvicorn services.twin.daemon:app --host SANDBOX_IP --port 8082 --no-access-log
Restart=on-failure
RestartSec=3
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable callback-sandbox
systemctl restart callback-sandbox
""".replace("SANDBOX_IP", state["resources"]["sandbox"]["vpc_ip"])
    ssh(state, "sandbox", script, timeout=30)
    deploy(state)
    sync_seeds(state)
    print("Sandbox daemon deployed. Waiting for real twin boot before acceptance.", flush=True)


if __name__ == "__main__":
    if "--sync-seeds" in sys.argv:
        sync_seeds(load_state())
    else:
        main()
