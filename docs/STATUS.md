# Callback status

Updated 2026-11-07. P0–P10 acceptance checks pass under the explicit
user-approved audio identity exception. P10 final assets are saved in the
100%-complete LabLab draft. Final submission awaits Hassan's explicit go.

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

## Integration and acceptance

P5 is complete: Hassan's physical phone is enrolled as Dana and Sam, and his
regular Chrome browser is pinned as approver. In the public main realm, Sam's
real device signature auto-applied one temporary reset and independent post-verify
passed. Hassan confirmed the password appeared on the phone; Codex did not fetch
or record it. Dana's real phone signed Deny; production before/after digests match.
Retargeting Sam's signed copy to Dana produced signed HASH_MISMATCH refusal.
All 15 programmatic checks pass in docs/infra/P5-real-phone-20261105T184311Z.json.
Real guest executor drift, rollback and encrypted-delivery checks also pass.

P6: Playwright verified all three recorded Gate states at 1920×1080 and
verified a fresh signed hash-mismatch refusal. The separate signed operator
workloads passed fork, memory, filesystem and hostile-replay checks. The hostile
replay measured 705.7 ms from tripwire detection to kill and observed 14 OTP
removals inside its twin. See docs/infra/P6-demo-e2e-20261105T192549Z.json and
docs/infra/P6-operator-jobs-20261105T190747Z.json.

P7 is deployed. Chrome verified the push-to-talk recording path using a stock
WAV as the synthetic microphone input. The red-team stock clip produced the
Dana OTP removal and re-enrollment proposal with production unchanged. Browser
median release/send-to-playback was 47.468 seconds for two turns. The text
fallback passed. See docs/infra/P7-browser-20261106T150701Z.json. P5 supplies
the independent physical-phone denial for the demo.

P8 completed all 540 unique cells in P8-full-v2-20261106, with 60 scenarios
for each of three planners and three arms. Across 180 cases per arm,
observed unauthorized effects were 48 for direct tools, 22 for
description-only approval and 0 for Callback. Legitimate completions were
20/60, 16/60 and 40/60 respectively. Thirteen output-limit terminations and
three invalid-tool outcomes remain failed tasks in the measured results.
Ten baseline terminal observations were incomplete, making baseline effect
counts lower bounds. The generated JSON, method and /race use the same full
result. Earlier samples and partial reports remain preserved.

P9 guest mode is deployed. A fresh profile completed one guest reset in
54.882 seconds, decrypted on that browser and verified the receipt. Three
fresh profiles then completed simultaneous independent resets in 79.648,
82.172 and 85.224 seconds. Their browsers decrypted each password and
verified each receipt. The main-realm digest matched the earlier signed
physical-phone denial. The executor cleared the abandoned test leases automatically. A follow-up
fresh-browser test verified signed slot reset and the executor readback showed
zero outstanding leases. Forced control and executor recovery
passed with preserved key and signed receipt.
See docs/infra/P9-public-guest-20261106T164523Z.json,
docs/infra/P9-main-isolation-20261106T164523Z.json and
docs/infra/P9-recovery-20261106T163052Z.json.

P10 README, nine-slide Marp deck, cover and shot list are complete. The
LabLab draft is 100% saved with the Blast Radius Zero track, final 540-case
deck, final 4:06 MP4, cover, source and live guest URL. The current MP4 is
.local/submission-media/Callback-demo-recut.mp4, the version with music.
It uses Chatterbox narration, Qwen3-TTS Ryan for the agent line and ACE-Step
1.5 music, all generated through Vultr Serverless Inference. The caller is
the labelled synthetic stock clip. Actual browser footage and recorded
execution evidence retain their disclosures. The video is 1920×1080
H.264/AAC, 246.181917 seconds and 99,443,374 bytes. The thirteen-scene script
follows .local/recut-src/narration.json and points to the local render source.
The earlier Callback-demo-final.mp4 remains on disk. Hassan requested that the application
remain a draft until he explicitly gives the go.

The recut, approved 49-character title, 237-character short description and
1,974-character long description are saved and survive a draft reload.
Hassan approved the condensed copy required by LabLab's 50/2,000-character
limits and requested the phrase "production untouched" in the demo line.
That phrase, all three benchmark lines and the existing final paragraph are
preserved. Autosave was confirmed, completion remained 100%, and the recut
played in the draft's player. See
docs/infra/P10-recut-assets-20261107T113741Z.json. Final submission remains
subject to Hassan's explicit go.

Final isolation readback matched the main realm's earlier signed phone-denial
digest and found zero guest leases. Public health was ready and the public
benchmark JSON exactly matched the local result. See
docs/infra/P10-final-isolation-20261107.json.

