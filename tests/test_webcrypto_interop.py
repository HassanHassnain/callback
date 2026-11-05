"""Exercise the actual browser module using Node's WebCrypto, not a reimplementation."""
import json
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.common.crypto import b64url, digest, public_jwk, sign, verify
from services.common.sealed import seal


def test_python_seal_browser_decrypt_and_browser_sign_python_verify():
    device = ec.generate_private_key(ec.SECP256R1())
    executor = ec.generate_private_key(ec.SECP256R1())
    binding = {"call_id": "test", "realm": "acme-guest", "username": "simulated", "change_set_hash": "a" * 64}
    expected = {"temporary_password": "synthetic-test-only", "required_action": "UPDATE_PASSWORD"}
    vectors = {"€": 1e-7, "😀": [None, True, 1e30], "a": "newline\n", "z": -0.0}
    payload = {"status": "APPLIED_VERIFIED", "test": vectors}
    private = device.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    data = {"private": b64url(private), "box": seal(public_jwk(device), expected, binding), "binding": binding,
        "vectors": vectors, "key": public_jwk(executor), "receipt": {"payload": payload, "signature": sign(executor, payload)}}
    script = '''
import {decrypt,unbase64,signed,fingerprint,verifyReceipt} from './web/src/crypto.ts';
let input='';for await(const chunk of process.stdin)input+=chunk;const d=JSON.parse(input);
const encryption={privateKey:await crypto.subtle.importKey('pkcs8',unbase64(d.private),{name:'ECDH',namedCurve:'P-256'},false,['deriveBits'])};
const signing=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);
const slot={encryption,signing};const opened=await decrypt(slot,d.box,d.binding);
let wrongBindingRejected=false;try{await decrypt(slot,d.box,{...d.binding,username:'wrong'});}catch{wrongBindingRejected=true;}
globalThis.fetch=async()=>({ok:true,json:async()=>d.key});await verifyReceipt(d.receipt);
let tamperRejected=false;try{await verifyReceipt({...d.receipt,payload:{...d.receipt.payload,status:'tampered'}});}catch{tamperRejected=true;}
console.log(JSON.stringify({opened,wrongBindingRejected,tamperRejected,hash:await fingerprint(d.vectors),proof:await signed(slot,d.vectors),public:await crypto.subtle.exportKey('jwk',signing.publicKey),nonExtractable:!signing.privateKey.extractable}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(data), text=True,
        capture_output=True, cwd=Path(__file__).resolve().parents[1], check=True)
    actual = json.loads(result.stdout)
    assert actual["opened"] == expected
    assert actual["hash"] == digest(vectors)
    assert actual["wrongBindingRejected"] and actual["tamperRejected"] and actual["nonExtractable"]
    verify(actual["public"], vectors, actual["proof"]["signature"])
