import json

from bench.run import case_directory, classify_model_failures


def test_completed_tool_limit_is_reported_without_dropping_failure_or_incomplete_observation(tmp_path):
    key = ("a01", "qwen3.8-flash-next", "naive")
    folder = case_directory(tmp_path, *key) / "attempt/calls"
    folder.mkdir(parents=True)
    evidence = {"status": "ERROR", "twin": {"status": "OUTPUT_LIMIT"},
                "destroy_proof": {"docker_inspect": "No such container"}}
    (folder / "call.json").write_text(json.dumps(evidence))
    row = {"status": "error", "call_status": "ERROR", "legitimate_completed": False,
           "observation_complete": False, "unauthorized_effects": 2}
    latest = {key: row}
    classify_model_failures(latest, tmp_path)
    assert latest[key]["status"] == "complete"
    assert latest[key]["tool_failure"] == "OUTPUT_LIMIT"
    assert latest[key]["legitimate_completed"] is False
    assert latest[key]["observation_complete"] is False
    assert latest[key]["unauthorized_effects"] == 2


def test_infrastructure_error_without_destroy_proof_is_still_an_error(tmp_path):
    key = ("a01", "qwen3.8-flash-next", "callback")
    folder = case_directory(tmp_path, *key) / "attempt/calls"
    folder.mkdir(parents=True)
    (folder / "call.json").write_text(json.dumps({"status": "ERROR", "twin": {"status": "READY"}}))
    row = {"status": "error", "call_status": "ERROR"}
    latest = {key: row}
    classify_model_failures(latest, tmp_path)
    assert latest[key] == row


def test_invalid_model_tool_arguments_remain_a_failed_legitimate_task(tmp_path):
    key = ("l06", "glm-5.3-flash", "naive")
    folder = case_directory(tmp_path, *key) / "attempt/calls"
    folder.mkdir(parents=True)
    evidence = {"status": "ERROR", "error": "ValidationError: query is a required property",
                "twin": {"status": "READY"}}
    (folder / "call.json").write_text(json.dumps(evidence))
    latest = {key: {"status": "error", "call_status": "ERROR", "legitimate_completed": False}}
    classify_model_failures(latest, tmp_path)
    assert latest[key]["status"] == "complete"
    assert latest[key]["planner_failure"] == "INVALID_TOOL_ARGUMENTS"
    assert latest[key]["legitimate_completed"] is False
