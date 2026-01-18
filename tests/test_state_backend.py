import json
from datetime import datetime, timedelta

from py_captions_for_channels.state import StateBackend


def test_should_process_initial_none(tmp_path):
    p = tmp_path / "state.json"
    sb = StateBackend(str(p))
    assert sb.last_ts is None
    now = datetime.now()
    assert sb.should_process(now)


def test_update_and_load(tmp_path):
    p = tmp_path / "state.json"
    sb = StateBackend(str(p))
    ts = datetime.now()
    sb.update(ts)

    # persisted file contains ISO timestamp
    with open(p, "r") as f:
        data = json.load(f)
    assert data["last_timestamp"] == ts.isoformat()

    # New backend loading the file reads the same timestamp
    sb2 = StateBackend(str(p))
    assert sb2.last_ts == datetime.fromisoformat(data["last_timestamp"])

    older = ts - timedelta(seconds=10)
    newer = ts + timedelta(seconds=10)
    assert not sb2.should_process(older)
    assert sb2.should_process(newer)


def test_corrupt_state_resets(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("not a json")
    sb = StateBackend(str(p))
    assert sb.last_ts is None
    assert sb.should_process(datetime.now())


def test_atomic_write(tmp_path):
    p = tmp_path / "state.json"
    sb = StateBackend(str(p))
    ts1 = datetime.now()
    sb.update(ts1)

    ts2 = ts1 + timedelta(seconds=5)
    sb.update(ts2)

    with open(p, "r") as f:
        data = json.load(f)
    assert data["last_timestamp"] == ts2.isoformat()
    assert sb.last_ts == ts2


def test_reprocess_queue_mark_and_check(tmp_path):
    p = tmp_path / "state.json"
    sb = StateBackend(str(p))

    path = "/tank/AllMedia/Channels/test_recording.mpg"

    # Initially should not be in queue
    assert not sb.has_reprocess_request(path)

    # Mark for reprocessing
    sb.mark_for_reprocess(path)
    assert sb.has_reprocess_request(path)

    # Load from disk and verify persistence
    sb2 = StateBackend(str(p))
    assert sb2.has_reprocess_request(path)


def test_reprocess_queue_clear(tmp_path):
    p = tmp_path / "state.json"
    sb = StateBackend(str(p))

    paths = [
        "/tank/AllMedia/Channels/recording1.mpg",
        "/tank/AllMedia/Channels/recording2.mpg",
    ]

    for path in paths:
        sb.mark_for_reprocess(path)

    # Verify both are in queue
    assert len(sb.get_reprocess_queue()) == 2

    # Clear one
    sb.clear_reprocess_request(paths[0])
    assert not sb.has_reprocess_request(paths[0])
    assert sb.has_reprocess_request(paths[1])
    assert len(sb.get_reprocess_queue()) == 1


def test_reprocess_queue_persistence(tmp_path):
    p = tmp_path / "state.json"
    sb = StateBackend(str(p))

    paths = [
        "/tank/AllMedia/Channels/a.mpg",
        "/tank/AllMedia/Channels/b.mpg",
        "/tank/AllMedia/Channels/c.mpg",
    ]

    for path in paths:
        sb.mark_for_reprocess(path)

    # Load from disk
    sb2 = StateBackend(str(p))

    # Verify all items persisted
    queue = sb2.get_reprocess_queue()
    assert len(queue) == 3
    assert set(queue) == set(paths)
