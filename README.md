# Callback

**The AI IT help desk that can't be sweet-talked.**

Approval prompts show what the agent says it will do. Callback shows what it
actually did — in a twin — and only that can reach production.

Callback is being built for Vultr: Agent Rush, Challenge 1, Blast Radius Zero.
P0 model, P1 infrastructure, P2 identity/seed, and P3 containment checks pass. Both synthetic
realms have 40 employees and 14 admins. Signed, scrubbed twin seeds are exported
every two minutes. Real gVisor/Chromium twins and containment tests are documented
in [the threat model](docs/threat-model.md), with raw measured evidence. There is
no call UI, production apply path or benchmark result yet. Infrastructure-only [health](https://callback-45-63-34-5.sslip.io/health)
explicitly reports `application_ready=false`. See [build status](docs/STATUS.md) and the [complete brief](docs/BRIEF.md).

The intended production boundary is a disposable Keycloak twin, typed effects
derived from its state, deterministic policy, device and approver signatures
over the exact change-set hash, and a separate executor that verifies production
after applying the approved effects. Runtime model calls use only Vultr
Serverless Inference.

## Development

Install Python 3.12 and uv, then run `make setup`. Create `.env` using
`.env.example` as the template; never commit or print the populated file.
Run `make catalog` to record the current model catalog and `make smoke` to
exercise the required model capabilities against Vultr. Audio uses the explicit
user-approved catalog-validation exception because Vultr omits per-response
TTS/STT model identity; chat and decision responses require exact model IDs.

`make provision`, `make status`, `make deploy`, and `make verify-infra` operate
only on the recorded project infrastructure. `make teardown-plan` is a dry run;
actual teardown requires an explicit `--execute` argument and matching live
ownership metadata. Estimated base services are $173.08/month before usage.
The sandbox uses the brief's smaller 16-GB plan, and the private registry is in SJC.
See [infrastructure evidence](docs/infra/P1-resources.json).

Existing files, cloud resources, and account items from before this task are
preserved. Destructive tests and teardown apply only to resources created by
this project, with recorded ownership.

## Attribution

Implementation by OpenAI Codex; research, design and review with Claude.

MIT licensed; see [LICENSE](LICENSE).
