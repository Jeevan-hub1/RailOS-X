"""
Unit tests for ReconnectUploader — Design §5.2 | Req 2 C3
"""

import asyncio
import json
import tempfile
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# We import CircularBuffer inline to keep tests self-contained
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "buffer"))

from circular_buffer import CircularBuffer
from reconnect_uploader import ReconnectUploader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(n: int, offset_seconds: int = 0) -> dict:
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return {
        "event_id": f"evt-{n:06d}",
        "timestamp_utc": ts.isoformat(),
        "sensor_type": "vibration",
        "value": float(n),
    }


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def buf(tmp_path):
    db_file = str(tmp_path / "test.db")
    b = CircularBuffer(db_path=db_file, max_rows=100)
    yield b
    b.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUploadsEventsInOrder:
    """Uploader reads events oldest-first and ACKs on success."""

    def test_successful_upload_acks_all_events(self, buf):
        for i in range(3):
            buf.write(_make_event(i + 1, offset_seconds=i))

        uploaded_ids = []

        async def mock_post(url, json, timeout):
            uploaded_ids.append(json["event_id"])
            resp = AsyncMock()
            resp.status = 200
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=1,
                retry_delay=0.0,
            )
            with patch("aiohttp.ClientSession.post", side_effect=mock_post):
                await uploader.start()
                # Wait for the upload loop to drain
                await asyncio.sleep(0.2)

        run(_run())

        # All events should be ACKed — buffer should be empty
        assert buf.read_oldest(10) == []
        assert uploaded_ids == ["evt-000001", "evt-000002", "evt-000003"]


class TestRetryOnFailure:
    """Events that fail are retried up to retry_count times."""

    def test_retries_on_http_error_then_succeeds(self, buf):
        buf.write(_make_event(1))

        attempt_count = [0]

        async def mock_post(url, json, timeout):
            attempt_count[0] += 1
            resp = AsyncMock()
            # Fail first attempt, succeed second
            resp.status = 500 if attempt_count[0] == 1 else 200
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=3,
                retry_delay=0.0,
            )
            with patch("aiohttp.ClientSession.post", side_effect=mock_post):
                await uploader.start()
                await asyncio.sleep(0.3)

        run(_run())
        assert attempt_count[0] == 2
        assert buf.read_oldest(10) == []  # eventually ACKed

    def test_moves_to_next_event_after_all_retries_fail(self, buf):
        buf.write(_make_event(1))
        buf.write(_make_event(2, offset_seconds=1))

        async def mock_post(url, json, timeout):
            resp = AsyncMock()
            # Always fail for event 1, succeed for event 2
            resp.status = 500 if json["event_id"] == "evt-000001" else 200
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=3,
                retry_delay=0.0,
            )
            with patch("aiohttp.ClientSession.post", side_effect=mock_post):
                await uploader.start()
                await asyncio.sleep(0.3)

        run(_run())
        # Event 1 failed but event 2 should be ACKed
        remaining = buf.read_oldest(10)
        ids = [r["event_id"] for r in remaining]
        # evt-000001 still un-ACKed (failed), evt-000002 gone (ACKed)
        assert "evt-000001" in ids
        assert "evt-000002" not in ids


class TestUploadCompleteEvent:
    """Emits reconnect_upload_complete when buffer is drained."""

    def test_emits_upload_complete_when_drained(self, buf):
        buf.write(_make_event(1))

        complete_events = []

        async def event_bus(event_type, data):
            complete_events.append(event_type)

        async def mock_post(url, json, timeout):
            resp = AsyncMock()
            resp.status = 200
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                event_bus=event_bus,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=1,
                retry_delay=0.0,
            )
            with patch("aiohttp.ClientSession.post", side_effect=mock_post):
                await uploader.start()
                await asyncio.sleep(0.3)

        run(_run())
        assert "reconnect_upload_complete" in complete_events

    def test_emits_complete_on_already_empty_buffer(self, buf):
        complete_events = []

        async def event_bus(event_type, data):
            complete_events.append(event_type)

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                event_bus=event_bus,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=1,
                retry_delay=0.0,
            )
            # No POST mock needed — empty buffer exits immediately
            await uploader.start()
            await asyncio.sleep(0.1)

        run(_run())
        assert "reconnect_upload_complete" in complete_events


class TestPrometheusCounters:
    """Prometheus counters are incremented correctly."""

    def test_success_counter_incremented(self, buf):
        import reconnect_uploader as ru
        initial = ru.edge_upload_events_total._value.get()

        buf.write(_make_event(1))

        async def mock_post(url, json, timeout):
            resp = AsyncMock()
            resp.status = 200
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=1,
                retry_delay=0.0,
            )
            with patch("aiohttp.ClientSession.post", side_effect=mock_post):
                await uploader.start()
                await asyncio.sleep(0.2)

        run(_run())
        assert ru.edge_upload_events_total._value.get() == initial + 1.0

    def test_failure_counter_incremented_after_all_retries(self, buf):
        import reconnect_uploader as ru
        initial = ru.edge_upload_failures_total._value.get()

        buf.write(_make_event(1))

        async def mock_post(url, json, timeout):
            resp = AsyncMock()
            resp.status = 503
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async def _run():
            uploader = ReconnectUploader(
                buffer=buf,
                pipeline_url="http://fake-pipeline",
                batch_size=10,
                retry_count=2,
                retry_delay=0.0,
            )
            with patch("aiohttp.ClientSession.post", side_effect=mock_post):
                await uploader.start()
                await asyncio.sleep(0.3)

        run(_run())
        assert ru.edge_upload_failures_total._value.get() == initial + 1.0
