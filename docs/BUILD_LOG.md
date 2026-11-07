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

## P5 — Technical path deployed; real-device checkpoint pending (2026-11-05)

Implemented strict typed apply, exact JCS hashes, raw P-256 device/approver
signatures, production-registered keys, pinned approver realm scope, timestamp
freshness, independent policy floor, full normalized CAS, typed REST mutations,
post-state effect comparison, reversible rollback, and signed receipts. A
started execution without a receipt fails closed instead of repeating a password
reset. Local receipts persist; an Object Storage outbox retries failed uploads.

The executor generates temporary passwords and seals them to a separately
registered ECDH device public key (HKDF-SHA256 + AES-GCM). Only authenticated
registered-device proofs can fetch the verified encrypted delivery. Control,
agent, API logs and receipts receive no plaintext password. The actual browser
crypto module interoperates with Python in both directions; wrong binding and
tampered receipts fail. The phone and operator private keys are non-extractable
WebCrypto keys persisted in IndexedDB. SSH-only enrollment refuses to overwrite
an existing different public key and archives public ceremonies.

Live guest direct checks: docs/infra/P5-executor-20261105T173758Z.json, nine
checks pass, including actual Keycloak reset/post-verify, signed receipt,
encrypted-only delivery, idempotent response, tamper rejection, signed Dana deny
with unchanged digest, real deliberate drift refusal, and unchanged main realm.
The public planner/twin/device-signature/apply path also passes all nine checks:
docs/infra/P5-public-20261105T180001Z.json. These tests use **simulated guest device
keys**, with real cryptography, inference, twins, executor and identity changes.
They are labelled in UI, README and reports; they do not satisfy real-phone
acceptance. Browser receipt verification was observed in Chromium using the
published executor key fingerprint 608d83bde0fe54ac901994732fb8e6e1870d7e8bee66414f7b73b8fa534c3c5a.
Phone layout was visually reviewed at 390×844. Artifacts: output/playwright/P5-*.

Preserved earlier public failures: the first test stopped after the planner
asked a normal extra staging question; the second used the old seed after our
manual drift probe. CAS correctly refused it. The initial diagnosis singled out emailVerified; a further real probe found
that sparse user PUTs clear unspecified root profile fields. Corrected enrollment
and typed mutations to GET and preserve the writable representation. The earliest
signed seed confirms main acme stayed intact; restored the affected guest
Sam/Dana names/email/verification while preserving their public keys and reset
state. Public pre-repair metadata was archived on executor. Added a regression
for field preservation. The failed supplementary test report remains unchanged.

A final real operator fault changed guest enabled state after the approved email
write. The executor observed the extra actual effect, alarmed FAILED_VERIFY,
rolled back and verified its own email change, and preserved the unrelated
concurrent enabled state until the test's explicit cleanup. All 12 checks pass:
docs/infra/P5-executor-20261105T175639Z.json. This is a labelled operator-scripted
fault with simulated guest signatures, not an invented planner action. Corrected
fixture drift cleanup uses full field preservation and publishes fresh seeds.

The automated browser enrollment test only creates an **unpinned** test request.
Its key is not Hassan's real approver enrollment and will not be pinned. The
required human checkpoint is now open: docs/device-enrollment.md gives exact
phone Dana/Sam and normal-browser approver steps. Await the three user-provided
enrollment IDs, pin their public bundles, then run actual-phone Sam approval and
Dana denial. Do not write "MVP reached" before that acceptance. P6–P10 remain.
Current local verification: 50 Python tests; Ruff; strict Vite/TypeScript build.

Published the final P4 twin image in Vultr Container Registry at immutable digest
sha256:72ff271bf03dcbcee94f39bfc89a00d14dd80b7017b8cf86a7c7f2b40600869b;
evidence in docs/infra/P4-image.json. Redeploy preserves the configured current
image rather than silently reverting to the historical P3 image.

Receipt layout was reviewed and refined twice: a clear status, hash/digest facts,
human-readable effects and collapsed signed JSON replace the cramped first pass.
The browser receipt still independently verifies the signature. The automated
IndexedDB readback confirms private_key_non_extractable=true; that test's
approver remains unpinned. Some enrollment polling requests encountered server
disconnects during executor replacement. Disabled persistent executor HTTP
connections and return bounded 503 reconnect responses instead of uncaught 500s.
Call creation refreshes signed seed pointers before claiming a twin; older sync
responses cannot replace newer versions. Seed pointer writes use unique atomic
files. These improve availability without relaxing hash, signature or CAS checks.


