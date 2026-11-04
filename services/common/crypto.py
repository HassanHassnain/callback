"""Canonical hashes and WebCrypto-compatible ECDSA P-256 signatures."""

import base64
import hashlib
from pathlib import Path

import rfc8785
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature


def canonical(data) -> bytes:
    return rfc8785.dumps(data)


def digest(data) -> str:
    return hashlib.sha256(canonical(data)).hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def load_or_create_key(path: Path):
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        path.chmod(0o600)
        file.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    return key


def public_jwk(key) -> dict:
    public = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    numbers = public.public_numbers()
    return {"kty": "EC", "crv": "P-256", "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big")), "ext": True, "key_ops": ["verify"]}


def sign(key, data) -> str:
    der = key.sign(canonical(data), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def verify(jwk: dict, data, signature: str) -> None:
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("Expected an ECDSA P-256 public key")
    public = ec.EllipticCurvePublicNumbers(int.from_bytes(unb64url(jwk["x"]), "big"),
                                          int.from_bytes(unb64url(jwk["y"]), "big"),
                                          ec.SECP256R1()).public_key()
    raw = unb64url(signature)
    if len(raw) != 64:
        raise ValueError("Expected a 64-byte WebCrypto signature")
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, canonical(data), ec.ECDSA(hashes.SHA256()))
