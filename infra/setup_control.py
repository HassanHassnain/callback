"""Deploy the text application as an unprivileged host service behind HTTPS."""

import sys
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.deploy import deploy  # noqa: E402
from infra.provision import save_state  # noqa: E402
from infra.remote import load_state, ssh, upload  # noqa: E402


def main():
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", check=True)
    state = load_state()
    env = dotenv_values(ROOT / ".env")
    key = env["VULTR_INFERENCE_API_KEY"]
    if not key or "\n" in key or "\r" in key:
        raise RuntimeError("Invalid inference credential")
    config = {"private_dir": "/opt/callback/control-private", "public_url": state["public_url"],
        "directory_path": "/opt/callback/fixtures/hr_directory.json", "sandbox_config": "/opt/callback/control-private/sandbox.json",
        "executor_url": "http://" + state["resources"]["executor"]["vpc_ip"] + ":8081",
        "executor_public_key_path": "/opt/callback/executor-pubkey.json", "daily_budget_usd": 20}
    upload(state, "control", [ROOT / "services", ROOT / "fixtures", ROOT / "pyproject.toml", ROOT / "uv.lock"])
    script = """set -euo pipefail
cd /opt/callback
if id callback-control >/dev/null 2>&1; then
 test "$(id -u callback-control)" = 1500
else
 useradd --uid 1500 --user-group --no-create-home --shell /usr/sbin/nologin callback-control
fi
install -d -m 700 /opt/callback/control-private
python3 - <<'CALLBACK_CONFIG'
from pathlib import Path
import json
"""
    script += "config=" + repr(config) + "\n"
    script += "Path('control-private/config.json').write_text(json.dumps(config))\n"
    script += "Path('control-private/inference.env').write_text('VULTR_INFERENCE_API_KEY='+" + repr(key) + "+'\\n')\n"
    script += """CALLBACK_CONFIG
chown -R 1500:1500 /opt/callback/control-private
chmod 700 /opt/callback/control-private
find /opt/callback/control-private -type f -exec chmod 600 {} +
.bootstrap-venv/bin/uv sync --frozen --no-dev >/dev/null
cat > /etc/systemd/system/callback-control.service <<'UNIT'
[Unit]
Description=Callback text help desk control plane
After=network-online.target
Wants=network-online.target
[Service]
User=callback-control
Group=callback-control
WorkingDirectory=/opt/callback
Environment=CONTROL_CONFIG=/opt/callback/control-private/config.json
EnvironmentFile=/opt/callback/control-private/inference.env
ExecStart=/opt/callback/.venv/bin/uvicorn services.control.app:app --host 127.0.0.1 --port 8000 --no-access-log --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/callback/control-private
PrivateTmp=true
CapabilityBoundingSet=
RestrictSUIDSGID=true
MemoryMax=1G
TasksMax=128
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable callback-control
systemctl restart callback-control
"""
    result = ssh(state, "control", script, timeout=90, check=False)
    if result.returncode:
        raise RuntimeError("Control service setup failed; inspect service logs without printing its environment")
    state["control_app_deployed"] = True
    save_state(state)
    deploy(state)
    print("Text app deployed: " + state["public_url"] + "/call")


if __name__ == "__main__":
    main()
