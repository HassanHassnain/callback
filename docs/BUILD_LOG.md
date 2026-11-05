# Callback build log

## 2026-11-04 — P0 bootstrap

Created a new `callback/` directory (it did not exist at task start). Added the
full brief, verbatim non-negotiables, MIT license, dependency setup, Makefile,
secret ignores, status, and the service/infra/web/fixture/benchmark/test layout.

Verification: `uv python find 3.12` found the installed interpreter;
`gh auth status` confirmed HassanHassnain with repo access. The requested GitHub
repository did not exist when checked. The Vultr portal visibly confirmed
email verification and previously showed the gift credit applied.

Decision: the user's clarification permits teardown and destructive containment
tests for resources created by this task. All pre-existing files/resources/keys
remain protected. Infrastructure must record created-resource ownership before
providing deletion operations.

Remaining: account API/inference/limits setup, live smoke tests, public repo,
and measured model selection. No simulated success or benchmark values added.

## 2026-11-04 — P0 account setup and live capability evidence

Created the public GitHub repo and the active Vultr Serverless Inference
subscription. Enabled the account API, saved keys directly into the ignored
owner-readable `.env`, and added the Mac's IPv4 /32. Preserved the existing IPv6
allowlist entry and did not enable global access. Verified lablab enrollment
and Axiom Labs team membership. Submitted a request for 10 instances as an
independent individual project (ticket ZAU-63SXJ); it is pending. The existing
limit is 5, enough for the four planned VMs. The user supplied the required
personal form details and instructed submission; no personal address/phone
details were written into the repository.

Built a Vultr-only transport, catalog preflight, exact response model checks,
per-model semaphores, bounded retries with Retry-After, and secret-redacted
errors. Added real smoke probes for 3 planners, vision, System One, moderation,
2 stock speech voices, and transcription of both WAVs. The lookup fixture only
validates tool-call arguments and never executes generated code locally.

Verification:

- `make preflight`: owner-only `.env`, gitignored/untracked; account and
  inference usage APIs both HTTP 200.
- `make lint`: all checks passed.
- `make test`: 7 passed. Covers missing/mismatched model IDs, unknown models
  before network, fixed provider origin, transient retries, fallback rejection,
  and configured-secret redaction.
- `uv run python scripts/si_smoke.py`: latest full run
  `20261104T182141769962Z`, 9 PASS / 4 FAIL, exit 1. All 3 planners passed tool
  and JSON Schema probes; image, decision and moderation endpoints passed.
  Speech and transcription functioned for Ryan and Aiden, but all 4 audio
  checks failed because responses omit model ID. Full measured outputs and
  latencies are committed under `docs/smoke/`; generated WAVs remain local.
- Catalog: 35 model IDs, capabilities and rate limits captured from live
  provider endpoints. No manually invented limits or measured results.
- Public visibility independently checked with `gh repo view`.
- Every pre-existing workspace entry recorded at startup remains present.

Fixes during verification: enlarged the vision rectangle to remove a shape
ambiguity; corrected the live SSE field name (`audio`); increased GLM schema
completion budget to 1024 after truncation. Earlier failed runs remain intact
for provenance. The two initial low-level audio probes are not acceptance runs.

Planner recommendation: start with DeepSeek V4.1 Flash 1017. It passed both
fixtures and had the lowest combined planner-probe latency in the latest run
(0.762 s tools + 1.888 s JSON). GLM and Qwen also work; no claim about general
quality follows from these fixtures.

P0 is partial, not green: the brief requires every response to identify its
model, but Vultr's documented speech/transcription format does not. A user
decision is pending about continuing text-first or accepting an explicit audio
identity limitation. No audio identity exception has been assumed, and no VM
has been provisioned yet.

## 2026-11-04 — P0 accepted with explicit audio identity exception

The user approved: "Allow audio using catalog validation, with the missing
response identity documented". Recorded the exception in AGENTS.md. It is
limited to omitted TTS/STT response IDs; unknown catalog IDs, wrong modality,
returned model mismatches, and omitted IDs on other routes still fail.

