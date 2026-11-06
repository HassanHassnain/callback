"""Strict signed change-set envelope shared by control and privileged executor."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

HEX64 = r"^[a-f0-9]{64}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Strict):
    user_id: str | None = Field(pattern=r"^[a-f0-9-]{36}$")
    username: str | None = Field(max_length=128)


class Effect(Strict):
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    type: Literal["user.password.reset", "user.required_action.added", "user.required_action.removed",
        "credential.otp.removed", "user.enabled.changed", "user.unlocked", "user.email.changed",
        "user.attribute.changed", "group.member.added", "group.member.removed", "role.granted", "role.revoked",
        "user.created", "user.deleted", "client.secret.changed", "realm.changed", "egress.attempted"]
    realm: Literal["acme", "acme-guest"]
    target: Target
    before: JsonValue
    after: JsonValue
    reversible: bool
    irreversible_reason: str | None = None
    evidence: dict[str, JsonValue]

    @model_validator(mode="after")
    def typed_payload(self):
        def exact(value, keys):
            return isinstance(value, dict) and set(value) == set(keys)

        def credential(value, kind):
            return (isinstance(value, dict) and {"id", "type"} <= set(value)
                and set(value) <= {"id", "type", "createdDate", "userLabel"} and value["type"] == kind)

        kind, before, after = self.type, self.before, self.after
        valid = True
        if kind == "user.password.reset":
            valid = (exact(before, ["credentials"]) and isinstance(before["credentials"], dict)
                and all(credential(v, "password") and k == v["id"] for k, v in before["credentials"].items())
                and exact(after, ["changed", "temporary"]) and after["changed"] is True and type(after["temporary"]) is bool)
        elif kind == "credential.otp.removed":
            valid = credential(before, "otp") and after is None
        elif kind.startswith("user.required_action."):
            valid = (before is None and isinstance(after, str)) if kind.endswith("added") else (isinstance(before, str) and after is None)
        elif kind == "user.enabled.changed":
            valid = type(before) is bool and type(after) is bool
        elif kind == "user.email.changed":
            valid = isinstance(before, (str, type(None))) and isinstance(after, str)
        elif kind == "user.attribute.changed":
            valid = (exact(before, ["attribute", "value"]) and exact(after, ["attribute", "value"])
                and before["attribute"] == after["attribute"] and isinstance(after["attribute"], str))
        elif kind.startswith("group.member."):
            valid = (exact(before, ["group", "member"]) and exact(after, ["group", "member"])
                and isinstance(after["group"], str) and before["group"] == after["group"]
                and type(before["member"]) is bool and type(after["member"]) is bool
                and before["member"] != after["member"] and after["member"] == kind.endswith("added"))
        elif kind.startswith("role."):
            valid = (exact(before, ["scope", "role", "granted"]) and exact(after, ["scope", "role", "granted"])
                and isinstance(after["scope"], str) and isinstance(after["role"], str)
                and before["scope"] == after["scope"] and before["role"] == after["role"]
                and type(before["granted"]) is bool and type(after["granted"]) is bool
                and before["granted"] != after["granted"] and after["granted"] == kind.endswith("granted"))
        elif kind == "user.unlocked":
            valid = isinstance(before, dict) and isinstance(after, dict)
        if not valid:
            raise ValueError("Effect payload does not match its typed operation")
        return self


class ChangeSet(Strict):
    call_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    realm: Literal["acme", "acme-guest"]
    seed_version: str = Field(min_length=1, max_length=128)
    prod_state_digest: str = Field(pattern=HEX64)
    guest_lease: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    effects: list[Effect] = Field(max_length=100)
    created_at: str = Field(max_length=64)


class Decision(Strict):
    change_set_hash: str = Field(pattern=HEX64)
    decision: Literal["approve", "deny"]
    ts: str = Field(max_length=64)
    username: str | None = Field(default=None, max_length=128)
    approver_id: str | None = Field(default=None, max_length=128)


class SignedDecision(Strict):
    kind: Literal["device", "approver"]
    payload: Decision
    signature: str = Field(min_length=80, max_length=100)


class ApplyRequest(Strict):
    change_set: ChangeSet
    change_set_hash: str = Field(pattern=HEX64)
    signatures: list[SignedDecision] = Field(max_length=10)
    context: dict[str, JsonValue] = Field(default_factory=dict)


def original(model):
    # The signature covers fields actually supplied; do not inject optional
    # defaults while re-serializing a parsed, already-signed object.
    return model.model_dump(exclude_unset=True)


class OperatorAction(Strict):
    purpose: Literal["operator_test"]
    action: Literal["hostile_replay", "fork_limit", "memory_limit", "filesystem"]
    realm: Literal["acme", "acme-guest"]
    approver_id: str = Field(min_length=1, max_length=128)
    nonce: str = Field(pattern=r"^[a-f0-9-]{36}$")
    ts: str = Field(max_length=64)


class OperatorProof(Strict):
    payload: OperatorAction
    signature: str = Field(min_length=80, max_length=100)
