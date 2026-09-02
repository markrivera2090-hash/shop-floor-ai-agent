"""Local JSON Lines persistence for shop-floor event history."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from src.data_loader import PROJECT_ROOT


DEFAULT_EVENT_HISTORY_PATH = PROJECT_ROOT / "runtime" / "event_history.jsonl"
VERCEL_EVENT_HISTORY_PATH = Path("/tmp/shop-floor-ai-agent/event_history.jsonl")


class EventHistoryError(ValueError):
    """Raised when event history input or stored content is invalid."""


def runtime_event_history_path(
    environment: Mapping[str, str] | None = None,
) -> str | Path | None:
    """Select writable history storage for local or hosted execution."""

    config = os.environ if environment is None else environment
    configured_path = config.get("EVENT_HISTORY_PATH", "").strip()
    if configured_path:
        return configured_path
    if config.get("VERCEL"):
        return VERCEL_EVENT_HISTORY_PATH
    return None


def _history_path(path: str | Path | None) -> Path:
    return DEFAULT_EVENT_HISTORY_PATH if path is None else Path(path).expanduser().resolve()


def append_event(event: dict[str, Any], path: str | Path | None = None) -> None:
    """Append one JSON-serializable event without rewriting existing history."""

    try:
        serialized_event = json.dumps(event, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise EventHistoryError("Event must be JSON serializable.") from exc

    history_path = _history_path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write(serialized_event)
        file_handle.write("\n")


def read_event_history(
    path: str | Path | None = None, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Read stored events in chronological order, optionally returning the latest N."""

    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
    ):
        raise EventHistoryError("Event-history limit must be a positive integer.")

    history_path = _history_path(path)
    if not history_path.exists():
        return []
    if not history_path.is_file():
        raise EventHistoryError("Event-history location is not a readable file.")

    events: list[dict[str, Any]] = []
    with history_path.open("r", encoding="utf-8") as file_handle:
        for line_number, line in enumerate(file_handle, start=1):
            if not line.strip():
                raise EventHistoryError(
                    f"Malformed event-history record at line {line_number}: empty record."
                )
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventHistoryError(
                    f"Malformed event-history JSON at line {line_number}."
                ) from exc
            if not isinstance(event, dict):
                raise EventHistoryError(
                    f"Malformed event-history record at line {line_number}: expected an object."
                )
            events.append(event)

    return events[-limit:] if limit is not None else events
