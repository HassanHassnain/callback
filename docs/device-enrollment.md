# Real-device enrollment checkpoint

The P5 brief explicitly requires Hassan's phone as Dana and Sam, and his own
browser as approver. Automated guest keys do not satisfy this checkpoint.

Keep all three keys on their original devices/browsers. Use the regular browser,
not a private tab or an embedded preview. No private key or password needs to be
sent to Codex.

1. **On your phone**, open
   https://callback-45-63-34-5.sslip.io/device?user=dana.whitfield
   in Safari or Chrome. Verify the **Dana Whitfield · CFO** link is selected.
   Tap **Create enrollment request** if no request exists. An existing request
   can be reused; the former Refresh label meant it was already created.
   Copy the enrollment ID and note the signing
   key fingerprint. Keep the page open.
2. On the same phone, open
   https://callback-45-63-34-5.sslip.io/device?user=sam.rivera
   or tap the visible **Sam Rivera · Sales** link. Tap **Create enrollment request**. Copy Sam's enrollment ID and fingerprint.
   Dana's separate key remains in the same browser's IndexedDB.
3. **On your computer**, in your regular browser, open
   https://callback-45-63-34-5.sslip.io/enroll-approver
   and click **Create enrollment request**. Copy the approver enrollment ID and
   fingerprint. Use this same browser for subsequent approvals.
4. Reply in the chat with the three labelled enrollment IDs (Dana, Sam,
   approver). Codex retrieves only the signed public bundles and pins them using
   the task-owned executor's SSH connection. The fingerprints in the pin output
   must match the values on your devices. The pages then show **KEY PINNED**.

The executor refuses to overwrite an already pinned different key. All public
ceremony bundles are retained. Device encryption public keys are separately
registered so a production temporary password can be decrypted only on its
registered device. Non-extractable private keys never leave IndexedDB.

## After pinning

- A fresh Sam call stages a temporary reset in a disposable twin. On the phone,
  tap the Sam link, inspect the actual changes and hash, then tap **Approve exact
  changes**. A standard low-risk reset needs no operator signature. Once the
  independent executor reports **APPLIED VERIFIED**, reveal the temporary
  password **only on the phone**. Do not share it in chat or in demo recordings.
- A Dana lost-phone request requires both device and operator approval. Tap the Dana link
  on the phone and tap **Deny**. The signed receipt must report **DENIED**
  with identical production before/after digests.
- The console links to each receipt. The browser verifies the executor signature
  against the separately published public key before displaying a verified label.

Decisions expire after ten minutes. Frozen proposals wait for up to one hour;
execution twins retain their separate fifteen-minute hard lifetime and are
already destroyed before a proposal is exposed for consent.
An expired call needs a fresh request. Guest automated tests use separate
`acme-guest` keys and are explicitly simulated devices, not enrolled real phones.
