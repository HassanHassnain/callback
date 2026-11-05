"""Registered-device password delivery: ephemeral P-256 ECDH, HKDF, AES-GCM."""

import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.common.crypto import b64url, canonical, public_jwk, unb64url


def public_key(jwk):
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or "d" in jwk:
        raise ValueError("Expected a public P-256 JWK")
    x, y = unb64url(jwk["x"]), unb64url(jwk["y"])
    if len(x) != 32 or len(y) != 32:
        raise ValueError("Invalid P-256 coordinate length")
    return ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                        ec.SECP256R1()).public_key()


def derive(shared, salt, binding):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b"callback-device-delivery-v1\x00" + canonical(binding)).derive(shared)


def seal(device_jwk, payload, binding):
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    shared = ephemeral.exchange(ec.ECDH(), public_key(device_jwk))
    salt, nonce = os.urandom(32), os.urandom(12)
    ciphertext = AESGCM(derive(shared, salt, binding)).encrypt(nonce, canonical(payload), canonical(binding))
    jwk = public_jwk(ephemeral)
    jwk["key_ops"] = []
    return {"version": 1, "ephemeral_public_key": jwk, "salt": b64url(salt), "nonce": b64url(nonce),
            "ciphertext": b64url(ciphertext), "binding": binding}


def unseal_for_test(device_private_key, box):
    """Test/benchmark simulated-device helper; production decryption runs in WebCrypto."""
    shared = device_private_key.exchange(ec.ECDH(), public_key(box["ephemeral_public_key"]))
    key = derive(shared, unb64url(box["salt"]), box["binding"])
    plaintext = AESGCM(key).decrypt(unb64url(box["nonce"]), unb64url(box["ciphertext"]), canonical(box["binding"]))
    return json.loads(plaintext)
