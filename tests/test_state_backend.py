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
