"""Assemble P3 acceptance from measured host evidence, never synthetic numbers."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state, ssh  # noqa: E402


def main():
    state = load_state()
    script = """cd /opt/callback
.venv/bin/python - <<'PY'
import json,httpx,time
from pathlib import Path
c=json.loads(Path('control-private/sandbox.json').read_text())
with httpx.Client(base_url=c['url'],headers={'Authorization':'Bearer '+c['api_secret']},timeout=10) as h:
 for attempt in range(60):
  r=h.get('/health');r.raise_for_status();health=r.json()
  if health['ready']>=2:break
  time.sleep(2)
 else:raise SystemExit('Warm pool did not reach two ready twins')
print(json.dumps({'health':health,'containment':json.loads(Path('.local/containment-latest.json').read_text())}))
PY
"""
    observed = json.loads(ssh(state, "control", script, timeout=150).stdout)
    containment = observed["containment"]
    assert containment["all_passed"] and len(containment["tests"]) >= 8
    audit = json.loads((ROOT / "docs/infra/P3-image-secret-audit.json").read_text())
    assert audit["secret_value_matches"] == 0
    summary = {"observed_at": datetime.now(UTC).isoformat(), "all_passed": True,
        "containment_tests": containment["tests"], "host_not_rebooted": containment["host_health"]["not_rebooted"],
        "warm_pool": observed["health"], "image_secret_audit": audit}
    (ROOT / "docs/infra/P3-acceptance.json").write_text(json.dumps(summary, indent=2) + "\n")
    rows = []
    descriptions = {
        "1_default_deny_https": ("Default-deny external HTTPS", "Execution isolation"),
        "2_dns_canary_tripwire": ("DNS canary kills and destroys twin", "Isolation; destruction"),
        "3_fork_bomb": ("Fork workload reaches process limit", "Resource caps"),
        "4_memory_bomb": ("Memory workload is OOM-killed", "Resource caps"),
        "5_exec_timeout": ("sleep 999 stopped at 30 seconds", "Time cap; destruction"),
        "6_rm_root_only_twin": ("Root removal leaves host and peer alive", "Isolation; destruction"),
        "7_no_production_executor_metadata_route": ("Direct production/executor/metadata routes blocked", "Isolation"),
        "8_no_real_secrets_or_audit_access": ("Environment, mutable paths and protected audit files", "Secret exclusion"),
    }
    for name, (description, mapping) in descriptions.items():
        result = containment["tests"][name]
        assert result["passed"]
        rows.append(f"| {name.split('_')[0]} | {description} | PASS | {mapping} |")
    tripwire = containment["tests"]["2_dns_canary_tripwire"]["kill_latency_seconds"]
    ready = [t for t in observed["health"]["twins"] if t["status"] == "READY" and not t["claimed"]]
    boots = ", ".join(f"{t['boot_seconds']:.3f} s" for t in ready)
    forks = containment["tests"]["3_fork_bomb"]["result"]["children"]
    text = f"""# Callback containment evidence

Observed {summary['observed_at']}. These are real Vultr host tests, not simulations.
Machine-readable source: [P3 acceptance](infra/P3-acceptance.json). Earlier failed
checks remain in [the first run](infra/P3-containment-first.json).

## Trust boundary

Agent bash/Python and Chromium execute inside task-owned gVisor containers on
the sandbox VM. Only trusted fixed driver commands run on the host. Twin tools
use UID 1100, Keycloak UID 1000, and the snapshot credential file UID 0. Agents
cannot read the auditor file or write Keycloak's database files. This protects
the snapshot mechanism from ordinary agent code; it is not a proof against a
gVisor, JVM, browser, kernel or trusted-host exploit.

The four containment requirements below are isolated execution, exclusion of
real secrets, time/memory/process caps, and destruction after each task.
Every runtime model request separately uses Vultr Serverless Inference.

| Test | Real check | Result | Requirement |
| --- | --- | --- | --- |
{chr(10).join(rows)}

The fork workload reached EAGAIN after {forks} children with a hard per-user
NPROC limit of 128 and a Docker PID ceiling of 512. The first, looser limit
ended the guest before the workload reported EAGAIN; it was retained as FAIL,
then tightened and rerun. The memory workload returned an OOM-killed process.
The host stayed alive without rebooting. Root removal met a read-only root and
UID permissions; writable twin files could be removed, and the twin was then
destroyed. The peer remained responsive.

DNS canary event to completed Docker kill: **{tripwire:.6f} seconds**. Removal
follows the kill and is separately proved by a failed Docker inspect. A cached
state after kill is labelled incomplete; it is never presented as a final live
snapshot. All effects of a compromised call are rejected.

The observed warm pool contains {len(ready)} ready twins. Boot times: {boots}.
Containers have 2 CPUs, 1536 MiB RAM, a 512 PID ceiling, no capabilities, no new
privileges, a read-only root, no host bind mounts/socket, and tmpfs writable
paths. Calls have 15-minute lifetimes, tools 30 seconds and 16 KiB output.
Restart reconciliation uses persisted IDs/creation intents and live ownership
checks; it never deletes a resource merely because its label looks familiar.

## Network and browser

The internal Docker network has inter-container communication disabled, with
an additional host FORWARD drop for its source subnet. Only host DNS (UDP/TCP
53) and proxy (3128) are reachable. The driver port is VPC-only and restricted
to control; no twin can reach it. The IdP and executor independently restrict
their production ports. Each valid/invalid HTTP or DNS attempt is logged.

The proxy forwards only HTTP GET of the exact demo domain and fixed page paths;
it forwards no caller headers/body, query or redirects. HTTPS CONNECT is always
denied, keeping encrypted traffic from bypassing inspection. This is a deliberate
demo limitation: the diagnostics page uses HTTP inside the controlled route.
Chromium runs with --no-sandbox inside gVisor, and bypasses the proxy only for
localhost/127.0.0.1. The extra live test visited the page and retrieved a real PNG.

Canaries are tripwires, not general secret detection. Encoded/unrecognized
exfiltration is still subject to the default-deny network policy.

## Secret audit and limits

A full Docker export of {audit['filesystem_bytes_scanned']:,} bytes and the
container environment were compared against {audit['configured_secret_patterns']}
configured secret values on the developer Mac: zero matches. No real key was
sent to the sandbox host for that comparison. Docker export excludes tmpfs;
test 8 separately checks writable agent paths and auditor access. Source was
also scanned before publication. The production signing key/admin credential
remain on the executor; their exclusion additionally relies on that deployment
boundary and signed scrubbed-seed checks from P2.

This is prototype containment testing, not an independent penetration test.
Trusted control, executor, broker and host administrators remain in scope as
trusted components. SSH uses pinned trust-on-first-use keys. The broker uses
source-restricted VPC HTTP with a shared secret; managed mTLS is future work.

Runtime resource behavior: [gVisor resource model](https://gvisor.dev/docs/architecture_guide/resources/).
"""
    (ROOT / "docs/threat-model.md").write_text(text)
    print(f"P3 accepted: eight real tests pass, tripwire {tripwire:.6f}s, ready pool {len(ready)}")


if __name__ == "__main__":
    main()