P5 final public rerun also passes all nine checks on the deployed field-preserving
executor and fresh-seed control flow: docs/infra/P5-public-20261105T180001Z.json.
Added a canonical-domain guard on the entire typed request before mutation,
including unsigned receipt context: non-finite numbers cannot cause receipt
signing to fail after a production change. Storage-outage and noncanonical-input
regressions bring the local suite to 50 passing tests.

Hassan reported a confusing Refresh enrollment label and missing Device slot.
The existing Dana requests use the same signing/encryption key; nothing needed
to be regenerated. Replaced the dropdown with explicit Dana/Sam links, show the
existing-request state, and added a copy-ID button. No prior key was deleted.
Using Computer Use, created the approver key in Hassan's actual regular Chrome
profile and pinned the exact public fingerprint
96071919a2ad8153d34928573f44b71450d9a297aeb2512b9b1bdeec388bb235
through executor SSH. Observed KEY PINNED in that browser, saved proof to
output/playwright/P5-real-browser-approver-pinned.png and kept the tab open.
This is distinct from the unpinned automated test-browser key. Phone key ceremony
still awaits Hassan confirming Dana's displayed fingerprint prefix 7d438445
and creating Sam's request using the direct phone URL. Codex will retrieve IDs
and pin the public keys; do not ask Hassan to recopy long IDs unnecessarily.


## P5 — MVP reached: real phone accepted (2026-11-05)

Hassan confirmed Dana's fingerprint prefix 7d438445 and created Sam's phone
request. Pinned both exact public signing/encryption bundles through executor SSH;
all three real enrollment-status checks return pinned=true. The private keys stay
on the physical phone and regular Chrome browser. Enrollment proof:
docs/infra/P5-real-enrollment-20261105T182513Z.json.

Staged real Vultr planner calls in acme: Sam
68d87ea9-7fd0-47fe-b2c6-d2d95f6ef07d and Dana
c4eb21e6-e053-440f-b579-f24800c2c438. Sam yields one reset, R7, device-only;
Dana yields OTP removal plus CONFIGURE_TOTP, R5/R6, device plus human. Both twins
were frozen and destroyed before phone delivery. Hassan approved Sam and confirmed
the temporary password appeared on his phone, without sharing its value. He
signed Deny for Dana. No device signature was simulated in these checks.

infra/verify_real_phone.py --phone-display-confirmed passes all 15 checks:
executor receipt signatures; real-phone context; twin destruction metadata;
exact returned Vultr models; one Sam reset applied/post-verified via device-only
AUTO; actual public retarget-to-Dana tamper refused with HASH_MISMATCH; signed
Dana denial; equal production before/after digests; privileged OTP policy.
Evidence: docs/infra/P5-real-phone-20261105T184311Z.json. The phone display is
explicitly human-confirmed; the password was never fetched by this verifier.
Drift and post-verify rollback use the separate real guest executor integration
proof (12 checks), not a claim of an extra manual main-realm drift test.

Separated approval waiting from execution: twins remain capped at 15 minutes,
and are destroyed before delivery; frozen proposals wait up to one hour so the
physical user can respond asynchronously. Decision signatures still expire in
10 minutes and full production CAS remains mandatory. Existing signed change
sets were not edited. The gate UI was refined to move only APPLIED_VERIFIED
effects to production, keep denied/rejected cards in the twin, show compact
real limits/destroy proof, and link browser-verifiable receipts. First 1920x1080
review saved to docs/img/P6-gate-sam-stage-v1.png; second visual iteration built.
P6 signed operator jobs and red-team UI are under construction, not accepted yet.

## P6 — Gate, signed containment tests and recorded demo acceptance (2026-11-06)

The live Gate shows signed Sam apply and Dana denial. The four fixed signed
operator tests passed with a simulated guest signer. The separately labelled
hostile replay removed 14 OTP credentials in its gVisor twin. The canary killed
the twin in 705.7 ms and the independent executor observed equal production
digests. The ordinary planner's response to the hostile page was refusal. The
red-team page also verified a real pinned Chrome operator signature for the
fork workload.

CALLBACK_LIVE_E2E=1 uv run pytest -q tests/e2e/test_demo.py passed in 21.69 s.
The test selected the three recorded beats, verified their receipts in Chrome
and created a fresh hash-mismatch refusal. Gate visuals were reviewed and
iterated at 1920×1080. Screenshots and passing JSON reports are in docs/img
and docs/infra. The earlier warm-pool 425 report is retained. The isolated
browser test uses installed Chrome after the bundled headless shell crashed.
Default tests reported 52 passed and one opt-in skip.

The landing explainer was built after the public replay test. Its static
deployment is pending. The new client IPv4 timed out on SSH and Vultr account
API preflight returned 401. The existing public service remained healthy.