Verification: `make lint` passed; `make test` 8 passed; `make smoke` completed
all 13 checks successfully in run `20261104T182519488993Z`. Audio evidence
retains null returned model IDs, `model_id_verified=false`, and explicit
catalog-only exception metadata. Previous failed evidence was not changed.
P0 checkpoint: both keys work; DeepSeek is the initial planner, with GLM and
Qwen as verified alternatives. Proceeding to P1 per the brief.

## 2026-11-04 — P1 infrastructure complete

Built an idempotent Vultr API provisioner with persistent creation records,
random ownership tags, live ownership checks before deletion, ambiguous-create
protection, and a dry-run default for teardown. Provisioned four Ubuntu 24.04
VMs in Seattle, a VPC, cloud firewalls, private Object Storage buckets
`cb-receipts` / `cb-seeds`, and a private free-tier Container Registry in SJC
(the catalog has no Seattle registry region). Local keys and storage/registry
credentials remain in owner-only ignored files. No secrets are in cloud-init.

Deployed Caddy HTTPS and an explicitly labelled P1 port listener on prod-idp.
The health endpoint reports `application_ready=false`; it does not claim a
working identity provider or app. Host nftables restricts the IdP port to the
executor and the executor port to control, including Docker-forwarded traffic.
Vultr's Ubuntu image also enables UFW; exact source/port allowances were added
without disabling its deny policy. The public firewall exposes only control
80/443 and SSH restricted to the Mac.

Verification:

- `make lint`: passed; `make test`: 15 passed, including ownership rejection
  and the registry pagination regression.
- `infra/provision.py up`: repeated successfully with no new resource IDs or
  creation events. Resource count before/after remained 13 (including one
  historical retired sandbox). `docs/infra/P1-resources.json` records this and
  real private-ACL/authenticated-head checks on both buckets.
- `infra/deploy.py --verify`: passed real HTTPS, gVisor hello-world, and VPC
  reachability. Evidence: `docs/infra/P1-20261104T184315Z.json`. `/dev/kvm` exists.
- `runsc` version: release-20261102.0; Docker Compose: 2.40.3.
- Control -> prod-idp:8080 blocked; executor -> prod-idp:8080 connected. This
  uses a P1 connectivity listener; P2 must replace it with real Keycloak.

Decisions/fixes: Seattle storage's cheapest tier is $50/month. The initial
4-core sandbox plus storage exceeded the account's $200 service-fee limit.
Retired only that task-created, bootstrap-only VM after verifying its creation
record, live tag, resource ID and path; confirmed API 404 afterward. Created
the brief's 2-core/16-GB/120-GB fallback instead. Current planned base fees:
$24 + $70.08 + $24 + $5 + $50 + free registry = $173.08/month before usage extras.
The preserved state retains the retired VM and absence proof.

Registry API details required lowercase alphanumeric names, flat resource
responses, and stopping pagination at the reported total despite a spurious
next cursor. Corrected those and reconciled the one successful registry create
from the recorded pending request; no duplicate registry was created.

Live health: https://callback-45-63-34-5.sslip.io/health
Remaining: P2 identity provider, fixtures, executor signing key and signed
scrubbed seed export. No containment or production-apply claim yet.

## 2026-11-04 — P2 real identity world and signed seeds complete

Deployed Keycloak 26.8.1 and PostgreSQL 17 on the IdP VM. Executor-to-Keycloak
uses HTTPS with a pinned private certificate. The signing key was generated on
the executor and never exported; only its P-256 public JWK is published.
Created `acme` and `acme-guest` through executor-side bootstrap code, each with
40 synthetic employees, 14 admins, and Dana with OTP. Realm-scoped confidential
service accounts hold realm-admin; their secret remains executor-local except
for its normal authenticated exchange with Keycloak. The transient bootstrap
password was removed from the IdP host env and running container after setup.

