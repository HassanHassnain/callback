"""Configure the four owned VMs and deploy the P1 HTTPS health endpoint."""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.provision import ROLES, save_state  # noqa: E402
from infra.remote import load_state, ssh, upload  # noqa: E402


def vpc_ip(state, role):
    return str(ipaddress.IPv4Address(state["resources"][role]["vpc_ip"]))


def firewall(state, role):
    mac_ip = str(ipaddress.IPv4Address(state["mac_ipv4"]))
    rules = ["ct state established,related accept", 'iifname "lo" accept',
             f"ip saddr {mac_ip}/32 tcp dport 22 accept", "ip protocol icmp accept",
             "meta l4proto ipv6-icmp accept", "udp sport 67 udp dport 68 accept"]
    forward = []
    if role == "control":
        rules += ["tcp dport {80, 443} accept"]
    for target_role, port, source_role in [("prod-idp", 8080, "executor"),
                                           ("executor", 8081, "control")]:
        if role == target_role:
            allowed = vpc_ip(state, source_role)
            rules.append(f"ip saddr {allowed} tcp dport {port} accept")
            # Docker-published ports pass through FORWARD instead of INPUT.
            forward.append(f"tcp dport {port} ip saddr != {allowed} drop")
    return ("table inet callback {\n chain input {\n type filter hook input priority -50; policy drop;\n"
            + "\n".join("  " + line + ";" for line in rules) + "\n }\n chain forward {\n"
            + " type filter hook forward priority -50; policy accept;\n"
            + "\n".join("  " + line + ";" for line in forward) + "\n }\n}\n")


def configure_host(state, role):
    host = state["resources"][role]
    ready = ssh(state, role, "test -f /etc/callback/bootstrap-complete\n", check=False, timeout=15)
    if ready.returncode:
        raise RuntimeError(f"{role}: bootstrap is not complete (SSH/test exit {ready.returncode})")
    netplan = yaml.safe_dump({"network": {"version": 2, "ethernets": {"callbackvpc": {
        "match": {"macaddress": host["vpc_mac"]}, "dhcp4": False, "dhcp6": False,
        "addresses": [vpc_ip(state, role) + "/24"], "optional": True,
    }}}})
    rules = firewall(state, role)
    ufw_rules = []
    if role == "control":
        ufw_rules += ["ufw allow 80/tcp comment 'Callback HTTP'", "ufw allow 443/tcp comment 'Callback HTTPS'"]
    if role in {"prod-idp", "executor"}:
        source_role, port = ("executor", 8080) if role == "prod-idp" else ("control", 8081)
        ufw_rules.append(f"ufw allow in proto tcp from {vpc_ip(state, source_role)} "
                         f"to {vpc_ip(state, role)} port {port} comment 'Callback VPC boundary'")
    ufw_commands = "\n".join(ufw_rules) or ":"
    script = f"""set -euo pipefail
install -d -m 0755 /etc/callback
if ! ip -4 addr show | grep -Fq {shlex.quote(vpc_ip(state, role) + '/24')}; then
  cat > /etc/netplan/60-callback-vpc.yaml <<'CALLBACK_NETPLAN'
{netplan}CALLBACK_NETPLAN
  chmod 600 /etc/netplan/60-callback-vpc.yaml
  netplan generate
  netplan apply
fi
cat > /etc/callback/host-firewall.nft <<'CALLBACK_NFT'
{rules}CALLBACK_NFT
cat > /usr/local/sbin/callback-firewall <<'CALLBACK_SCRIPT'
#!/bin/sh
set -eu
if nft list table inet callback >/dev/null 2>&1; then nft delete table inet callback; fi
nft -f /etc/callback/host-firewall.nft
CALLBACK_SCRIPT
chmod 755 /usr/local/sbin/callback-firewall
cat > /etc/systemd/system/callback-firewall.service <<'CALLBACK_UNIT'
[Unit]
Description=Callback owned host network boundary
After=network-online.target docker.service
Wants=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/callback-firewall
[Install]
WantedBy=multi-user.target
CALLBACK_UNIT
systemctl daemon-reload
systemctl enable callback-firewall
systemctl restart callback-firewall
if command -v ufw >/dev/null 2>&1; then
{ufw_commands}
fi
docker compose version
echo 'Callback host configured'
"""
    result = ssh(state, role, script)
    print(f"Configured {role}: {result.stdout.strip()}", flush=True)