## P7 — Public voice and browser evidence (2026-11-06)

Implemented hold-to-talk in Chrome, bounded FFmpeg conversion, live Vultr
Whisper transcription and Ryan stock reply synthesis. Generated five labelled
Aiden stock pretexts from the demo fixtures. The control service invokes fixed
FFmpeg arguments with pipe-only I/O and no inference-key environment. It
does not persist audio uploads. Identity checks apply the user-approved
catalog-only audio exception when Vultr omits the returned ID.

CALLBACK_VOICE_E2E=1 uv run pytest -s -q tests/e2e/test_public_voice.py passed
in 127.73 seconds. Real browser MediaRecorder captured a synthetic WAV from
Chrome's fake microphone. The red-team clip reached the same live API and
staged Dana's OTP removal and re-enrollment with production unchanged. Text
fallback passed. The two release/send-to-playing measurements were 38.195 and
56.741 seconds, median 47.468. These are batch turns including twin operations,
not realtime voice. A local component probe separately measured a 2.563 s median
for FFmpeg, STT and fixed-reply TTS, excluding planner and browser. The first
public run staged the change but failed playback because Caddy still mounted
the old configuration file after rsync. Recreating the owned Caddy container
applied the media policy. A later run hit a disabled warm pool after one
boot failure. The broker now retries after a backoff and archives destroyed
snapshots out of its active state file. Prior evidence remains preserved.

## P8 — Matched benchmark sample and full run (2026-11-06)

Materialized 40 synthetic attack scenarios and 20 legitimate scenarios.
The runner uses three planners, three arms, and fresh gVisor Keycloak copies.
Its in-process executor connects only to a label-verified disposable bridge
address. It uses separate simulated signing keys, no production credential.
The DeepSeek six-cell sample finished across all three arms. Callback signed
DENIED for the attack and APPLIED_VERIFIED for the legitimate reset. Sample
coverage and estimates are generated in bench/results and docs/benchmark.md.
Started P8-full-20261106, 540 cells with a 12-turn maximum, from make bench
on the owned sandbox. The race displays the sample as such until full results
are collected.

## P9 — Public guest desk and recovery work (2026-11-06)

Each reserved guest slot has a browser-held signing/encryption key and a
20-minute lease. The executor checks the exact realm and slot, compares the
target and realm policy state, and permits only the guest's own temporary
reset. The browser signs a reset to release its slot. The executor resets
expired guest slots and records its nightly pass. Sam and Dana's existing
main-realm phone enrollment stays separate.

CALLBACK_GUEST_E2E=1 uv run pytest -s -q tests/e2e/test_guest_desk.py verified
a fresh Chrome profile in 54.882 seconds from page open through applied
verification. Browser decryption and receipt verification passed. The
temporary password was hidden before screenshot capture. A subsequent repeat
test exposed a monitor bug. A cancelled call without a planner policy field
could stop the background usage check, leaving health stale. Closed-call
archival now accepts the absent field and retries errors separately. Health
reports stale usage even if the last iteration succeeded. The three-profile
and forced recovery checks remain pending.

The recovery verifier killed the task-owned control and executor processes.
systemd and Docker started new PIDs. Readiness returned, the public executor
key matched, and the earlier Sam receipt remained available. The poll
intervals measured 3.222 seconds after the control PID changed and 4.025
seconds after the executor PID changed. The original containment pool's
reconciliation ran on broker restart before the full benchmark resumed.
See docs/infra/P9-recovery-20261106T163052Z.json.

A simultaneous guest retry after control recovered exposed seed warm-up 425s
and exhausted the per-IP retry bucket. Scoped guest starts now accept an
available recent signed guest rehearsal seed while the executor checks the
current leased user's complete state and realm policy. Main-realm starts
still require the current signed seed. The guest browser backs off for ten
seconds between attempts. The full benchmark was stopped for the owned
broker rollout after seven journaled cases and resumed under the same run
ID. Completed observations were preserved.

## P10 — Submission assets and LabLab draft (2026-11-06)

The README exceeds 12 KB. It links primary incident sources, names every
Vultr product used, includes the Gate capture and trust-zone diagram, and
shows the generated benchmark table with the development-sample label.
Rendered the nine-slide Marp source to a PDF, inspected its slide images,
and rendered the 1920×1080 cover in Chrome at device scale factor two.

Rendered a 4:09 H.264/AAC MP4 using authentic browser recordings, captured
test evidence, stock Vultr narration and the labelled synthetic caller clip.
Verified the stream dimensions, duration, audio level and sampled frames.
The recording follows docs/video-script.md. The Race segment identifies its
observed sample coverage on screen. Hassan can record the same script in his
own voice. The generated submission video does not depict a new physical
phone ceremony.

