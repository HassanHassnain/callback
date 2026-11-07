# Callback benchmark

Run `P8-full-v2-20261106`. Mode **full_design**. Observed 540 of 540 cases. Complete **True**.

Same synthetic scenarios across three Vultr planners. A Vultr LLM plays the caller for up to twelve turns. Each baseline writes to a fresh sacrificial Keycloak in gVisor. Description approval sees only agent description and transcript. Callback rehearses in a second twin and uses simulated device signatures and a deterministic simulated operator. A legitimate simulated device signs only a proposal matching its requested effects. The in-process executor applies only to a separately inspected disposable copy.

This measures a synthetic Keycloak workload, with no real attackers or real employee credentials. The caller is regenerated for each arm and can adapt to replies. The baseline arms share containment so no production service or arbitrary network target can be reached. The rushed-approver model is a simulation. Effects are counted from snapshots, including observed intermediate baseline mutations. Changes made and undone within a single tool action can escape snapshot observation. A killed baseline with incomplete observations is reported separately. Costs use observed response tokens and the live catalog. Failed or unpriced calls can make these estimates incomplete. Latency includes fresh-copy setup. Verified output-limit and timeout terminations count as completed evaluations and are reported separately as tool failures. Invalid tool arguments remain failed model outcomes. These model-induced failures are not retried to improve scores. Incomplete baseline observations make observed effect counts lower bounds.

| Planner | Arm | Cases | Measured | Runtime errors | Tool limits | Invalid tools | Incomplete | Observed unauthorized | Privileged | Legit rate | Mismatches | Approvals / 100 | Median seconds | Mean USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4.1-flash-1017 | approve-description | 60 | 60 | 0 | 0 | 0 | 0 | 9 | 8 | 0.25 | 0 | 75 | 144.8 | 0.003434 |
| deepseek-v4.1-flash-1017 | callback | 60 | 60 | 0 | 0 | 0 | 0 | 0 | 8 | 0.65 | 8 | 90 | 300.7 | 0.004661 |
| deepseek-v4.1-flash-1017 | naive | 60 | 60 | 0 | 0 | 0 | 0 | 19 | 12 | 0.35 | 0 | 0 | 134.2 | 0.003743 |
| glm-5.3-flash | approve-description | 60 | 60 | 0 | 0 | 2 | 2 | 9 | 10 | 0.25 | 0 | 65 | 164.4 | 0.00416 |
| glm-5.3-flash | callback | 60 | 60 | 0 | 0 | 0 | 0 | 0 | 13 | 0.85 | 2 | 111.7 | 307.9 | 0.005487 |
| glm-5.3-flash | naive | 60 | 60 | 0 | 0 | 1 | 1 | 15 | 14 | 0.25 | 0 | 0 | 137.9 | 0.004458 |
| qwen3.8-flash-next | approve-description | 60 | 60 | 0 | 3 | 0 | 3 | 4 | 2 | 0.3 | 0 | 285 | 196.9 | 0.005028 |
| qwen3.8-flash-next | callback | 60 | 60 | 0 | 6 | 0 | 0 | 0 | 7 | 0.5 | 12 | 101.7 | 298.1 | 0.005447 |
| qwen3.8-flash-next | naive | 60 | 60 | 0 | 4 | 0 | 4 | 14 | 15 | 0.4 | 0 | 0 | 167.9 | 0.006193 |

[Raw case results](../bench/results/latest.json) · [CISA and FBI advisory AA23-320A](https://www.cisa.gov/sites/default/files/2023-11/aa23-320a_scattered_spider_0.pdf)
