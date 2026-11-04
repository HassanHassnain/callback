# Callback

**The AI IT help desk that can't be sweet-talked.**

Approval prompts show what the agent says it will do. Callback shows what it
actually did — in a twin — and only that can reach production.

Callback is being built for Vultr: Agent Rush, Challenge 1, Blast Radius Zero.
The implementation is in Phase 0. There is no live application or benchmark
result yet. See [build status](docs/STATUS.md) and the [complete brief](docs/BRIEF.md).

The intended production boundary is a disposable Keycloak twin, typed effects
derived from its state, deterministic policy, device and approver signatures
over the exact change-set hash, and a separate executor that verifies production
after applying the approved effects. Runtime model calls use only Vultr
Serverless Inference.

## Development

Install Python 3.12 and uv, then run `make setup`. Create `.env` using
`.env.example` as the template; never commit or print the populated file.
Run `make catalog` to record the current model catalog and `make smoke` to
exercise the required model capabilities against Vultr.

Existing files, cloud resources, and account items from before this task are
preserved. Destructive tests and teardown apply only to resources created by
this project, with recorded ownership.

## Attribution

Implementation by OpenAI Codex; research, design and review with Claude.

MIT licensed; see [LICENSE](LICENSE).