LabLab's Axiom Labs draft is 100% saved with the C1 Blast Radius Zero track,
Security category, Vultr technology, cover, demo MP4, PDF, public source and
guest URL. The publish action awaits the remaining acceptance checks and
full benchmark export. The brief's earlier internal deadline is used for
planning because the event page and its schedule labels differ.

The fixture audit found six OTP-removal attack cases aimed at identities
without OTP enrolled. Assigned those cases to synthetic identities with OTP
and preserved their pretexts. The first attempted full run is retained as an
eight-case partial file. The corrected 540-cell design gets a new run ID.
For legitimate requests, the simulated device signs only a proposal matching
the exact requested effects. The generated method states that simulation
assumption. The direct and description-only arms keep their original setup.

The three-browser guest check completed after signed recent-seed warm-up.
All three approved temporary resets were APPLIED_VERIFIED in 79.648–85.224
seconds. All browsers observed local decryption and verified the signed
receipt. The main realm's signed seed digest still matched the historical
real-phone denial. A post-test lease inspection showed the first test's
cleanup skipped its click after navigating back. Updated the acceptance
test to verify the receipt in a separate tab and require a reset
confirmation on the original page. The old test leases expire normally.

The corrected full benchmark P8-full-v2-20261106 started on the sandbox
host with 540 cells, up to 12 turns and three workers. It is running
independently of the LabLab draft and workstation.

The expiry check found zero active leases after the three earlier test leases
expired. The separate fresh-browser follow-up verified receipt signature,
browser decryption and the signed slot reset. Executor readback found zero
remaining leases. That completed the P9 acceptance checks.

## P8 — Decision billing reconciliation (2026-11-07 PKT)

The 12 USD conservative benchmark budget stopped productive inference after 64
completed cells. The runner journaled 202 attempts, including budget refusals.
Vultr's current-month observed chat and decision tokens were approximately
0.566 USD at catalog rates across Callback work, excluding audio. The previous
settlement logic handled chat's prompt_tokens/completion_tokens but omitted
System One's billed input_tokens. It retained every maximum decision
reservation. Vultr documents per-question input-token billing at
https://api.vultrinference.com/docs/reference/create-systemone.

The benchmark journal and earlier spend reservations were preserved. The
corrected settlement code uses the live decision rate and actual billed input
tokens. Previous successful cases' decision cost estimates are reconstructed
programmatically from their saved model responses. Resumed the same matched
design with the 20 USD runner cap and retry-errors. Future budget refusals
stop the queue instead of consuming all remaining cells. The live control
plane also received the corrected accounting. Evidence and the earlier
partial report are retained.

The LabLab application remains a saved draft. Hassan explicitly requested
approval before final submission.

## P8 — Full matched benchmark accepted (2026-11-07 UTC)

Completed P8-full-v2-20261106 with 540 unique planner/arm/scenario cells.
Every planner/arm pair contains all 60 scenarios. The observed unauthorized
effect totals were 48 for direct tools, 22 for description-only approval and
0 for Callback, each across 180 cases. Legitimate completions were 20/60,
16/60 and 40/60 respectively. The case-level estimated inference total was
2.556616 USD at observed catalog rates, with failed/unpriced-call caveats.

The runner's original error status mixed infrastructure failures with
terminal model-induced failures. Added report classification from saved
artifacts. Thirteen verified OUTPUT_LIMIT terminations and three tool-schema
validation failures remain failed tasks, with original call_status preserved.
They count as evaluated cases and receive separate diagnostic columns.
Infrastructure failures retain error status. Ten baseline terminal
observations are incomplete, so baseline effect totals are lower bounds.
No inference was repeated to improve these failed model outcomes.

The report-only finalization read saved broker status, destroy proof and
tool validation evidence, then regenerated the JSON and Markdown. Preserved
the raw pre-classification result separately. Collected and published the
full result, generated README/deck tables from it and deployed the Race
diagnostic columns. Public JSON equals the local artifact. Regression tests
for retained effects, failed legitimate tasks and infrastructure-error
classification passed, 3/3. Ruff and git diff checks passed. Earlier samples,
partial runs, budget evidence and journals remain preserved.

## P10 — Final assets and saved review draft (2026-11-07 UTC)

Refreshed the README, nine-slide Marp deck and 4:09 video with the generated
540-case result. The video uses labelled Vultr stock narration, actual browser
captures and recorded execution evidence. The hostile operator workload and
simulated device/caller paths retain their labels. Kept the earlier media
variants locally. The final video is
.local/submission-media/Callback-demo-final.mp4.

