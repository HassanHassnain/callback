"""Select verified recorded executions; never fabricate or edit result metrics."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state  # noqa: E402
from services.common.crypto import verify  # noqa: E402


def latest(pattern, marker):
    for path in sorted((ROOT / "docs/infra").glob(pattern), reverse=True):
        data = json.loads(path.read_text())
        if data.get(marker) is True:
            return path, data
    raise RuntimeError("No verified evidence: " + pattern)


def main():
    key = load_state()["executor_public_key"]
    phone_path, phone = latest("P5-real-phone-20*.json", "all_programmatic_checks_passed")
    operator_path, operator = latest("P6-operator-jobs-*.json", "all_passed")
    dana = phone["cases"]["dana_lost_phone"]
    sam = phone["cases"]["sam_reset"]
    hostile = operator["cases"]["hostile_replay"]["call"]
    for receipt in [dana["receipt"], sam["receipt"], hostile["receipt"]]:
        verify(key, receipt["payload"], receipt["signature"])
    manifest = {"mode": "evidence_replay", "description": "Recorded executions, not a new live call. Main-realm phone decisions and a separately labelled guest containment replay.",
        "source_reports": [str(phone_path.relative_to(ROOT)), str(operator_path.relative_to(ROOT))],
        "beats": [{"id": "dana", "title": "Dana · denied", "call_id": dana["call_id"], "origin": "Real physical-phone denial"},
            {"id": "hostile", "title": "Hostile replay", "call_id": hostile["call_id"], "origin": "Scripted execution · guest operator signer simulated"},
            {"id": "sam", "title": "Sam · verified", "call_id": sam["call_id"], "origin": "Real physical-phone approval"}]}
    destination = ROOT / "fixtures/demo_manifest.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n")
    print("Generated verified evidence replay manifest:", destination)


if __name__ == "__main__":
    main()
