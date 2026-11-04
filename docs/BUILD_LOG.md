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
