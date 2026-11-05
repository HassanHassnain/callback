"""Provision only Callback-owned resources; no deletion based on labels alone."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
import yaml
from botocore.exceptions import ClientError
from dotenv import dotenv_values, load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "infra/state.json"
ENV = ROOT / ".env"
API = "https://api.vultr.com/v2/"
# The brief's 16 GB fallback keeps instances + $50/mo Seattle storage below
# this hackathon account's $200 monthly service-fee limit.
ROLES = {"control": "vhp-2c-4gb-amd", "sandbox": "vx1-m-2c-16g-120s",
         "prod-idp": "vhp-2c-4gb-amd", "executor": "vc2-1c-1gb"}
SAFE_FIELDS = {"id", "label", "name", "description", "region", "plan", "status", "power_status",
               "server_status", "main_ip", "internal_ip", "date_created", "hostname", "tags"}


class ProvisionError(RuntimeError):
    pass


def now():
    return datetime.now(UTC).isoformat()


def read_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"schema": 1, "owner_id": str(uuid.uuid4()), "created_at": now(),
            "resources": {}, "audit": [], "buckets": {}}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_suffix(".next.json")
    temp.write_text(json.dumps(state, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(STATE)


def remember(state, name, path, data):
    safe = {key: value for key, value in data.items() if key in SAFE_FIELDS}
    entry = {**safe, "api_path": path, "created_by_task": True,
             "owner_id": state["owner_id"], "recorded_at": now()}
    state["resources"][name] = entry
    state["audit"].append({"event": "resource_created", "name": name, "id": data["id"], "at": now()})
    save_state(state)
    return entry


class Vultr:
    def __init__(self):
        load_dotenv(ENV)
        key = os.environ.get("VULTR_API_KEY")
        if not key:
            raise ProvisionError("VULTR_API_KEY is missing")
        self.client = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {key}"},
                                   timeout=45, follow_redirects=False)
        self.last_status = None

    def call(self, method, path, *, body=None, params=None, allow_missing=False):
        response = self.client.request(method, path, json=body, params=params)
        self.last_status = response.status_code
        if allow_missing and response.status_code == 404:
            return None
        if not response.is_success:
            # Only expose the redacted error string, never a full resource body.
            detail = response.json().get("error", "") if response.content else ""
            detail = detail if isinstance(detail, str) else ""
            for name, value in os.environ.items():
                if value and len(value) >= 8 and any(x in name for x in ("KEY", "TOKEN", "SECRET")):
                    detail = detail.replace(value, "[REDACTED]")
            raise ProvisionError(f"Vultr {method} {path}: HTTP {response.status_code}: {detail[:300]}")
        return response.json() if response.content else {}

    def listing(self, path, key):
        items = []
        cursor = None
        seen_cursors = set()
        seen_ids = set()
        while True:
            params = {"per_page": 500}
            if cursor:
                params["cursor"] = cursor
            data = self.call("GET", path, params=params)
            page = data[key]
            fresh = [item for item in page if str(item.get("id")) not in seen_ids]
            items.extend(fresh)
            seen_ids.update(str(item.get("id")) for item in fresh)
            cursor = data.get("meta", {}).get("links", {}).get("next")
            total = data.get("meta", {}).get("total")
            if not cursor or not fresh or cursor in seen_cursors or (total is not None and len(items) >= total):
                return items
            seen_cursors.add(cursor)

    def ensure(self, state, name, *, collection, response_key, payload, list_key=None, path=None):
        entry = state["resources"].get(name)
        if entry:
            if entry.get("owner_id") != state["owner_id"] or not entry.get("created_by_task"):
                raise ProvisionError(f"Refusing unowned resource: {name}")
            result = self.call("GET", entry["api_path"], allow_missing=True)
            if result is None:
                raise ProvisionError(f"Recorded resource {name} is missing; refusing silent replacement")
            return entry
        # The random owner token is recorded before a create. If a POST's outcome
        # is ambiguous, a subsequent run refuses duplication until reconciled.
        if name in state.get("pending_creates", {}):
            raise ProvisionError(f"Ambiguous previous create for {name}; inspect and reconcile its ID")
        if list_key:
            for resource in self.listing(collection, list_key):
                for key in ("label", "name", "description"):
                    if payload.get(key) and resource.get(key) == payload[key]:
                        raise ProvisionError(f"Existing {name} is not recorded as task-owned; preserving it")
        state.setdefault("pending_creates", {})[name] = {"collection": collection, "at": now()}
        save_state(state)
        try:
            data = self.call("POST", collection, body=payload)
            result = data[response_key] if response_key else data
        except ProvisionError:
            if self.last_status in {400, 401, 403, 404, 422}:
                state["pending_creates"].pop(name)
                save_state(state)
            raise
        resource_path = (path or collection) + "/" + str(result["id"])
        entry = remember(state, name, resource_path, result)
        state["pending_creates"].pop(name)
        save_state(state)
        print(f"Created {name}: {entry['id']}", flush=True)
        return entry


def ensure_ssh(api, state):
    key_path = Path.home() / ".ssh/id_ed25519"
    pub_path = key_path.with_suffix(".pub")
    if not pub_path.exists():
        key_path.parent.mkdir(mode=0o700, exist_ok=True)
        if key_path.exists():
            result = subprocess.run(["ssh-keygen", "-y", "-f", str(key_path)],
                                    check=True, capture_output=True, text=True)
            pub_path.write_text(result.stdout)
        else:
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path),
                            "-C", "callback-infra"], check=True)
            state["local_ssh_key_created_by_task"] = True
    public = pub_path.read_text().strip()
    state["ssh_key_path"] = str(key_path)
    state["ssh_public_sha256"] = hashlib.sha256(public.encode()).hexdigest()
    return api.ensure(state, "ssh-key", collection="ssh-keys", response_key="ssh_key",
                      list_key="ssh_keys", payload={"name": f"callback-{state['owner_id'][:8]}",
                                                    "ssh_key": public})


def ensure_firewall(api, state, role, mac_ip):
    marker = f"cb-{role} | callback-owner:{state['owner_id']}"
    fw = api.ensure(state, "fw-" + role, collection="firewalls", response_key="firewall_group",
                    list_key="firewall_groups", payload={"description": marker})
    path = f"firewalls/{fw['id']}/rules"
    rules = api.listing(path, "firewall_rules")
    desired = [("22", mac_ip, 32)]
    if role == "control":
        desired += [("80", "0.0.0.0", 0), ("443", "0.0.0.0", 0)]
    if role in {"prod-idp", "executor"}:
        source_role, port = ("executor", "8080") if role == "prod-idp" else ("control", "8081")
        source_ip = state["resources"].get(source_role, {}).get("vpc_ip")
        if source_ip:
            desired.append((port, source_ip, 32))
    if role == "sandbox" and state["resources"].get("control", {}).get("vpc_ip"):
        desired.append(("8082", state["resources"]["control"]["vpc_ip"], 32))
    for port, subnet, mask in desired:
        if any(r.get("protocol", "").lower() == "tcp" and r.get("port") == port
               and r.get("subnet") == subnet and r.get("subnet_size") == mask for r in rules):
            continue
        api.call("POST", path, body={"ip_type": "v4", "protocol": "tcp", "port": port,
                                     "subnet": subnet, "subnet_size": mask,
                                     "notes": "Callback owned: " + state["owner_id"]})
    return fw


def refresh_instances(api, state):
    for role in ROLES:
        entry = state["resources"].get(role)
        if not entry:
            continue
        result = api.call("GET", entry["api_path"])["instance"]
        entry.update({key: value for key, value in result.items() if key in SAFE_FIELDS})
        vpcs = api.call("GET", f"instances/{entry['id']}/vpcs")["vpcs"]
        own = next((v for v in vpcs if v["id"] == state["resources"]["vpc"]["id"]), None)
        if own:
            entry["vpc_ip"] = own["ip_address"]
            entry["vpc_mac"] = own["mac_address"]
    save_state(state)


def ensure_storage(api, state):
    tiers = api.call("GET", "object-storage/clusters/19/tiers")["tiers"]
    tier = min(tiers, key=lambda t: float(t["price"]))
    storage = api.ensure(state, "object-storage", collection="object-storage",
                         response_key="object_storage", list_key="object_storages",
                         payload={"cluster_id": 19, "tier_id": tier["id"],
                                  "label": f"callback-{state['owner_id'][:8]}"})
    data = api.call("GET", storage["api_path"])["object_storage"]
    if data.get("status") != "active":
        print("Object Storage is provisioning; rerun up when active", flush=True)
        return
    for field, env_name in [("s3_access_key", "OBJECT_STORAGE_ACCESS_KEY"),
                            ("s3_secret_key", "OBJECT_STORAGE_SECRET_KEY"),
                            ("s3_hostname", "OBJECT_STORAGE_HOST")]:
        if data.get(field):
            set_key(str(ENV), env_name, data[field], quote_mode="never")
    ENV.chmod(0o600)
    values = dotenv_values(ENV)
    s3 = boto3.client("s3", endpoint_url="https://" + values["OBJECT_STORAGE_HOST"],
                      aws_access_key_id=values["OBJECT_STORAGE_ACCESS_KEY"],
                      aws_secret_access_key=values["OBJECT_STORAGE_SECRET_KEY"], region_name="us-east-1")
    existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
    for bucket in ("cb-receipts", "cb-seeds"):
        if bucket not in state["buckets"]:
            if bucket in existing:
                raise ProvisionError(f"Unrecorded bucket {bucket} exists; preserving it")
            s3.create_bucket(Bucket=bucket)
            state["buckets"][bucket] = {"created_by_task": True, "owner_id": state["owner_id"],
                                        "created_at": now()}
            save_state(state)
        s3.head_bucket(Bucket=bucket)
    state["storage_monthly_price"] = tier["price"]
    save_state(state)


def up(api, state):
    region = os.environ.get("VULTR_REGION", "sea")
    if region != "sea":
        raise ProvisionError("This phase's network and storage plan is for sea")
    mac_ip = httpx.get("https://api.ipify.org", timeout=20).text.strip()
    if ipaddress.ip_address(mac_ip).version != 4:
        raise ProvisionError("A public Mac IPv4 is required for the SSH firewall")
    state["mac_ipv4"] = mac_ip
    save_state(state)
    plans = state.setdefault("plans", dict(ROLES))
    availability = api.call("GET", "regions/sea/availability")["available_plans"]
    for role, plan in plans.items():
        if plan not in availability:
            raise ProvisionError(f"Plan unavailable in sea: {role} {plan}")
    ssh = ensure_ssh(api, state)
    vpc = api.ensure(state, "vpc", collection="vpcs", response_key="vpc", list_key="vpcs",
                     payload={"region": region, "description": f"cb-vpc | callback-owner:{state['owner_id']}",
                              "v4_subnet": "10.77.0.0", "v4_subnet_mask": 24})
    for role, plan in plans.items():
        firewall = ensure_firewall(api, state, role, mac_ip)
        config = yaml.safe_load((ROOT / "infra/cloud-init/base.yaml").read_text().replace("__ROLE__", role))
        config["hostname"] = "cb-" + role
        userdata = "#cloud-config\n" + yaml.safe_dump(config)
        payload = {"region": region, "plan": plan, "os_id": 2284, "label": "cb-" + role,
                   "hostname": "cb-" + role, "sshkey_id": [ssh["id"]], "attach_vpc": [vpc["id"]],
                   "firewall_group_id": firewall["id"], "tags": ["callback", state["owner_id"]],
                   "user_data": base64.b64encode(userdata.encode()).decode(),
                   "enable_ipv6": False, "backups": "disabled", "activation_email": False}
        if plan.startswith("vx1-"):
            payload["block_devices"] = [{"block_id": "local", "bootable": True}]
        api.ensure(state, role, collection="instances", response_key="instance", list_key="instances",
                   payload=payload)
    refresh_instances(api, state)
    for role in ROLES:
        ensure_firewall(api, state, role, mac_ip)
    ensure_storage(api, state)
    plans = api.call("GET", "registry/plan/list")["plans"]
    if plans["start_up"]["monthly_price"] != 0:
        raise ProvisionError("Container Registry start_up plan is no longer free")
    regions = api.listing("registry/region/list", "regions")
    registry_region = "sea" if any(r["name"] == "sea" for r in regions) else "sjc"
    registry = api.ensure(state, "registry", collection="registry", response_key=None,
               path="registry", payload={"name": f"callback{state['owner_id'][:8]}",
                                          "public": False, "region": registry_region, "plan": "start_up"})
    data = api.call("GET", registry["api_path"])
    registry["urn"] = data["urn"]
    for env_name, value in [("REGISTRY_URI", data["urn"]),
                            ("REGISTRY_USERNAME", data["root_user"]["username"]),
                            ("REGISTRY_PASSWORD", data["root_user"]["password"])]:
        if value:
            set_key(str(ENV), env_name, value, quote_mode="never")
    ENV.chmod(0o600)
    status(api, state)


def status(api, state):
    refresh_instances(api, state)
    for name, item in state["resources"].items():
        if not item.get("deleted_at"):
            resource = live_resource(api, item)
            item.update({k: v for k, v in resource.items() if k in SAFE_FIELDS})
            item["api_verified_at"] = now()
            if "status" not in item:
                item["status"] = "exists"
        status = "deleted" if item.get("deleted_at") else item.get("status", "recorded")
        print(f"{name:16} {status:12} "
              f"{item.get('main_ip', ''):16} {item.get('vpc_ip', '')}", flush=True)
    print("Buckets:", ", ".join(state["buckets"]) or "not created", flush=True)
    save_state(state)


def deletion_plan(state):
    entries = []
    for name, item in state["resources"].items():
        if item.get("created_by_task") is not True or item.get("owner_id") != state["owner_id"]:
            raise ProvisionError(f"Ownership verification failed for {name}")
        if item.get("deleted_at"):
            continue
        entries.append((name, item))
    # Remove VMs before VPC/firewalls, storage service only after explicit execution.
    return sorted(entries, key=lambda p: 0 if p[0] in ROLES else 1)


def verify_live_ownership(state, name, item, resource):
    """Require both a persisted creation event and live owner metadata."""
    if item.get("owner_id") != state["owner_id"] or item.get("created_by_task") is not True:
        raise ProvisionError("Resource is not recorded as task-owned")
    if not any(event.get("event") == "resource_created" and event.get("id") == item["id"]
               for event in state["audit"]):
        raise ProvisionError("No persisted creation event for resource")
    if str(resource.get("id")) != str(item["id"]):
        raise ProvisionError("Live resource ID differs from creation record")
    owner = state["owner_id"]
    if item["api_path"].startswith("instances/"):
        owned = owner in resource.get("tags", [])
        expected_path = "instances/" + str(item["id"])
    elif name == "vpc" or name.startswith("fw-"):
        owned = "callback-owner:" + owner in resource.get("description", "")
        expected_path = ("vpcs/" if name == "vpc" else "firewalls/") + str(item["id"])
    elif name in {"ssh-key", "registry", "object-storage"}:
        expected_name = ("callback" if name == "registry" else "callback-") + owner[:8]
        owned = resource.get("name", resource.get("label")) == expected_name
        prefix = {"ssh-key": "ssh-keys", "registry": "registry", "object-storage": "object-storage"}[name]
        expected_path = prefix + "/" + str(item["id"])
    else:
        raise ProvisionError("Unknown resource type in deletion plan")
    if not owned or item["api_path"] != expected_path:
        raise ProvisionError("Live ownership/path verification failed; preserving resource")


def live_resource(api, item):
    result = api.call("GET", item["api_path"])
    if item["api_path"].startswith("registry/"):
        return result
    key = {"instances": "instance", "vpcs": "vpc", "firewalls": "firewall_group",
           "ssh-keys": "ssh_key", "registry": "registry", "object-storage": "object_storage"}[
               item["api_path"].split("/")[0]]
    return result[key]


def retire_sandbox(api, state):
    item = state["resources"]["sandbox"]
    verify_live_ownership(state, "sandbox", item, live_resource(api, item))
    api.call("DELETE", item["api_path"])
    item["deleted_at"] = now()
    state["resources"]["sandbox-retired-" + item["id"][:8]] = item
    state["resources"].pop("sandbox")
    state.setdefault("plans", dict(ROLES))["sandbox"] = "vx1-m-2c-16g-120s"
    state["audit"].append({"event": "resource_deleted", "id": item["id"], "at": now(),
                           "reason": "Use brief fallback to keep instance+storage fee below account limit"})
    save_state(state)
    print("Retired the verified task-created empty sandbox; selected 16 GB fallback plan.", flush=True)


def down(api, state, execute):
    entries = deletion_plan(state)
    for name, item in entries:
        print(f"{'Delete' if execute else 'Would delete'} task-owned {name}: {item['id']}", flush=True)
        if execute:
            # The resource ID must be in the persisted creation record. Names are
            # informational and can never independently authorize deletion.
            verify_live_ownership(state, name, item, live_resource(api, item))
            api.call("DELETE", item["api_path"])
            item["deleted_at"] = now()
            state["audit"].append({"event": "resource_deleted", "id": item["id"], "at": now()})
            save_state(state)
    if not execute:
        print("Dry run only. --execute is required to delete these recorded project resources.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "status", "down", "retire-empty-sandbox"])
    parser.add_argument("--execute", action="store_true", help="Execute the owned-resource teardown")
    args = parser.parse_args()
    (ROOT / ".local").mkdir(exist_ok=True)
    try:
        with (ROOT / ".local/provision.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = read_state()
            api = Vultr()
            if args.command == "up":
                up(api, state)
            elif args.command == "status":
                status(api, state)
            elif args.command == "retire-empty-sandbox":
                retire_sandbox(api, state)
            else:
                down(api, state, args.execute)
    except (ProvisionError, httpx.HTTPError, ClientError, BlockingIOError) as exc:
        # Exception class and controlled ProvisionError messages are safe. Never
        # stringify SDK errors that might contain a signed URL or credentials.
        message = str(exc) if isinstance(exc, ProvisionError) else type(exc).__name__
        print("Provisioning blocked: " + message, file=sys.stderr)
        sys.exit(1)
