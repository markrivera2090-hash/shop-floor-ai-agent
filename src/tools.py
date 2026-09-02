"""Deterministic tools grounded in the project's verified local sources."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.data_loader import DataValidationError, load_panels, load_sop, load_workstations
from src.event_history import EventHistoryError, append_event


SUPPORTED_EVENT_TYPES = frozenset({"scan", "question", "escalation"})
_SOP_HEADING_PATTERN = re.compile(
    r"^##\s+(SOP-[A-Z]+-\d{3})\s+[—-]\s+(.+?)\s*$", re.MULTILINE
)
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "do",
        "does",
        "for",
        "grounded",
        "i",
        "information",
        "is",
        "it",
        "me",
        "my",
        "operation",
        "panel",
        "process",
        "processed",
        "processing",
        "procedure",
        "procedures",
        "provide",
        "record",
        "records",
        "required",
        "selected",
        "should",
        "system",
        "the",
        "this",
        "to",
        "use",
        "verify",
        "verification",
        "what",
        "whether",
        "workstation",
    }
)
_SOP_ALIASES = {
    "SOP-GENERAL-001": ("unknown panel", "panel code not found", "panel verification"),
    "SOP-EDGE-001": ("edge banding", "edge bander"),
    "SOP-DRILL-001": ("drilling", "drill"),
    "SOP-MISMATCH-001": (
        "wrong workstation",
        "does not match",
        "doesn't match",
        "mismatch",
        "physical panel label",
    ),
    "SOP-UNSUPPORTED-001": (
        "spindle speed",
        "feed rate",
        "tooling parameter",
        "machine parameter",
        "machine setting",
    ),
    "SOP-ESCALATION-001": ("supervisor", "escalate", "escalation"),
}
_CONDITIONAL_SOP_SECTIONS = frozenset(
    {"SOP-MISMATCH-001", "SOP-UNSUPPORTED-001", "SOP-ESCALATION-001"}
)
_MIN_SOP_RELEVANCE = 6
_SECONDARY_SCORE_WINDOW = 4
_PANEL_CODE_PATTERN = re.compile(r"^P-?(\d{4})$", re.IGNORECASE)


def _result(
    tool: str,
    tool_input: dict[str, Any],
    *,
    success: bool,
    data: Any = None,
    sources: list[str] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "input": tool_input,
        "success": success,
        "data": data if success else None,
        "sources": sources or [],
        "error": None
        if success
        else {"code": error_code, "message": error_message},
    }


def _normalized_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_panel_code(value: Any) -> str | None:
    """Return a canonical P-1234 panel code for supported input shapes."""

    normalized = _normalized_optional_string(value)
    if normalized is None:
        return None
    match = _PANEL_CODE_PATTERN.fullmatch(normalized)
    return f"P-{match.group(1)}" if match else None


def _is_json_serializable(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def _safe_structured_input(value: Any) -> Any:
    return value if _is_json_serializable(value) else None


def _data_source_failure(tool: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return _result(
        tool,
        tool_input,
        success=False,
        error_code="data_source_error",
        error_message="The verified local grounding source could not be read safely.",
    )


def get_panel(panel_code: Any) -> dict[str, Any]:
    """Return the exact grounded panel record for a normalized panel code."""

    normalized_code = normalize_panel_code(panel_code)
    tool_input = {"panel_code": normalized_code}
    if normalized_code is None:
        return _result(
            "get_panel",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Panel code must use the format P-1234 or P1234.",
        )

    try:
        panels = load_panels()
    except (FileNotFoundError, OSError, DataValidationError):
        return _data_source_failure("get_panel", tool_input)

    panel = next(
        (record for record in panels if record["panel_code"] == normalized_code), None
    )
    if panel is None:
        return _result(
            "get_panel",
            tool_input,
            success=False,
            error_code="panel_not_found",
            error_message=f"No panel record was found for code '{normalized_code}'.",
        )
    return _result(
        "get_panel",
        tool_input,
        success=True,
        data=panel,
        sources=[f"Panel {normalized_code}"],
    )


def get_workstation_requirements(workstation_id: Any) -> dict[str, Any]:
    """Return the exact grounded workstation record for a normalized ID."""

    normalized_id = _normalized_optional_string(workstation_id)
    tool_input = {"workstation_id": normalized_id}
    if normalized_id is None:
        return _result(
            "get_workstation_requirements",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Workstation ID must be a non-empty string.",
        )

    try:
        workstations = load_workstations()
    except (FileNotFoundError, OSError, DataValidationError):
        return _data_source_failure("get_workstation_requirements", tool_input)

    workstation = next(
        (
            record
            for record in workstations
            if record["workstation_id"] == normalized_id
        ),
        None,
    )
    if workstation is None:
        return _result(
            "get_workstation_requirements",
            tool_input,
            success=False,
            error_code="workstation_not_found",
            error_message=f"No workstation record was found for ID '{normalized_id}'.",
        )
    return _result(
        "get_workstation_requirements",
        tool_input,
        success=True,
        data=workstation,
        sources=[f"Workstation {normalized_id}"],
    )


def _parse_sop_sections(sop_text: str) -> list[dict[str, str]]:
    matches = list(_SOP_HEADING_PATTERN.finditer(sop_text))
    sections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(sop_text)
        sections.append(
            {
                "source_id": match.group(1),
                "title": match.group(2).strip(),
                "content": sop_text[content_start:content_end].strip(),
            }
        )
    return sections


def _search_terms(text: str) -> set[str]:
    return {
        token
        for token in _WORD_PATTERN.findall(text.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


def search_sop(query: Any) -> dict[str, Any]:
    """Return ranked SOP sections using explainable keyword and alias matching."""

    normalized_query = _normalized_optional_string(query)
    tool_input = {"query": normalized_query}
    if normalized_query is None:
        return _result(
            "search_sop",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="SOP search query must be a non-empty string.",
        )

    try:
        sections = _parse_sop_sections(load_sop())
    except (FileNotFoundError, OSError, DataValidationError):
        return _data_source_failure("search_sop", tool_input)
    if not sections:
        return _result(
            "search_sop",
            tool_input,
            success=False,
            error_code="sop_parse_error",
            error_message="The verified SOP contains no searchable sections.",
        )

    query_lower = normalized_query.lower().replace("_", " ")
    query_terms = _search_terms(normalized_query)
    ranked_matches: list[dict[str, Any]] = []
    for section in sections:
        source_id = section["source_id"]
        aliases = _SOP_ALIASES.get(source_id, ())
        alias_hits = sum(alias in query_lower for alias in aliases)
        if source_id in _CONDITIONAL_SOP_SECTIONS and not alias_hits:
            continue

        title_overlap = len(query_terms.intersection(_search_terms(section["title"])))
        content_overlap = len(query_terms.intersection(_search_terms(section["content"])))
        alias_score = 12 * alias_hits
        score = alias_score + (4 * title_overlap) + content_overlap

        # Operation names are mutually exclusive for this assessment. A query that
        # names one must never retrieve the other merely through shared SOP wording.
        if source_id == "SOP-EDGE-001" and any(
            alias in query_lower for alias in _SOP_ALIASES["SOP-DRILL-001"]
        ):
            continue
        if source_id == "SOP-DRILL-001" and any(
            alias in query_lower for alias in _SOP_ALIASES["SOP-EDGE-001"]
        ):
            continue

        if score >= _MIN_SOP_RELEVANCE:
            ranked_matches.append({**section, "score": score})

    ranked_matches.sort(key=lambda match: (-match["score"], match["source_id"]))
    if ranked_matches:
        strongest_score = ranked_matches[0]["score"]
        ranked_matches = [
            match
            for match in ranked_matches
            if match["score"] >= strongest_score - _SECONDARY_SCORE_WINDOW
        ][:3]
    if not ranked_matches:
        return _result(
            "search_sop",
            tool_input,
            success=False,
            error_code="sop_no_match",
            error_message="The available SOP does not support this query.",
        )

    return _result(
        "search_sop",
        tool_input,
        success=True,
        data={"matches": ranked_matches},
        sources=[match["source_id"] for match in ranked_matches],
    )


def record_event(
    event_type: Any,
    message: Any,
    panel_code: Any = None,
    workstation_id: Any = None,
    metadata: Any = None,
    *,
    event_history_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and append one local event-history record."""

    normalized_event_type = _normalized_optional_string(event_type)
    normalized_message = _normalized_optional_string(message)
    normalized_panel_code = normalize_panel_code(panel_code)
    normalized_workstation_id = _normalized_optional_string(workstation_id)
    normalized_metadata = {} if metadata is None else metadata
    tool_input = {
        "event_type": normalized_event_type,
        "message": normalized_message,
        "panel_code": normalized_panel_code,
        "workstation_id": normalized_workstation_id,
        "metadata": _safe_structured_input(normalized_metadata),
    }

    if normalized_event_type is None or normalized_message is None:
        return _result(
            "record_event",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Event type and message must be non-empty strings.",
        )
    if panel_code is not None and normalized_panel_code is None:
        return _result(
            "record_event",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Panel code must use the format P-1234 or P1234 when provided.",
        )
    if workstation_id is not None and normalized_workstation_id is None:
        return _result(
            "record_event",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Workstation ID must be a non-empty string when provided.",
        )
    if normalized_event_type not in SUPPORTED_EVENT_TYPES:
        return _result(
            "record_event",
            tool_input,
            success=False,
            error_code="unsupported_event_type",
            error_message=f"Unsupported event type '{normalized_event_type}'.",
        )
    if not _is_json_serializable(normalized_metadata):
        return _result(
            "record_event",
            tool_input,
            success=False,
            error_code="metadata_not_serializable",
            error_message="Event metadata must be JSON serializable.",
        )

    event = {
        "event_id": f"evt_{uuid4().hex}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": normalized_event_type,
        "message": normalized_message,
        "panel_code": normalized_panel_code,
        "workstation_id": normalized_workstation_id,
        "metadata": normalized_metadata,
    }
    try:
        append_event(event, event_history_path)
    except (OSError, EventHistoryError):
        return _result(
            "record_event",
            tool_input,
            success=False,
            error_code="event_write_failed",
            error_message="The event could not be stored in local history.",
        )

    return _result(
        "record_event", tool_input, success=True, data=event, sources=[]
    )


