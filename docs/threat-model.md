# Callback containment evidence

Observed 2026-11-05T11:47:21.363930+00:00. These are real Vultr host tests, not simulations.
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
| 1 | Default-deny external HTTPS | PASS | Execution isolation |
| 2 | DNS canary kills and destroys twin | PASS | Isolation; destruction |
| 3 | Fork workload reaches process limit | PASS | Resource caps |
| 4 | Memory workload is OOM-killed | PASS | Resource caps |
| 5 | sleep 999 stopped at 30 seconds | PASS | Time cap; destruction |
| 6 | Root removal leaves host and peer alive | PASS | Isolation; destruction |
| 7 | Direct production/executor/metadata routes blocked | PASS | Isolation |
| 8 | Environment, mutable paths and protected audit files | PASS | Secret exclusion |

The fork workload reached EAGAIN after 126 children with a hard per-user
NPROC limit of 128 and a Docker PID ceiling of 512. The first, looser limit
ended the guest before the workload reported EAGAIN; it was retained as FAIL,
then tightened and rerun. The memory workload returned an OOM-killed process.
The host stayed alive without rebooting. Root removal met a read-only root and
UID permissions; writable twin files could be removed, and the twin was then
destroyed. The peer remained responsive.

DNS canary event to completed Docker kill: **0.154419 seconds**. Removal
follows the kill and is separately proved by a failed Docker inspect. A cached
state after kill is labelled incomplete; it is never presented as a final live
snapshot. All effects of a compromised call are rejected.

The observed warm pool contains 2 ready twins. Boot times: 23.901 s, 24.446 s.
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

A full Docker export of 2,902,577,152 bytes and the
container environment were compared against 5
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
