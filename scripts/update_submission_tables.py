"""Populate the submission's measured tables from the generated race artifact."""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, marker, text):
    document = path.read_text()
    start, end = f"<!-- BENCH_{marker}_START -->", f"<!-- BENCH_{marker}_END -->"
    before, rest = document.split(start, 1)
    _, after = rest.split(end, 1)
    path.write_text(before + start + "\n" + text + "\n" + end + after)


def n(value):
    return "—" if value is None else f"{value:.5g}"


def pct(value):
    return "—" if value is None else f"{value:.0%}"


def main():
    result = json.loads((ROOT / "bench/results/latest.json").read_text())
    label = "Development sample" if result["mode"] == "sample" else (
        "Full matched run" if result["complete"] else "Partial matched run")
    scope = f"**{label}.** {result['observed_cases']} of {result['expected_cases']} cases in this run."
    if result["mode"] == "sample":
        scope += " The full matched design has 540 cases."
    readme = [
        scope, "",
        "| Planner | Arm | Cases | Errors | Unauthorized | Privileged | Legitimate | Mismatches | Median s | Mean USD |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["summary"]:
        readme.append("| " + " | ".join([
            row["planner"], row["arm"], str(row["n_cases"]), str(row["n_errors"]), n(row["unauthorized_effects"]),
            n(row["privileged_effects"]), pct(row["legitimate_completion_rate"]), n(row["mismatch_catches"]),
            n(row["median_seconds"]), n(row["cost_estimate_usd"]),
        ]) + " |")
    readme += ["", "[Generated method and raw results](docs/benchmark.md) · "
                   "[Race page](https://callback-45-63-34-5.sslip.io/race)"]
    replace(ROOT / "README.md", "README", "\n".join(readme))

    arms = defaultdict(list)
    for case in result["cases"]:
        arms[case["arm"]].append(case)
    deck = [
        scope, "",
        "| Arm | Measured cases | Unauthorized effects | Legitimate completions |",
        "| --- | ---: | ---: | ---: |",
    ]
    for arm in ("naive", "approve-description", "callback"):
        group = arms[arm]
        measured = [row for row in group if "unauthorized_effects" in row]
        unauthorized = sum(row["unauthorized_effects"] for row in measured)
        legit = [row for row in group if row["kind"] == "legitimate"]
        success = sum(row.get("legitimate_completed") is True for row in legit)
        deck.append(f"| {arm} | {len(measured)} | {unauthorized if measured else '—'} | {success} / {len(legit)} |")
    deck += ["", "The caller, device owner and approvers are simulated. The Keycloak copies and observed effects are real.",
             "", "[Open the generated race](https://callback-45-63-34-5.sslip.io/race)"]
    replace(ROOT / "docs/deck.md", "DECK", "\n".join(deck))


if __name__ == "__main__":
    main()
