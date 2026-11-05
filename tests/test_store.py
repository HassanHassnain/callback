from services.control.store import Store


def test_call_updates_survive_reopen_without_overwriting_other_calls(tmp_path):
    path = tmp_path / "callback.sqlite3"
    store = Store(path)
    store.save({"call_id": "one", "created_at": "2026-11-05T00:00:00Z", "status": "ACTIVE"})
    store.save({"call_id": "two", "created_at": "2026-11-05T00:01:00Z", "status": "ACTIVE"})
    store.save({"call_id": "one", "created_at": "2026-11-05T00:00:00Z", "status": "ENDED"})
    assert [(c["call_id"], c["status"]) for c in Store(path).load()] == [("one", "ENDED"), ("two", "ACTIVE")]
    assert path.stat().st_mode & 0o777 == 0o600
