"""Unit tests for CircularBuffer (Task 5.2)"""
import os
import pytest
from circular_buffer import CircularBuffer


@pytest.fixture
def buf(tmp_path):
    db = str(tmp_path / "test.db")
    return CircularBuffer(db_path=db, max_rows=5)


def _event(i: int) -> dict:
    return {
        "eventId": f"evt-{i:04d}",
        "timestamp_utc": f"2026-01-01T00:00:{i:02d}Z",
        "sensorType": "vibration",
        "payload": {"v": i},
    }


def test_write_and_read(buf):
    buf.write(_event(1))
    buf.write(_event(2))
    rows = buf.read_oldest(10)
    assert len(rows) == 2


def test_ack_removes_event(buf):
    buf.write(_event(1))
    rows = buf.read_oldest(1)
    buf.ack(rows[0]["_buffer_event_id"])
    assert len(buf.read_oldest(10)) == 0


def test_overflow_evicts_oldest(buf):
    for i in range(6):   # max_rows=5, so 6th write triggers eviction
        buf.write(_event(i))
    remaining = buf.read_oldest(10)
    # Oldest (evt-0000) should have been evicted
    ids = [r["eventId"] for r in remaining]
    assert "evt-0000" not in ids
    assert len(remaining) == 5


def test_overflow_logged(buf):
    for i in range(6):
        buf.write(_event(i))
    assert buf.overflow_count() >= 1


def test_capacity_pct_empty(buf):
    assert buf.capacity_pct() == 0.0


def test_capacity_pct_half_full(buf):
    for i in range(2):
        buf.write(_event(i))
    pct = buf.capacity_pct()
    assert 30.0 <= pct <= 50.0


def test_duplicate_event_id_ignored(buf):
    buf.write(_event(1))
    buf.write(_event(1))  # same eventId — should be ignored
    assert len(buf.read_oldest(10)) == 1