def escalate_to_supervisor(
    reason: Any,
    panel_code: Any = None,
    workstation_id: Any = None,
    context: Any = None,
    *,
    event_history_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record a simulated assessment escalation without contacting anyone."""

    normalized_reason = _normalized_optional_string(reason)
    normalized_panel_code = normalize_panel_code(panel_code)
    normalized_workstation_id = _normalized_optional_string(workstation_id)
    normalized_context = {} if context is None else context
    tool_input = {
        "reason": normalized_reason,
        "panel_code": normalized_panel_code,
        "workstation_id": normalized_workstation_id,
        "context": _safe_structured_input(normalized_context),
    }

    if normalized_reason is None:
        return _result(
            "escalate_to_supervisor",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Escalation reason must be a non-empty string.",
        )
    if panel_code is not None and normalized_panel_code is None:
        return _result(
            "escalate_to_supervisor",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Panel code must use the format P-1234 or P1234 when provided.",
        )
    if workstation_id is not None and normalized_workstation_id is None:
        return _result(
            "escalate_to_supervisor",
            tool_input,
            success=False,
            error_code="invalid_input",
            error_message="Workstation ID must be a non-empty string when provided.",
        )
    if not _is_json_serializable(normalized_context):
        return _result(
            "escalate_to_supervisor",
            tool_input,
            success=False,
            error_code="context_not_serializable",
            error_message="Escalation context must be JSON serializable.",
        )

    escalation_id = f"esc_{uuid4().hex}"
    event_result = record_event(
        "escalation",
        f"Supervisor escalation recorded: {normalized_reason}",
        panel_code=normalized_panel_code,
        workstation_id=normalized_workstation_id,
        metadata={
            "escalation_id": escalation_id,
            "reason": normalized_reason,
            "context": normalized_context,
            "simulated": True,
        },
        event_history_path=event_history_path,
    )
    if not event_result["success"]:
        return _result(
            "escalate_to_supervisor",
            tool_input,
            success=False,
            error_code="escalation_record_failed",
            error_message="The supervisor escalation event could not be recorded.",
        )

    return _result(
        "escalate_to_supervisor",
        tool_input,
        success=True,
        data={
            "escalation_id": escalation_id,
            "status": "escalated",
            "message": "Supervisor escalation recorded.",
            "panel_code": normalized_panel_code,
            "workstation_id": normalized_workstation_id,
            "context": normalized_context,
            "event": event_result["data"],
        },
        sources=["SOP-ESCALATION-001"],
    )
