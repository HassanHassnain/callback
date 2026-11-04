# Callback status

Updated: 2026-11-04. P0 bootstrap and account setup complete; strict audio
model-identity acceptance is blocked by the provider response format.

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
- Seven local inference boundary tests and Ruff pass.

## P0 checkpoint

The latest full run is `docs/smoke/20261104T182141769962Z.json`: **9 PASS, 4 FAIL**.
All four failures are the TTS/STT response model ID being absent. The smoke
script exits 1 and `phase0_accepted` is false. No failure was relabelled a pass.

DeepSeek is the initial planner recommendation: both probes passed and their
combined latency was lowest in this single small fixture run. GLM and Qwen also
passed; this is not a broad quality benchmark. All keys work.

Awaiting the user's choice: continue P1 with voice disabled, or explicitly allow
catalog-validated audio with the missing per-response identity documented.
Voice remains gated until that decision. See `docs/account-setup.md` for setup.

## Not done

P1–P10. No infrastructure, application, production identity realm, benchmark,
phone enrollment, or submission assets have been deployed yet.

## Known limits

- Vultr speech SSE and transcription JSON responses omit `model`. Neither
  provides a model identity header. Strict identity checks therefore fail.
- GLM needed a 1024-token completion budget to avoid truncation on the schema
  probe. It reported reasoning tokens even with reasoning disabled in the request.
- Endpoint smoke tests do not establish moderation/injection detection accuracy,
  help-desk quality, production containment, or security of a deployed system.
- Limit increase is pending. Payment method still needs user setup to retain
  the hackathon account after its stated 30-day expiry.

## URLs and demo

No live demo yet. Source: https://github.com/HassanHassnain/callback

Run `make setup`, `make preflight`, `make test`, `make lint`, and `make smoke`.
`make smoke` intentionally fails while audio identity is unverifiable.