def deploy(state):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(configure_host, state, role) for role in ROLES]
        for future in futures:
            future.result()
    ip = state["resources"]["control"]["main_ip"]
    host = "callback-" + ip.replace(".", "-") + ".sslip.io"
    staging = ROOT / ".local/deploy/control"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "Caddyfile").write_text((ROOT / "infra/caddy/Caddyfile").read_text().replace("CALLBACK_HOST", host))
    compose = {"services": {"caddy": {"image": "caddy:2", "restart": "unless-stopped",
                "ports": ["80:80", "443:443"],
                "volumes": ["./Caddyfile:/etc/caddy/Caddyfile:ro", "caddy_data:/data", "caddy_config:/config"]}},
               "volumes": {"caddy_data": {}, "caddy_config": {}}}
    (staging / "compose.yaml").write_text(yaml.safe_dump(compose))
    upload(state, "control", [staging / "Caddyfile", staging / "compose.yaml"])
    ssh(state, "control", "set -e\ncd /opt/callback\ndocker compose up -d\n", timeout=60)
    print("Control HTTPS service started", flush=True)
    # This listener is explicitly a P1 network probe, not a fake Keycloak. P2
    # replaces it with real Keycloak before claiming identity-provider readiness.
    script = f"""set -euo pipefail
install -d -m 0755 /opt/callback/p1-probe
echo 'P1 network probe only. Keycloak is not deployed.' > /opt/callback/p1-probe/index.html
cat > /etc/systemd/system/callback-p1-probe.service <<'CALLBACK_UNIT'
[Unit]
Description=Callback P1 VPC connectivity probe (not Keycloak)
After=network-online.target
[Service]
ExecStart=/usr/bin/python3 -m http.server 8080 --bind {vpc_ip(state, 'prod-idp')} --directory /opt/callback/p1-probe
Restart=on-failure
User=nobody
[Install]
WantedBy=multi-user.target
CALLBACK_UNIT
systemctl daemon-reload
systemctl enable --now callback-p1-probe
"""
    ssh(state, "prod-idp", script)
    state["public_host"] = host
    state["public_url"] = "https://" + host
    state["p1_deployed_at"] = datetime.now(UTC).isoformat()
    save_state(state)
    print(state["public_url"] + "/health", flush=True)


def verify(state):
    report = {"observed_at": datetime.now(UTC).isoformat(), "checks": {},
              "limits": ["Port 8080 uses a labelled P1 listener; real Keycloak arrives in P2.",
                         "SSH bootstrap uses trust on first use, pinned in a dedicated known_hosts file."]}
    response = httpx.get(state["public_url"] + "/health", timeout=30)
    response.raise_for_status()
    health = response.json()
    if health.get("status") != "ok" or health.get("application_ready") is not False:
        raise RuntimeError("Unexpected P1 health response")
    report["checks"]["https_health"] = {"passed": True, "url": str(response.url), "body": health}
    sandbox = ssh(state, "sandbox", "set -e\nrunsc --version\ndocker run --rm --runtime=runsc "
                  "--network none --memory 128m --cpus 1 --pids-limit 64 "
                  "--label callback.owner=" + shlex.quote(state["owner_id"]) + " hello-world\n",
                  timeout=60)
    if "Hello from Docker!" not in sandbox.stdout:
        raise RuntimeError("gVisor hello-world output is missing")
    report["checks"]["gvisor_hello_world"] = {"passed": True, "output": sandbox.stdout}
    kvm = ssh(state, "sandbox", "ls -l /dev/kvm\n", check=False)
    report["checks"]["kvm_observation"] = {"present": kvm.returncode == 0,
                                           "output": kvm.stdout + kvm.stderr}
    prod = vpc_ip(state, "prod-idp")
    for role, expected in [("control", False), ("executor", True)]:
        script = f"""python3 - <<'PY'
import socket, json
try:
    with socket.create_connection(({prod!r}, 8080), timeout=3):
        connected = True
except OSError:
    connected = False
print(json.dumps({{"connected": connected}}))
PY
"""
        result = json.loads(ssh(state, role, script).stdout)
        if result["connected"] != expected:
            raise RuntimeError(f"VPC isolation failed: {role} -> prod-idp:8080 {result}")
        report["checks"][role + "_to_prod_port"] = {"passed": True, **result, "port": 8080}
    report["all_passed"] = True
    path = ROOT / "docs/infra" / ("P1-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print("P1 host/network checks passed. Evidence: " + str(path.relative_to(ROOT)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Run acceptance checks instead of deploying")
    args = parser.parse_args()
    try:
        state = load_state()
        verify(state) if args.verify else deploy(state)
    except (RuntimeError, subprocess.SubprocessError, httpx.HTTPError, KeyError) as exc:
        print(f"Deployment not ready: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
