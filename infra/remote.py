"""SSH transport restricted to task-owned hosts recorded by provision.py."""

import ipaddress
import json
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_state():
    return json.loads((ROOT / "infra/state.json").read_text())


def ssh_args(state, role):
    host = state["resources"][role]
    if host.get("owner_id") != state["owner_id"] or host.get("created_by_task") is not True:
        raise RuntimeError("Refusing SSH to a resource not recorded as created by this task")
    ipaddress.IPv4Address(host["main_ip"])
    return ["ssh", "-i", state["ssh_key_path"], "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={ROOT / '.local/known_hosts'}",
            "root@" + host["main_ip"]]


def ssh(state, role, script, *, timeout=60, check=True):
    return subprocess.run(ssh_args(state, role) + ["bash", "-s"], input=script,
                          capture_output=True, text=True, timeout=timeout, check=check)


def upload(state, role, files):
    host = state["resources"][role]
    command = shlex.join(ssh_args(state, role)[:-1])
    subprocess.run(["rsync", "-a", "-e", command, *[str(f) for f in files],
                    "root@" + host["main_ip"] + ":/opt/callback/"], check=True, timeout=60)
