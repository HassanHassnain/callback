# Callback status

Updated: 2026-11-05. P0 complete under the explicit user-approved audio
identity exception. P1 infrastructure checks pass; P2 identity/seed-export and P3 real containment acceptance checks pass; P4 is in progress.

## Done

- Read the complete specification and created the repository skeleton.
- Copied the brief and its non-negotiables into project instructions.
- Recorded the user's preservation boundary: no deletion of anything present
  before the task; project-created disposable test resources may be destroyed.
- Confirmed local Python 3.12, uv, and authenticated GitHub CLI are available.
- Verified the Vultr account email through its official verification link.
- Created and pushed the public MIT GitHub repo: https://github.com/HassanHassnain/callback
- Enabled Vultr account API access, saved both API keys locally with 0600
  permissions, and added the Mac's current IPv4 /32 to API access control.
- Created the active `callback` Serverless Inference subscription.
- Verified both authenticated APIs return HTTP 200 (`make preflight`).
- Submitted the 10-instance request, ticket ZAU-63SXJ, as an independent
  individual project. Current 5-instance limit is enough for four VMs.
- Confirmed lablab enrollment and Axiom Labs team dashboard access.
- Recorded all 35 live catalog entries, modality/input caps, and provider
  rate limits in `docs/models.md`, `model_catalog.json`, and `model_limits.json`.
- All three candidate planners passed tool calling and JSON Schema output.
- MiMo image input, Clef Flash decision probability, and Nemotron moderation passed.
- Both Qwen stock voices produced WAVs; Whisper transcribed the expected words
  for both. Functional success is separate from the failed identity assertions.
- Eight local inference boundary tests and Ruff pass.

- P1: four live Seattle VMs, VPC, source-restricted firewalls, private buckets,
  private SJC registry, public HTTPS health, gVisor hello-world, and /dev/kvm.
- Network verification: executor can connect to the IdP port; control cannot.
- Provisioning rerun created no duplicates; both bucket ACLs are private.

- P2: real Keycloak 26.8.1 + PostgreSQL, two realms with 40 employees and
  14 admins each, Dana OTP, executor-local signing key, signed scrubbed seeds
  in Object Storage, healthy 120-second exporter, and public verification JWK.
- Real production credential-ID/secret-data-hash audit passes for 68 credentials
  per realm. No production OTP/hash data reused in seeds.

- P3: real Keycloak + Chromium gVisor twins; eight real containment tests pass,
  two-twin warm pool, default-deny HTTP/DNS, canary kill and destroy proof.
  Evidence and measured timings: `docs/infra/P3-acceptance.json` and
  `docs/threat-model.md`. Full 2.9-GB image export/local secret comparison has
  zero configured-key matches. Earlier failed tests remain in evidence.

## P0 checkpoint

The latest full run is `docs/smoke/20261104T182519488993Z.json`: **13 PASS**,
exit 0, `phase0_accepted=true`. The user explicitly approved live catalog
validation for audio responses that omit model identity. Those four results
retain `returned_model=null` and `model_id_verified=false`. Earlier strict-policy
failures remain unchanged in their original evidence files.

DeepSeek is the initial planner recommendation: both probes passed and their
combined latency was lowest in this single small fixture run. GLM and Qwen also
passed; this is not a broad quality benchmark. All keys work.

User decision: allow catalog-validated TTS/STT with the missing per-response
identity documented. A returned mismatch is still rejected. Exact model checks
remain mandatory for every other route. See `docs/account-setup.md` for setup.

## Not done

P4–P10 are not completed. State-diff and policy modules have initial unit coverage;
the public React text call/console preview and agent loop are live. A real Sam
reset reached R7 / DEVICE_REQUIRED, with actual visual evidence and twin destruction.
P4 scripted acceptance is still in progress; no device enrollment, production apply
or benchmark is available yet. Production apply still returns 501.

## Known limits

- The demo proxy permits exact-domain HTTP GET only; HTTPS CONNECT is denied.
- Agent NPROC is capped at 128, in addition to Docker's 512 PID ceiling, after
  the initial fork workload ended the guest before reporting its limit.
- Snapshots after a kill are explicitly incomplete cached observations.
- Broker authentication uses source-restricted VPC HTTP with a shared secret.
  Managed mTLS and independent penetration testing are not implemented.

- P1 port evidence used a labelled listener. P2 now verifies real Keycloak over
  pinned TLS, with control still blocked by host/Docker network rules.
- Sandbox uses the brief's 2-core/16-GB fallback to fit the account fee limit.
- Container Registry is in SJC because Seattle is absent from its region list.
- SSH host keys use trust on first use, pinned in a dedicated local known_hosts.
- Base service fees are approximately $173.08/month, excluding usage extras.

- Vultr speech SSE and transcription JSON responses omit `model`. Neither
  provides a model identity header. Audio is accepted under the user-approved catalog-only exception; individual audio
  response identity remains unverifiable.
- GLM needed a 1024-token completion budget to avoid truncation on the schema
  probe. It reported reasoning tokens even with reasoning disabled in the request.
- Endpoint smoke tests do not establish moderation/injection detection accuracy,
  help-desk quality, production containment, or security of a deployed system.
- Limit increase is pending. Payment method still needs user setup to retain
  the hackathon account after its stated 30-day expiry.

## URLs and demo

Application health (text preview, production apply disabled): https://callback-45-63-34-5.sslip.io/health
Executor public key: https://callback-45-63-34-5.sslip.io/executor-pubkey.json
Source: https://github.com/HassanHassnain/callback

Run `make setup`, `make preflight`, `make test`, `make lint`, and `make smoke`.
`make smoke` applies the documented audio-only exception and checks functional output.

Text preview: https://callback-45-63-34-5.sslip.io/call
Operator console: https://callback-45-63-34-5.sslip.io/console
