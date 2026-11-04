import json
import shutil
import subprocess

import pytest
from cryptography.exceptions import InvalidSignature

from services.common.crypto import canonical, digest, load_or_create_key, public_jwk, sign, verify


def test_jcs_uses_canonical_key_order_and_hash_binds_every_field():
    assert canonical({"z": 1, "a": [True, None]}) == b'{"a":[true,null],"z":1}'
    assert digest({"z": 1, "a": [True, None]}) == digest({"a": [True, None], "z": 1})
    assert digest({"target": "sam.rivera"}) != digest({"target": "dana.whitfield"})


def test_signature_rejects_tampering_and_private_key_stays_owner_only(tmp_path):
    path = tmp_path / "signing.pem"
    key = load_or_create_key(path)
    jwk = public_jwk(key)
    value = {"change_set_hash": "abc", "decision": "approve"}
    signature = sign(key, value)
    verify(jwk, value, signature)
    with pytest.raises(InvalidSignature):
        verify(jwk, {**value, "decision": "deny"}, signature)
    assert path.stat().st_mode & 0o077 == 0
    assert "d" not in jwk


def test_python_signature_is_verified_by_node_webcrypto(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node WebCrypto is unavailable")
    key = load_or_create_key(tmp_path / "key.pem")
    value = {"change_set_hash": "012345", "decision": "approve", "ts": 123}
    payload = {"jwk": public_jwk(key), "signature": sign(key, value),
               "message": canonical(value).decode()}
    code = """const {webcrypto}=require('node:crypto');let input='';
process.stdin.on('data',x=>input+=x);process.stdin.on('end',async()=>{
const d=JSON.parse(input);const k=await webcrypto.subtle.importKey('jwk',d.jwk,{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
const ok=await webcrypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},k,Buffer.from(d.signature,'base64url'),Buffer.from(d.message));
process.exit(ok?0:1);});"""
    subprocess.run([node, "-e", code], input=json.dumps(payload), text=True, check=True, timeout=10)
