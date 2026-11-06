from services.control.approvals import request_for


def test_cancelled_call_without_planner_policy_can_be_archived():
    call_id = "a12d2740-e86d-4d93-a992-1016c0a51d02"
    call = {
        "status": "CANCELLED", "realm": "acme", "twin": {"twin_id": call_id},
        "transcript": [], "model_calls": [], "egress": [],
        "change_set_hash": "0" * 64,
        "change_set": {"call_id": call_id, "realm": "acme", "seed_version": "test",
                       "prod_state_digest": "1" * 64, "effects": [], "created_at": "2026-11-06T00:00:00Z"},
    }
    request = request_for(call)
    assert request["context"]["policy"] is None
    assert request["context"]["call_status"] == "CANCELLED"
    assert not request["signatures"] and not request["change_set"]["effects"]