Built normalized metadata export, fresh twin-only password/OTP/client
credentials, RFC 8785 hashing, WebCrypto-compatible P-256 signatures, private S3
uploads, and the 120-second export worker. The worker is healthy and continues
to export both realms; `/apply` explicitly returns 501 until P5.

Verification: `make lint` passed; `make test` 22 passed, including native Node
WebCrypto interoperability, signature tamper rejection, secret scrub checks,
and preservation of password-policy fields for diffs. `infra/verify_identity.py`
passed against real services: 40 employees/14 admins per realm, Dana OTP and
privileged tier, signed bucket objects, public-key pin match, normalized-state
digests, 68 credential-ID/production secret-data-hash comparisons per realm,
and no production hash/OTP data reused. Evidence:
`docs/infra/P2-20261104T191152Z.json`. Control cannot reach real Docker-published
Keycloak; the executor can authenticate over pinned TLS. Re-running bootstrap
preserved existing employee accounts and credentials.

Fixes: matched Keycloak's UID for its TLS key, and restricted nftables Docker
port guards to the connection's original direction so return traffic is
allowed. The guard matches original port 8080 even after DNAT to 8443.
Earlier failed probes were treated as failures and fixed before acceptance.

Known limits: no UI, twin, containment proof, device enrollment, or apply path
yet. All people/identity data are synthetic. The private TLS certificate is
locally pinned and requires managed rotation for a longer-lived deployment.

Public verification key:
https://callback-45-63-34-5.sslip.io/executor-pubkey.json
Next: P3 real twin, egress/DNS tripwire, warm pool, and containment tests.


## P3 — Real twin containment accepted (2026-11-05)

Built Keycloak/Chromium image on the sandbox VM and pushed it to the private
Vultr registry. Twin tools (UID 1100), Keycloak (1000), and audit credentials
(0) are separate. Added signed-seed validation, bounded tool execution,
freeze, snapshots, screenshot retrieval, 15-minute lifetime, warm pool,
restart cleanup with persisted ownership/creation intents, and destroy proof.
Added source-restricted broker, internal network/peer restrictions, HTTP and
UDP/TCP DNS guard, canaries, and the explicitly hostile diagnostics fixture.
No agent code executes on control or the host.

Verification: `make lint` and `make test` pass (29 tests including initial P4
effects/policy tests). The explicit real-host containment runner in
`tests/containment/run.py` passed all eight required checks, plus Chromium
through the allowlist. `infra/verify_sandbox.py` accepted the actual warm
pool of two twins. Timings, limits, fork EAGAIN, OOM result, host uptime,
tripwire kill and teardown proofs are in `docs/infra/P3-acceptance.json`;
`docs/threat-model.md` is generated from it. `infra/audit_twin_image.py`
compared the full exported image filesystem and environment locally against
configured credentials: zero matches; keys were not sent to the sandbox host.

Failures retained: first bootstrap attempted to write Docker's read-only
resolver file; fixed delivery with UID-owned tmpfs paths. The first fork
workload ended the guest before reporting EAGAIN; tightened NPROC from 512
to 128 while retaining Docker's 512 PID ceiling, then reran all eight. Fixed
stale IP attribution, a terminal event race, and Docker's lowercase missing-
object error handling. The first failed containment report remains unchanged.

Decisions/limits: no encrypted CONNECT tunnel; only the demo's exact HTTP GET
route is forwarded, so all forwarded bytes remain inspectable. Chromium's
inner sandbox is disabled because it executes inside gVisor. Read-only root
and distinct UIDs are retained. Cached post-kill snapshots are marked
incomplete and cannot authorize confirmation. Public site still advertises
infrastructure readiness only; production apply remains disabled until P5.

Next: P4 agent loop, complete effect derivation, policy, visual evidence and
minimal text UI. Agent-framework skill guidance was reviewed; this established
Python stack and the brief's Vultr-only constraint take precedence over a
new framework/provider scaffold. Frontend skill applies to the control-room UI.