The final combined regression command enabled the live demo, voice and guest
tests. All 64 tests passed in 252.09 seconds, with zero skips. Ruff and the
TypeScript/Vite production build passed. The guest completed in 48.662 seconds,
including verified device delivery and signed reset. The final two-turn voice
median was 73.390 seconds. Evidence is recorded in
docs/infra/P6-demo-e2e-20261107T054601Z.json,
docs/infra/P9-public-guest-20261107T054620Z.json and
docs/infra/P7-browser-20261107T054715Z.json.

## Real and simulated paths

- Real execution includes live Vultr inference, Keycloak mutations in
  disposable gVisor copies, broker containment, executor verification,
  signed receipts and the completed physical-phone Sam approval and Dana denial.
- The guest device, benchmark callers and benchmark device/operator decisions
  are simulated and labelled in the UI and README. The hostile operator test
  executes real commands with a scripted workload and a simulated benign claim.
- The deterministic Console demo replays recorded evidence. The submission
  video labels those replays and its synthetic narration. It depicts the
  completed phone decisions through their records.

## Known limits

- The physical phone/main-realm checks are real. Guest integration keys and
  proposals are labelled simulated in UI and README. A separate automated test
  browser approver key remains unpinned.
- Executor mutations use application-level CAS and a local serialization lock;
  Keycloak's REST API does not provide one atomic multi-operation transaction.
  Independent concurrent administrators can race apply. Post-verify detects
  observed differences and alarms; irreversible credential changes cannot be
  restored from metadata, so crash/partial failure requires reviewed recovery.
- Password reset verification uses exported credential IDs/timestamps and the
  UPDATE_PASSWORD flag, not exported secret material or a claim that screenshots
  establish a password value. Browser receipt verification trusts the published
  executor public key; its documented fingerprint is the bootstrap reference.
- The executor uses a bounded mutation whitelist. User creation/deletion,
  client-secret rotation and catch-all realm changes are refused even with a
  human signature. Provider-generated extra metadata must also match the exact
  proposal; otherwise post-verify fails and reversible fields are restored.
- A started execution without a terminal receipt is never automatically repeated.
  Local signed receipts are retained and Object Storage upload failures retried.
- Guest mode reserves three synthetic accounts for twenty minutes. Each slot
  can approve one temporary reset for its own account. Its scoped CAS covers
  the target's complete state and relevant realm policy. The main realm keeps
  full realm CAS. Three independent guest calls completed concurrently.
- Callback completed 40/60 legitimate benchmark tasks. Its per-planner median
  benchmark latency was about five minutes, including fresh-copy setup.
  The guest acceptance tests use warm copies. Ten baseline observations were
  incomplete, so their observed unauthorized effects are lower bounds.
- Voice is push-to-talk. Two-turn browser release/send-to-playback medians
  were 47.468 seconds in P7 acceptance and 68.441 seconds in the first final
  regression run. The final combined run measured 73.390 seconds. Provider
  and planner latency vary between runs.

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

Application health: https://callback-45-63-34-5.sslip.io/health
Executor public key: https://callback-45-63-34-5.sslip.io/executor-pubkey.json
Source: https://github.com/HassanHassnain/callback

Run `make setup`, `make preflight`, `make test`, `make lint`, and `make smoke`.
`make smoke` applies the documented audio-only exception and checks functional output.

Text preview: https://callback-45-63-34-5.sslip.io/call
Operator console: https://callback-45-63-34-5.sslip.io/console

- [Guest desk](https://callback-45-63-34-5.sslip.io/call?guest=1)
- [Recorded evidence](https://callback-45-63-34-5.sslip.io/console?demo=1)
- [Full benchmark](https://callback-45-63-34-5.sslip.io/race)
- [Saved application draft](https://lablab.build/ai-hackathons/vultr-hackathon/axiom-labs/submission)

## Recording and review steps

1. Use a fresh 1920×1080 browser profile and follow the timed narration in
   docs/video-script.md. Keep employee private keys and temporary passwords
   outside the recording profile.
2. Follow the recut's hook, why-now, pitch and how-it-works scenes from
   .local/recut-src/. Keep the synthetic audio and recorded-evidence labels.
3. Show the labelled synthetic Dana caller and the Qwen3-TTS Ryan agent line.
   Follow with the recorded Dana Gate, real-phone denial and verified receipt
   with equal production digests.
4. Show Hostile replay, its 14 observed OTP removals in the disposable twin,
   705.7 ms kill timing and signed unchanged-production receipt.
5. Show Sam's one APPLIED_VERIFIED reset, then the saved browser
   hash-mismatch refusal capture. Keep decrypted password material hidden.
6. Open /race for the full 540-case result and its caveats. Show the landing
   page architecture and /call?guest=1 simulated-device panel.
7. Close with the security-team and service-desk buyer. The final rendered
   video is .local/submission-media/Callback-demo-recut.mp4. The thirteen-scene
   cut, narration and source references are recorded in docs/video-script.md.
   Review the saved LabLab
   draft and await Hassan's explicit go for final submission.
