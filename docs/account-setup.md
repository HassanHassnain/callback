# Account setup — 2026-11-04

## Verified

- GitHub CLI authenticated as HassanHassnain; public MIT repository created:
  https://github.com/HassanHassnain/callback
- Lablab showed Enrolled and access to the Axiom Labs team dashboard, with
  Hassan Hasnain listed as a team member. No submission has been made.
- Vultr gift credit confirmed: $200 available at setup.
- Vultr account email verified through its official welcome email link.
- Account API enabled; the newly generated key is stored only in local `.env`.
- Current Mac IPv4 added as a /32 API allowlist entry. The portal's existing
  IPv6 entry was preserved; global IPv4/IPv6 access was not enabled.
- Serverless Inference subscription `callback` created and shown Active.
- Inference key saved locally. Both authenticated account and inference usage
  API requests returned HTTP 200.
- `.env` permissions are 0600 and it is ignored and untracked by git.
- Network access is working for Vultr, GitHub, and package installation.

## Instance limits

The account initially allowed 5 instances, with none provisioned. This is
enough for the four planned VMs. On the user's instruction, a request for 10
instances was submitted and received as ticket **ZAU-63SXJ**. The monthly
instance cost limit remains $200. Approval is pending.

The request identifies **Callback (independent hackathon project)**, category
Individual, organization size 0–1. It does not identify Rooya as the organization
using the account. Personal contact/address details are not stored in this repo.

## Preservation

The `callback/` directory and its GitHub repository did not exist at task start.
Read-only API inventories at setup showed no existing instances, VPCs, or SSH
keys. Local inventories are retained under ignored `.local/`. Any future
teardown must use recorded ownership of resources created by this task; never
delete an item merely because its label matches the project name.

## Outstanding

- Instance-limit increase: submitted, not yet approved.
- A phone and browser signing-key ceremony occurs in P5.
- Vultr's hackathon welcome email says account access expires in 30 days unless
  a valid payment method is added. No payment method was added by this task.
- Audio responses omit a model identifier; this conflicts with the brief's
  per-response identity assertion. See `models.md` and the smoke evidence.

Official pages: [API access](https://console.vultr.com/user/apiaccess/),
[inference](https://console.vultr.com/inference/),
[limits](https://console.vultr.com/billing/#billinglimits).
