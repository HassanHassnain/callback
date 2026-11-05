# Real-device enrollment checkpoint

The P5 brief explicitly requires Hassan's phone as Dana and Sam, and his own
browser as approver. Automated guest keys do not satisfy this checkpoint.

Keep all three keys on their original devices/browsers. Use the regular browser,
not a private tab or an embedded preview. No private key or password needs to be
sent to Codex.

1. **On your phone**, open
   https://callback-45-63-34-5.sslip.io/device?user=dana.whitfield
   in Safari or Chrome. Verify **Dana Whitfield · CFO** in Device slot.
   Tap **Create enrollment request**. Copy the enrollment ID and note the signing
   key fingerprint. Keep the page open.
2. On the same phone, choose **Sam Rivera · Sales** in **Device slot**.
   Tap **Create enrollment request**. Copy Sam's enrollment ID and fingerprint.
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
  choose Sam, inspect the actual changes and hash, then tap **Approve exact
  changes**. A standard low-risk reset needs no operator signature. Once the
  independent executor reports **APPLIED VERIFIED**, reveal the temporary
  password **only on the phone**. Do not share it in chat or in demo recordings.
- A Dana lost-phone request requires both device and operator approval. Choose
  Dana on the phone and tap **Deny**. The signed receipt must report **DENIED**
  with identical production before/after digests.
- The console links to each receipt. The browser verifies the executor signature
  against the separately published public key before displaying a verified label.

Decisions expire after ten minutes. Proposals expire after fifteen minutes.
An expired call needs a fresh request. Guest automated tests use separate
`acme-guest` keys and are explicitly simulated devices, not enrolled real phones.
