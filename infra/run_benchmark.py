"""Launch or collect a matched benchmark on the recorded Callback sandbox."""

import argparse
import json
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values

from bench.run import report
from infra.remote import load_state, ssh, upload

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Also update the generated latest.json and docs table")
    parser.add_argument("--sample", type=int, choices=range(1, 21))
    parser.add_argument("--workers", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--turns", type=int, choices=range(1, 13), default=12)
    parser.add_argument("--budget", choices=["12", "20"], default="12")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", args.run_id):
        parser.error("Invalid run ID")
    state = load_state()
    if args.collect:
        result = ssh(state, "sandbox", "cat /opt/callback/bench/results/" + args.run_id + ".json")
        raw = json.loads(result.stdout)
        assert raw["run_id"] == args.run_id
        report(args.run_id, SimpleNamespace(sample=raw["mode"] == "sample", turns=raw["max_turns"], publish=args.publish),
               raw["cases"], raw["expected_cases"], raw["seed_version"], created_at=raw["created_at"])
        print(f"Collected {raw['observed_cases']}/{raw['expected_cases']} cases from {args.run_id}")
        if args.publish:
            content = (ROOT / "bench/results/latest.json").read_text()
            assert "CALLBACK_BENCH_RESULT" not in content
            ssh(state, "control", "set -e\nmkdir -p /opt/callback/bench/results\n"
                "cat > /opt/callback/bench/results/latest.tmp <<'CALLBACK_BENCH_RESULT'\n"
                + content + "\nCALLBACK_BENCH_RESULT\nmv /opt/callback/bench/results/latest.tmp /opt/callback/bench/results/latest.json\n")
        return
    if args.publish:
        parser.error("--publish is used when collecting results")
    # Transfer explicit sources only. A local bench cache never enters rsync.
    ssh(state, "sandbox", "umask 077; mkdir -p /opt/callback/bench/.cache")
    upload(state, "sandbox", [ROOT / "services", ROOT / "fixtures"])
    for relative in ("bench/run.py", "bench/arms/runtime.py", "bench/scenarios/attacks.yaml", "bench/scenarios/legitimate.yaml"):
        payload = (ROOT / relative).read_text()
        dest = "/opt/callback/" + relative
        delimiter = "CALLBACK_BENCH_SOURCE"
        assert delimiter not in payload
        ssh(state, "sandbox", f"mkdir -p {shlex.quote(str(Path(dest).parent))}\n"
            f"cat > {shlex.quote(dest)} <<'{delimiter}'\n{payload}\n{delimiter}\n")
    key = dotenv_values(ROOT / ".env")["VULTR_INFERENCE_API_KEY"]
    if not key or "\r" in key or "\n" in key:
        raise RuntimeError("Invalid inference credential")
    command = ["/opt/callback/.venv/bin/python", "-m", "bench.run", "--run-id", args.run_id,
               "--workers", str(args.workers), "--turns", str(args.turns), "--budget", args.budget,
               "--inference-key-file", "/opt/callback/bench/.cache/inference-key"]
    if args.retry_errors:
        command.append("--retry-errors")
    if args.sample:
        command += ["--sample", str(args.sample)]
    script = ("set -e\numask 077\ncat > /opt/callback/bench/.cache/inference-key <<'CALLBACK_KEY'\n"
              + key + "\nCALLBACK_KEY\n" +
              "systemd-run --unit=callback-bench-" + args.run_id + " --working-directory=/opt/callback " + shlex.join(command))
    result = ssh(state, "sandbox", script, check=False)
    if result.returncode:
        raise RuntimeError("Benchmark launcher failed; check the owned service and run identifier")
    print("Started matched benchmark " + args.run_id)


if __name__ == "__main__":
    main()