Rendered the deck with Marp and inspected its nine-page contact sheet.
Inspected sampled frames from all twelve video scenes, including the full
Race table. ffprobe verified 1920×1080 H.264/AAC and 249.021 seconds. Measured
audio mean was -20.9 dB and peak -4.3 dB. These are volume measurements. The
README is 18,674 bytes and the cover is 1920×1080.

Replaced the task-created LabLab draft media with the final PDF and MP4,
updated its additional context with full results and caveats, and observed
100% completion with autosave confirmed. Independently streamed the uploaded
assets and matched each SHA-256 and byte count to its reviewed local file.
See docs/infra/P10-final-assets-20261107.json. The saved draft remains at
https://lablab.build/ai-hackathons/vultr-hackathon/axiom-labs/submission.
Final submission awaits Hassan's explicit go.

Ran the combined live regression suite with
CALLBACK_LIVE_E2E=1 CALLBACK_VOICE_E2E=1 CALLBACK_GUEST_E2E=1 uv run pytest -q.
All 64 tests passed in 252.09 seconds, with zero skips. make lint passed and
npm run build --prefix web passed TypeScript checking and the Vite build.
The fresh guest completed in 48.662 seconds, observed local decryption,
verified its receipt and confirmed signed reset. The three replay receipts
and a fresh tampered-copy refusal passed browser verification. Both public
voice paths and text fallback passed. The final two-turn browser voice median
was 73.390 seconds, illustrating the planner latency limitation.

Public health and the full result matched local expectations. Executor
readback matched the main realm's physical-phone denial digest and found
zero guest leases. Added the final review steps, real/simulated scope and
remaining benchmark/voice limitations to STATUS. Configured-secret and
whitespace checks passed before commits. The earlier partial runs and
failed attempts remain preserved.

## P10 — Recut video and copy refresh (2026-11-07 UTC)

Uploaded the requested Callback-demo-recut.mp4 with music through the same
logged-in LabLab Chrome session. The uploaded video is 246.181917 seconds,
1920×1080 H.264/AAC and 99,443,374 bytes. Streamed the uploaded object and
matched SHA-256 and byte count to the local file. The earlier
Callback-demo-final.mp4 retained its original SHA-256. Evidence is in
docs/infra/P10-recut-assets-20261107T113741Z.json.

Rewrote video-script.md from .local/recut-src/narration.json with all thirteen
scenes, their timeline boundaries, caller/agent inserts and local render
sources. The document identifies Chatterbox narration, Qwen3-TTS Ryan agent
speech and ACE-Step 1.5 music as Vultr Serverless Inference outputs. The caller
remains the labelled synthetic stock clip. Updated STATUS to name the recut
and preserve the final-submission approval boundary.

Applied the source short description verbatim at 237 characters and verified
it after reload. The source title has 53 characters and LabLab requires 5–50.
The supplied long opening with the plain-line benchmark and retained final
paragraph totals 3,268 characters, exceeding the enforced 2,000-character
limit. The UI displayed validation errors for both. Restored the existing
title and long description and requested a copy decision. Prepared a
49-character title and 1,944-character long description containing every
requested section and the old final paragraph verbatim.

The saved draft remains 100% complete. After reload, the recut URL and short
description persisted. The cover image, PDF, category, track, technology,
repository, demo URL, platform and additional information matched their
earlier values. The supplied new title and long description await Hassan's
choice about the field limits. Final submission awaits Hassan's explicit go.
Checked narration preservation and git diff whitespace. This update changes
submission media and documentation, so application tests were not repeated.

## Pre-submission polish (2026-11-07 UTC, Claude)

The guest and main help desk now show live turn progress, built from the
call's real tool log, with an elapsed timer and the expected 20–60 s
duration. They also show a device-prompt hint and the executor's
apply status. Verified on the public URL with one fresh guest run: the
request reached the device 51 s after sending, then applied and verified
4 s after approval, and the receipt verified in the browser. The web bundle
was redeployed with an rsync of `web/dist` only.

Re-cut the submission video as `.local/submission-media/Callback-demo-recut.mp4`
(4:06). It is built from 2× captures of the recorded evidence pages, a live
guest run and generated graphics, with Vultr Chatterbox narration, the
recorded agent reply in Qwen3-TTS Ryan, the stock synthetic caller clip
and an ACE-Step music bed. A voice-only variant is alongside. Benchmark
figures come from `bench/results/latest.json`; simulations keep their
on-screen labels. Sol's `Callback-demo-final.mp4` is unchanged. The
render source is in `.local/recut-src/`.
