import copy

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec

from services.common.crypto import public_jwk
from services.common.sealed import seal, unseal_for_test


def test_delivery_is_bound_to_device_and_exact_change_hash():
    owner = ec.generate_private_key(ec.SECP256R1())
    stranger = ec.generate_private_key(ec.SECP256R1())
    binding = {"call_id": "test-call", "realm": "acme", "username": "sam.rivera", "change_set_hash": "a" * 64}
    payload = {"temporary_password": "synthetic-test-password"}
    box = seal(public_jwk(owner), payload, binding)
    assert unseal_for_test(owner, box) == payload
    assert payload["temporary_password"] not in str(box)
    with pytest.raises(InvalidTag):
        unseal_for_test(stranger, box)
    tampered = copy.deepcopy(box)
    tampered["binding"]["username"] = "dana.whitfield"
    with pytest.raises(InvalidTag):
        unseal_for_test(owner, tampered)
