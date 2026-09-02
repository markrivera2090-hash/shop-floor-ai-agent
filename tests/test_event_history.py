"""Tests for local JSON Lines event history."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from src.event_history import (
    DEFAULT_EVENT_HISTORY_PATH,
    EventHistoryError,
    VERCEL_EVENT_HISTORY_PATH,
    read_event_history,
    runtime_event_history_path,
)
from src.tools import record_event


@pytest.fixture(autouse=True)
def preserve_real_event_history():
    existed_before = DEFAULT_EVENT_HISTORY_PATH.exists()
    content_before = (
        DEFAULT_EVENT_HISTORY_PATH.read_bytes() if existed_before else None
    )
    yield
    assert DEFAULT_EVENT_HISTORY_PATH.exists() is existed_before
    if existed_before:
        assert DEFAULT_EVENT_HISTORY_PATH.read_bytes() == content_before


def test_missing_event_history_file_returns_empty_list(tmp_path):
    assert read_event_history(tmp_path / "missing.jsonl") == []


def test_runtime_history_defaults_to_local_storage():
    assert runtime_event_history_path({}) is None


def test_runtime_history_uses_writable_vercel_tmp_storage():
    assert runtime_event_history_path({"VERCEL": "1"}) == VERCEL_EVENT_HISTORY_PATH


def test_explicit_runtime_history_path_overrides_vercel_default(tmp_path):
    configured = str(tmp_path / "configured.jsonl")

    assert runtime_event_history_path(
        {"VERCEL": "1", "EVENT_HISTORY_PATH": configured}
    ) == configured


def test_recording_scan_creates_one_valid_event(tmp_path):
    history_path = tmp_path / "events.jsonl"

    result = record_event(
        "scan",
        "Panel scanned",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        metadata={"source": "operator"},
        event_history_path=history_path,
    )
    events = read_event_history(history_path)

    assert result["success"] is True
    assert events == [result["data"]]
    assert events[0]["event_type"] == "scan"
    assert events[0]["panel_code"] == "P-1001"


def test_recording_question_creates_one_valid_event(tmp_path):
    history_path = tmp_path / "events.jsonl"

    result = record_event(
        "question",
        "What should I do next?",
        event_history_path=history_path,
    )

    assert result["success"] is True
    assert read_event_history(history_path)[0]["event_type"] == "question"


def test_multiple_events_preserve_append_order(tmp_path):
    history_path = tmp_path / "nested" / "events.jsonl"

    first = record_event("scan", "First", event_history_path=history_path)
    second = record_event("question", "Second", event_history_path=history_path)
    third = record_event("scan", "Third", event_history_path=history_path)

    assert [event["event_id"] for event in read_event_history(history_path)] == [
        first["data"]["event_id"],
        second["data"]["event_id"],
        third["data"]["event_id"],
    ]


def test_unique_ids_and_utc_timestamps_are_present(tmp_path):
    history_path = tmp_path / "events.jsonl"
    first = record_event("scan", "First", event_history_path=history_path)["data"]
    second = record_event("scan", "Second", event_history_path=history_path)["data"]

    assert first["event_id"].startswith("evt_")
    assert first["event_id"] != second["event_id"]
    for event in (first, second):
        assert event["timestamp_utc"].endswith("Z")
        assert datetime.fromisoformat(event["timestamp_utc"].replace("Z", "+00:00")).tzinfo


def test_positive_limit_returns_latest_events_in_chronological_order(tmp_path):
    history_path = tmp_path / "events.jsonl"
    for message in ("First", "Second", "Third"):
        record_event("scan", message, event_history_path=history_path)

    limited = read_event_history(history_path, limit=2)

    assert [event["message"] for event in limited] == ["Second", "Third"]


@pytest.mark.parametrize("invalid_limit", [0, -1, 1.5, "2", True])
def test_invalid_limits_are_rejected(tmp_path, invalid_limit):
    with pytest.raises(EventHistoryError, match="positive integer"):
        read_event_history(tmp_path / "events.jsonl", limit=invalid_limit)


@pytest.mark.parametrize("event_type", ["delete", "update", "", None, 1])
def test_unsupported_or_invalid_event_types_are_rejected(tmp_path, event_type):
    result = record_event(
        event_type,
        "Test message",
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is False
    expected_code = "unsupported_event_type" if event_type in {"delete", "update"} else "invalid_input"
    assert result["error"]["code"] == expected_code


@pytest.mark.parametrize("message", [None, "", "   ", 7])
def test_empty_or_invalid_required_messages_are_rejected(tmp_path, message):
    result = record_event(
        "scan", message, event_history_path=tmp_path / "events.jsonl"
    )

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


def test_non_json_serializable_metadata_is_rejected(tmp_path):
    history_path = tmp_path / "events.jsonl"

    result = record_event(
        "scan",
        "Bad metadata",
        metadata={"not_serializable": object()},
        event_history_path=history_path,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "metadata_not_serializable"
    assert not history_path.exists()
    json.dumps(result)


@pytest.mark.parametrize("malformed_line", ["not json\n", "[]\n", "\n"])
def test_malformed_json_lines_fail_clearly(tmp_path, malformed_line):
    history_path = tmp_path / "events.jsonl"
    history_path.write_text(malformed_line, encoding="utf-8")

    with pytest.raises(EventHistoryError, match="Malformed event-history"):
        read_event_history(history_path)


def test_event_file_is_utf8_json_lines(tmp_path):
    history_path = tmp_path / "events.jsonl"
    record_event("question", "Check café panel", event_history_path=history_path)

    raw_line = history_path.read_text(encoding="utf-8").splitlines()

    assert len(raw_line) == 1
    assert json.loads(raw_line[0])["message"] == "Check café panel"
