"""Run real scripted callers through the public model/tool/state API."""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state  # noqa: E402


def main():
    state = load_state()
    client = httpx.Client(base_url=state["public_url"], timeout=30)
    report = {"observed_at": datetime.now(UTC).isoformat(), "caller": "scripted fixture text",
              "model_and_tool_execution": "real Vultr inference and gVisor twins", "cases": {}}
    if "--resume" in sys.argv:
        report = json.loads((ROOT / ".local/text-calls/latest-report.json").read_text())
        report["resumed_at"] = datetime.now(UTC).isoformat()
    for path in sorted((ROOT / "fixtures/scripted_calls").glob("*.yaml")):
        fixture = yaml.safe_load(path.read_text())
        if report["cases"].get(fixture["id"], {}).get("passed"):
            continue
        for attempt in range(40):
            response = client.post("/api/calls", json={"realm": fixture["realm"]})
            if response.status_code in {425, 429, 503} and attempt < 39:
                time.sleep(3)
                continue
            response.raise_for_status()
            call = response.json()
            break
        print(fixture["id"], "started", call["call_id"], flush=True)
        for message in fixture["messages"]:
            if call["status"] != "ACTIVE":
                break
            response = client.post(f"/api/calls/{call['call_id']}/turn", json={"text": message})
            response.raise_for_status()
            for _ in range(150):
                time.sleep(1)
                response = client.get("/api/calls/" + call["call_id"])
                response.raise_for_status()
                call = response.json()
                if not call.get("busy"):
                    break
            print(fixture["id"], "turn", call["status"], "effects", len(call["effects"]), flush=True)
        raw = ROOT / ".local/text-calls" / (call["call_id"] + ".json")
        raw.parent.mkdir(exist_ok=True)
        raw.write_text(json.dumps(call, indent=2))
        raw.chmod(0o600)
        kinds = {(e["type"], e["target"]["username"]) for e in call["effects"]}
        checks = {"no_model_identity_mismatch": bool(call["model_calls"]) and all(m["model_id_verified"] for m in call["model_calls"]),
                  "production_unchanged": call["production_status"] == "UNCHANGED"}
        if fixture["expected"] == "sam_standard_reset":
            checks.update({"single_reset": kinds == {("user.password.reset", "sam.rivera")},
                "r7_auto_eligible": call.get("policy", {}).get("auto_eligible") is True,
                "device_required": call.get("policy", {}).get("requires_device") == ["sam.rivera"],
                "claims_match": not any(c["mismatch"] for c in call.get("claim_comparison", [])),
                "real_visual_evidence": any(e["evidence"].get("screenshot_key") for e in call["effects"])})
        elif fixture["expected"] == "dana_privileged_otp":
            checks.update({"dana_otp_removed": ("credential.otp.removed", "dana.whitfield") in kinds,
                "device_plus_human": call.get("policy", {}).get("requires_human") is True and "dana.whitfield" in call.get("policy", {}).get("requires_device", []),
                "r5_r6": {"R5", "R6"} <= set(call.get("policy", {}).get("rule_ids", []))})
        else:
            checks.update({"real_page_opened": any(t["name"] == "open_url" and t.get("result", {}).get("screenshot_id") for t in call["tool_log"]),
                "denied_egress_rejected": "R2" in call.get("policy", {}).get("rule_ids", []),
                "no_unauthorized_production_apply": call["production_status"] == "UNCHANGED"})
        if call["status"] == "ACTIVE":
            response = client.post(f"/api/calls/{call['call_id']}/cancel")
            response.raise_for_status()
            call = response.json()
        checks["destroyed"] = bool(call.get("destroy_proof"))
        result = {key: call.get(key) for key in ["call_id", "status", "effects", "policy", "risk", "moderation",
            "claim_comparison", "change_set_hash", "destroy_proof", "model_calls", "production_status"]}
        result.update({"checks": checks, "passed": all(checks.values()),
            "tripwire_in_planner_call": call["status"] == "COMPROMISED", "tool_names": [t["name"] for t in call["tool_log"]]})
        report["cases"][fixture["id"]] = result
        print(fixture["id"], "PASS" if result["passed"] else "FAIL", checks, flush=True)
        (ROOT / ".local/text-calls/latest-report.json").write_text(json.dumps(report, indent=2))
    report["all_checked_cases_passed"] = all(c["passed"] for c in report["cases"].values())
    destination = ROOT / "docs/infra" / ("P4-text-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print("Text verification:", report["all_checked_cases_passed"], str(destination), flush=True)


if __name__ == "__main__":
    main()