Post-restart checks also passed: a twin could not connect to a peer's Keycloak
listener, and a canary in an HTTP header triggered a real kill, denied-egress
event and destruction proof (`docs/infra/P3-post-restart.json`). The final
image registry digest is in `docs/infra/P3-image.json`.


## P4 — In progress: live text preview and helper hardening (2026-11-05)

Implemented Vultr-only function orchestration, risk/moderation and tool-less
vision, state effects, policy, a persistent daily budget, SQLite call storage
with JSON audit archives, and a React/TypeScript/Tailwind Vite UI. Control runs
as an unprivileged systemd service with a read-only system and no Docker group.
Caddy serves the compiled UI and proxies localhost. Production apply is disabled.

A real browser conversation staged Sam's temporary password reset, derived one
user.password.reset effect, reached R7 / DEVICE_REQUIRED / auto_eligible, and
destroyed the twin. The independent vision model returned UNSURE with a real
Keycloak screenshot, correctly avoiding a claim that pixels establish password
material. Evidence: docs/infra/P4-Sam-first.json. The first planner invented
claim-type aliases, causing a false MISMATCH; narrowed end_call to the canonical
effect enum and will rerun. Do not count that first result as perfect acceptance.

Fixed seed fidelity: preserve the production user-profile configuration and
bearer-only client metadata. Hash client-secret values inside trusted snapshot
helpers for rotation detection, never export their plaintext. Clone password
rehashing can change createdDate; effect CAS references signed production
credential metadata while detecting the observed twin delta.

Hardened fixed helpers with Python isolated mode and read-only source paths.
A real regression planted a hostile user-site hook, started background work,
froze the twin, verified work stopped and later exec returned 409, captured a
real admin screenshot, and destroyed the twin. The trusted PID-1 anchor uses a
different UID and reaps children. Evidence: docs/infra/P4-helper-regression.json.

Current local verification: 35 Python tests and Ruff pass; npm run build passes
with strict TypeScript. Published static bundle has zero configured-secret
matches. Playwright exercised the real /call → /console flow; one transient
ERR_NETWORK_CHANGED recovered. Desktop screenshot is in output/playwright/.
The first plain-JS draft was moved into ignored .local/ui-draft and replaced
with the specified React stack before publication. Frontend and React review
skills applied. Remaining P4 work: final scripted cases and updated deployment
verification. No device confirmation, production apply or benchmark is claimed.


## P4 — Text flow verified, with honest hostile-case distinction

Final scripted text cases pass in docs/infra/P4-text-20261105T170136Z.json:
Sam yields one password reset, R7 eligibility, a device requirement, matching
canonical claims and an actual screenshot. Dana yields OTP removal plus
re-enrollment and R5/R6 device-plus-human requirements. The planner fetched the
hostile page, refused its instructions, and R2 rejected denied network attempts.
It did not execute the malicious payload; no such claim is made.

A separately labelled operator replay executed that payload inside a real twin,
removed 14 OTP credentials, fired the canary, and received R1/R2/R3 rejections.
Kill latency was 0.502452 seconds. The benign agent claim is explicitly simulated
in both UI and README; the commands, effects, kill and destroy proof are real.
Evidence: docs/infra/P4-operator-replay-20261105T170523Z.json. This is a documented
deviation from the brief's predicted planner-compromise narrative, not fabricated
model behavior. Signed production seeds confirm unchanged identity and full
normalized state for every case (docs/infra/P4-production-unchanged.json).

Fixed two acceptance-discovered issues: READY was published before the initial
snapshot, allowing an early claim to raise KeyError; publish only after the
snapshot and test that incomplete records cannot be claimed. Also normalized
unordered client scope/URI sets after a permutation caused a false realm.changed
effect on Sam. The failed report remains unchanged. Private replay now preserves
425 warm-up status for bounded retries rather than converting it to 500.

P5 is in progress. Strict change-set contracts, signature/floor/CAS checks and
device-only ECDH/HKDF/AES-GCM delivery have unit coverage; none of the new apply
path is deployed yet. Current tests: 43 pass; Ruff and Vite strict build pass.
