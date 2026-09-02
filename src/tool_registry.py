"""OpenAI tool schemas and a strict allowlisted dispatcher."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.tools import (
    escalate_to_supervisor,
    get_panel,
    get_workstation_requirements,
    record_event,
    search_sop,
)


def _string_schema(description: str, *, nullable: bool = False) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": ["string", "null"] if nullable else "string",
        "description": description,
    }
    if not nullable:
        schema["minLength"] = 1
    return schema


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_panel",
        "description": "Retrieve exact production facts for a panel code.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "panel_code": _string_schema("Exact panel identifier from the operator context."),
            },
            "required": ["panel_code"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_workstation_requirements",
        "description": "Retrieve exact requirements for a selected workstation ID.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "workstation_id": _string_schema(
                    "Exact selected workstation identifier from the operator context."
                ),
            },
            "required": ["workstation_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_sop",
        "description": (
            "Retrieve grounded SOP guidance for operations, mismatches, unavailable "
            "machine settings, or escalation policy."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": _string_schema("Concise SOP search query based on the operator need."),
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "record_event",
        "description": "Record a scan or operator question in local assessment history.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "enum": ["scan", "question", "escalation"],
                    "description": "Type of local event to record.",
                },
                "message": _string_schema("Safe concise event description."),
                "panel_code": _string_schema("Related panel code, if known.", nullable=True),
                "workstation_id": _string_schema(
                    "Related workstation ID, if known.", nullable=True
                ),
                "metadata": {
                    "type": ["object", "null"],
                    "description": "Optional non-sensitive assessment metadata.",
                    "properties": {
                        "request_type": _string_schema(
                            "Original request type, if useful.", nullable=True
                        ),
                        "note": _string_schema("Optional safe note.", nullable=True),
                    },
                    "required": ["request_type", "note"],
                    "additionalProperties": False,
                },
            },
            "required": [
                "event_type",
                "message",
                "panel_code",
                "workstation_id",
                "metadata",
            ],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "escalate_to_supervisor",
        "description": (
            "Create a simulated assessment escalation when facts are unavailable, "
            "records conflict, or the request cannot be resolved safely."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "reason": _string_schema("Clear reason the issue cannot be resolved safely."),
                "panel_code": _string_schema("Related panel code, if known.", nullable=True),
                "workstation_id": _string_schema(
                    "Related workstation ID, if known.", nullable=True
                ),
                "context": {
                    "type": ["object", "null"],
                    "description": "Optional structured mismatch context without secrets.",
                    "properties": {
                        "issue": _string_schema("Issue summary.", nullable=True),
                        "observed": _string_schema("Observed information.", nullable=True),
                        "expected": _string_schema("Expected information.", nullable=True),
                    },
                    "required": ["issue", "observed", "expected"],
                    "additionalProperties": False,
                },
            },
            "required": ["reason", "panel_code", "workstation_id", "context"],
            "additionalProperties": False,
        },
    },
]


_TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_panel": get_panel,
    "get_workstation_requirements": get_workstation_requirements,
    "search_sop": search_sop,
    "record_event": record_event,
    "escalate_to_supervisor": escalate_to_supervisor,
}
_TOOL_ALLOWED_ARGUMENTS = {
    "get_panel": frozenset({"panel_code"}),
    "get_workstation_requirements": frozenset({"workstation_id"}),
    "search_sop": frozenset({"query"}),
    "record_event": frozenset(
        {"event_type", "message", "panel_code", "workstation_id", "metadata"}
    ),
    "escalate_to_supervisor": frozenset(
        {"reason", "panel_code", "workstation_id", "context"}
    ),
}
_TOOL_REQUIRED_ARGUMENTS = {
    "get_panel": frozenset({"panel_code"}),
    "get_workstation_requirements": frozenset({"workstation_id"}),
    "search_sop": frozenset({"query"}),
    "record_event": frozenset({"event_type", "message"}),
    "escalate_to_supervisor": frozenset({"reason"}),
}


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted local dependencies that are never exposed in model-facing schemas."""

    event_history_path: Path | None = None


def _dispatch_failure(
    tool_name: Any,
    arguments: dict[str, Any] | None,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "tool": tool_name if isinstance(tool_name, str) else "unknown",
        "input": arguments or {},
        "success": False,
        "data": None,
        "sources": [],
        "error": {"code": code, "message": message},
    }


def dispatch_tool(
    tool_name: Any,
    arguments: Any,
    *,
    context: ToolExecutionContext | None = None,
) -> dict[str, Any]:
    """Decode, validate, and execute one explicitly allowlisted tool call."""

    if not isinstance(tool_name, str) or tool_name not in _TOOL_FUNCTIONS:
        return _dispatch_failure(
            tool_name,
            None,
            "unknown_tool",
            "The requested tool is not available.",
        )

    decoded_arguments = arguments
    if isinstance(arguments, str):
        try:
            decoded_arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return _dispatch_failure(
                tool_name,
                None,
                "invalid_tool_arguments",
                "Tool arguments must be valid JSON object data.",
            )
    if not isinstance(decoded_arguments, dict):
        return _dispatch_failure(
            tool_name,
            None,
            "invalid_tool_arguments",
            "Tool arguments must be a JSON object.",
        )

    allowed = _TOOL_ALLOWED_ARGUMENTS[tool_name]
    required = _TOOL_REQUIRED_ARGUMENTS[tool_name]
    if set(decoded_arguments).difference(allowed) or required.difference(decoded_arguments):
        return _dispatch_failure(
            tool_name,
            decoded_arguments,
            "invalid_tool_arguments",
            "Tool arguments do not match the registered schema.",
        )

    execution_arguments = dict(decoded_arguments)
    if tool_name in {"record_event", "escalate_to_supervisor"} and context is not None:
        execution_arguments["event_history_path"] = context.event_history_path

    try:
        result = _TOOL_FUNCTIONS[tool_name](**execution_arguments)
        json.dumps(result)
    except Exception:
        return _dispatch_failure(
            tool_name,
            decoded_arguments,
            "tool_execution_failed",
            "The tool could not be executed safely.",
        )
    return result
