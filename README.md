# Callback

**The AI IT help desk that can't be sweet-talked.**

Approval prompts show what the agent says it will do. Callback shows what it
actually did — in a twin — and only that can reach production.

Callback is being built for Vultr: Agent Rush, Challenge 1, Blast Radius Zero.
P0–P4 checks pass. Both synthetic realms have 40 employees and 14 admins.
Signed, scrubbed twin seeds are exported every two minutes. Real gVisor/Chromium
twins and measured containment evidence are documented in the
[threat model](docs/threat-model.md).

The public [text call](https://callback-45-63-34-5.sslip.io/call),
[operator console](https://callback-45-63-34-5.sslip.io/console),
[phone consent page](https://callback-45-63-34-5.sslip.io/device), and signed
receipt viewer are live. Health reports the actual P5 runtime and apply readiness.
The executor accepts strict typed changes, independently verifies device and
operator signatures, checks its own policy floor and production CAS, applies
through pinned-TLS Keycloak, re-exports production, and signs its result.
Temporary passwords are generated only by the executor and forwarded only as
ECDH/HKDF/AES-GCM ciphertext for the registered device to decrypt.

The full public guest test passes with real Vultr planning, twin mutation,
state-derived effects, automatic signed apply, post-verification, encrypted
password delivery and hash-tamper refusal. **Guest device keys/signatures in
these tests are simulated.** The executor, signatures, REST changes and receipts
are real. UI banners and each report identify that distinction. Direct executor
checks additionally exercise signed denial and real production drift. Evidence:
`docs/infra/P5-public-20261105T180001Z.json` and the P5 executor reports.

**The real-phone P5 checkpoint is pending.** Hassan must enroll his actual phone
as Dana and Sam. His regular Chrome browser is enrolled as approver; automated guest keys do not
satisfy it. [Exact enrollment steps](docs/device-enrollment.md). No complete MVP,
voice flow, benchmark, finished submission assets or hackathon submission is
claimed yet. See [build status](docs/STATUS.md) and the [complete brief](docs/BRIEF.md).
All runtime model calls use only Vultr Serverless Inference.

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

The ordinary planner refused the hostile page instructions in the recorded text
case. A separate, clearly labelled operator replay exercises the malicious
commands and an explicitly simulated benign agent claim. Its identity mutations,
state diff, network denial and tripwire kill are real; it is not presented as
planner-generated behavior. See `docs/infra/P4-operator-replay-20261105T170523Z.json`.
