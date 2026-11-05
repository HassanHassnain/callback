"""Pin a phone's public bundle through the task-owned executor's SSH boundary."""

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state, ssh  # noqa: E402
from services.executor.enrollment import validate_bundle  # noqa: E402
from services.common.crypto import digest  # noqa: E402


def main(kind="device"):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pending", help="Enrollment ID shown on the phone/browser")
    source.add_argument("--bundle", type=Path, help="Public signed enrollment bundle JSON")
    parser.add_argument("--realm", choices=["acme", "acme-guest"], required=True)
    parser.add_argument("--user" if kind == "device" else "--approver", dest="identity", required=True)
    args = parser.parse_args()
    state = load_state()
    if args.pending:
        if len(args.pending) != 64 or any(c not in "0123456789abcdef" for c in args.pending):
            parser.error("Invalid enrollment ID")
        response = httpx.get(state["public_url"] + "/api/enrollments/" + args.pending, timeout=20)
        response.raise_for_status()
        bundle = response.json()
    else:
        bundle = json.loads(args.bundle.read_text())
    payload = validate_bundle(bundle, check_time=False)
    if payload["kind"] != kind or payload["realm"] != args.realm or payload["identity"] != args.identity:
        raise RuntimeError("Displayed enrollment does not match the requested kind, realm and identity")
    public_json = json.dumps(bundle)
    script = "set -e\ncd /opt/callback\ndocker compose exec -T executor /opt/callback/.venv/bin/python - <<'CALLBACK_ENROLL'\n"
    script += "import json\nfrom services.executor.enrollment import pin\nfrom services.executor.keycloak import config_from_file\n"
    script += "bundle=json.loads(" + repr(public_json) + ")\nprint(json.dumps(pin(bundle,config_from_file())))\nCALLBACK_ENROLL\n"
    print("Pinning public key fingerprint: " + digest(payload["public_key"]), flush=True)
    result = ssh(state, "executor", script, timeout=120, check=False)
    if result.returncode:
        # Error types/messages contain no credential-bearing HTTP response body.
        raise RuntimeError("Executor refused enrollment; existing keys were preserved. " + result.stderr[-600:])
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
