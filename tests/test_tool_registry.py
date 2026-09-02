"""Tests for provider-facing tool schemas and strict dispatch."""

from __future__ import annotations

import json

import pytest

import src.tool_registry as registry
from src.event_history import read_event_history
from src.tool_registry import TOOL_SCHEMAS, ToolExecutionContext, dispatch_tool


EXPECTED_TOOLS = {
    "get_panel",
    "get_workstation_requirements",
    "search_sop",
    "record_event",
    "escalate_to_supervisor",
}


def test_all_five_tool_schemas_are_registered():
    assert {schema["name"] for schema in TOOL_SCHEMAS} == EXPECTED_TOOLS


def test_schemas_contain_required_fields_and_strict_behavior():
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        assert schema["description"]
        assert schema["strict"] is True
        parameters = schema["parameters"]
        assert parameters["type"] == "object"
        assert parameters["required"]
        assert set(parameters["required"]) == set(parameters["properties"])


def test_schemas_reject_additional_properties():
    for schema in TOOL_SCHEMAS:
        assert schema["parameters"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_source"),
    [
        ("get_panel", {"panel_code": "P-1001"}, "Panel P-1001"),
        (
            "get_workstation_requirements",
            {"workstation_id": "EDGE-01"},
            "Workstation EDGE-01",
        ),
        ("search_sop", {"query": "edge banding"}, "SOP-EDGE-001"),
    ],
)
def test_valid_dispatch_calls_execute_correct_read_tool(
    tool_name, arguments, expected_source
):
    result = dispatch_tool(tool_name, arguments)

    assert result["tool"] == tool_name
    assert result["success"] is True
    assert expected_source in result["sources"]


def test_unknown_tools_are_rejected():
    result = dispatch_tool("delete_all_records", {})

    assert result["success"] is False
    assert result["error"]["code"] == "unknown_tool"


@pytest.mark.parametrize("arguments", ["{", "not-json", "[]"])
def test_malformed_or_non_object_json_arguments_are_rejected(arguments):
    result = dispatch_tool("get_panel", arguments)

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_tool_arguments"


@pytest.mark.parametrize("arguments", [None, [], "value", 7])
def test_non_object_arguments_are_rejected(arguments):
    result = dispatch_tool("get_panel", arguments)

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_tool_arguments"


def test_missing_or_extra_arguments_are_rejected():
    assert dispatch_tool("get_panel", {})["error"]["code"] == "invalid_tool_arguments"
    result = dispatch_tool("get_panel", {"panel_code": "P-1001", "extra": True})
    assert result["error"]["code"] == "invalid_tool_arguments"


def test_dispatcher_results_are_json_serializable():
    results = [
        dispatch_tool("get_panel", '{"panel_code":"P-1001"}'),
        dispatch_tool("unknown", {}),
        dispatch_tool("get_panel", "{"),
    ]
    for result in results:
        json.dumps(result)


def test_raw_exceptions_and_private_paths_are_not_exposed(monkeypatch, tmp_path):
    private_path = tmp_path / "private" / "secret.txt"

    def explode(**_arguments):
        raise RuntimeError(f"failure at {private_path}")

    monkeypatch.setitem(registry._TOOL_FUNCTIONS, "get_panel", explode)
    result = dispatch_tool("get_panel", {"panel_code": "P-1001"})
    rendered = json.dumps(result)

    assert result["error"]["code"] == "tool_execution_failed"
    assert str(private_path) not in rendered
    assert "RuntimeError" not in rendered


def test_temporary_event_history_path_is_injected_without_model_argument(tmp_path):
    history_path = tmp_path / "events.jsonl"
    context = ToolExecutionContext(event_history_path=history_path)

    result = dispatch_tool(
        "record_event",
        {"event_type": "scan", "message": "Temporary scan"},
        context=context,
    )

    assert result["success"] is True
    assert read_event_history(history_path) == [result["data"]]
    record_schema = next(schema for schema in TOOL_SCHEMAS if schema["name"] == "record_event")
    assert "event_history_path" not in record_schema["parameters"]["properties"]
