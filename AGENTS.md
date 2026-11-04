# Callback project instructions

Read `docs/BRIEF.md` for the complete build specification.

## User instruction — preservation boundary

Preserve every file, cloud resource, account item, key, and project that existed before this Callback task began on 2026-11-04. Teardown commands and destructive tests are authorized only for disposable resources created by this task. Record ownership in infrastructure state; never delete based only on a matching name. Do not rewrite pushed history.

## Brief non-negotiables (verbatim)

**User-approved exception, 2026-11-04:** For Vultr TTS/STT only, allow audio
using live catalog validation when the provider omits response model identity.
Record `model_id_verified=false` and `identity_validation=catalog_only_user_exception`;
never invent a returned model ID. A returned but mismatched model still fails.
All chat, vision, moderation, and decision responses retain exact model checks.
This explicit user instruction supersedes item 2 below only for that omission.

1. **Use only Vultr Serverless Inference** for every runtime model call: LLM, vision, decision, STT, TTS, moderation. Never call OpenAI, Anthropic or other model APIs at runtime.
2. **The model ID must match.** Every Serverless Inference call asserts that the response's `model` equals the requested model. Unknown IDs silently fall back to `deepseek-v4.1-flash-1017`, which must raise an error, not pass silently.
3. **No secrets in sandboxes.** Twins get only twin-only throwaway credentials and planted **canary** values. The inference key, Vultr API key, production admin credential and all signing keys never enter a sandbox, its image or its environment.
4. **The sandbox is the only place agent actions execute.** The control plane never runs agent-supplied code or commands on itself.
5. **The executor is the only holder of the production admin credential.** It accepts only canonical typed change sets with valid signatures. It never processes free text from callers or agents.
6. **Never fake a result.**
   - No hard-coded numbers in the UI or README: benchmark numbers come from files in `bench/results/`.
   - Anything simulated must be labelled as simulated in both the UI and the README (for example the guest-mode simulated phone, or benchmark approver bots).
   - Judges read repos.
7. **Commit early and often.**
   - Small commits with meaningful messages after every working step; at least 30 commits across the week.
   - Push to GitHub after each phase.
   - Never squash or rewrite pushed history.
8. **Never print, log or commit secrets.** `.env` is gitignored. Logs redact anything that looks like a key.
9. **MIT license.**
   - Do not vendor GPL or AGPL code into the repo. Running Keycloak (Apache-2.0) as a separate container is fine.
   - Disclose in the README: "Implementation by OpenAI Codex; research, design and review with Claude."
10. **Honest limits.** Keep a running "Known limits" list in `docs/STATUS.md`.
11. **Log the build.** After each phase, append to `docs/BUILD_LOG.md`: what was built, how it was verified (the commands you ran and their output summary), what's left, and decisions made.
12. **Ask only when blocked.** Stop for the human only at ⛳ checkpoints or when a kill criterion fires and its fallback fails. Otherwise make a sensible call and record it in BUILD_LOG.

