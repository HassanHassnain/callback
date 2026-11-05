"""Verify actual phone decisions and public tamper refusal without fetching passwords."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state  # noqa: E402
from services.common.crypto import verify  # noqa: E402


def main():
    state = load_state()
    client = httpx.Client(base_url=state["public_url"], timeout=150)
    active = json.loads((ROOT / ".local/real-phone/active.json").read_text())
    report = {"observed_at": datetime.now(UTC).isoformat(), "realm": "acme", "simulated_device": False,
        "device_provenance": "User confirmed physical-phone enrollment; decisions verified by executor using production-registered keys",
        "checks": {}, "cases": {}}
    for name, identifier in active.items():
        response = client.get("/api/calls/" + identifier)
        response.raise_for_status()
        call = response.json()
        if not call.get("receipt"):
            print(name, "pending", call["status"], flush=True)
            raise SystemExit(2)
        receipt = call["receipt"]
        verify(state["executor_public_key"], receipt["payload"], receipt["signature"])
        payload = receipt["payload"]
        checks = {"signed_receipt": True, "real_phone_context": payload["context"]["simulated_device"] is False,
            "twin_destroyed": bool(payload["context"]["twin"].get("destroyed_at")) and bool(call.get("destroy_proof")),
            "exact_models": bool(call["model_calls"]) and all(m["model_id_verified"] for m in call["model_calls"])}
        if name == "sam_reset":
            checks.update({"applied_verified": payload["status"] == "APPLIED_VERIFIED" and payload["verified"],
                "one_sam_reset": len(payload["actual_effects"]) == 1 and payload["actual_effects"][0]["type"] == "user.password.reset"
                    and payload["actual_effects"][0]["target"]["username"] == "sam.rivera",
                "device_only_auto": call["policy"]["outcome"] == "AUTO" and not call["policy"]["requires_human"]
                    and len(payload["signatures"]) == 1 and payload["signatures"][0]["kind"] == "device"})
            response = client.post("/api/calls/" + identifier + "/tamper")
            response.raise_for_status()
            tamper = response.json()["receipt"]
            verify(state["executor_public_key"], tamper["payload"], tamper["signature"])
            checks["public_tamper_refused"] = tamper["payload"]["status"] == "REFUSED" and tamper["payload"]["reason"]["code"] == "HASH_MISMATCH"
            report["tamper_receipt"] = tamper
        else:
            checks.update({"signed_denial": payload["status"] == "DENIED" and any(s["kind"] == "device" and s["payload"]["decision"] == "deny" for s in payload["signatures"]),
                "production_unchanged": payload["prod_state_digest_before"] == payload["prod_state_digest_after"],
                "privileged_otp_policy": {"R5", "R6"} <= set(call["policy"]["rule_ids"])})
        report["cases"][name] = {"call_id": identifier, "checks": checks, "receipt": receipt}
        report["checks"].update({name + ":" + key: value for key, value in checks.items()})
    report["phone_password_display_confirmed_by_user"] = "--phone-display-confirmed" in sys.argv
    report["all_programmatic_checks_passed"] = all(report["checks"].values())
    path = ROOT / "docs/infra" / ("P5-real-phone-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_programmatic_checks_passed": report["all_programmatic_checks_passed"], "checks": report["checks"], "evidence": str(path)}), flush=True)
    if not report["all_programmatic_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
