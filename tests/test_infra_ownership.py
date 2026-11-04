import pytest

from infra.provision import ProvisionError, Vultr, deletion_plan, verify_live_ownership


def fixture():
    item = {"id": "new-vm", "created_by_task": True, "owner_id": "task-owner",
            "api_path": "instances/new-vm"}
    return {"owner_id": "task-owner", "resources": {"sandbox": item},
            "audit": [{"event": "resource_created", "id": "new-vm"}]}, item


def test_teardown_requires_recorded_ownership():
    state, item = fixture()
    item["created_by_task"] = False
    with pytest.raises(ProvisionError):
        deletion_plan(state)


@pytest.mark.parametrize("mutation", ["live_tag", "live_id", "creation_event", "path"])
def test_resource_with_missing_ownership_evidence_is_preserved(mutation):
    state, item = fixture()
    live = {"id": "new-vm", "tags": ["task-owner"]}
    if mutation == "live_tag":
        live["tags"] = []
    elif mutation == "live_id":
        live["id"] = "pre-existing-vm"
    elif mutation == "creation_event":
        state["audit"] = []
    else:
        item["api_path"] = "instances/pre-existing-vm"
    with pytest.raises(ProvisionError):
        verify_live_ownership(state, "sandbox", item, live)


def test_task_created_vm_requires_matching_live_tag_id_and_path():
    state, item = fixture()
    verify_live_ownership(state, "sandbox", item, {"id": "new-vm", "tags": ["task-owner"]})


def test_registry_pagination_stops_at_total_despite_spurious_next_cursor():
    api = Vultr.__new__(Vultr)
    calls = []

    def call(method, path, **kwargs):
        calls.append(path)
        return {"regions": [{"id": 3, "name": "sjc"}],
                "meta": {"total": 1, "links": {"next": "spurious-cursor"}}}

    api.call = call
    assert api.listing("registry/region/list", "regions") == [{"id": 3, "name": "sjc"}]
    assert len(calls) == 1
