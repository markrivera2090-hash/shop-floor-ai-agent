"""Contract and behavior tests for deterministic Phase 3 tools."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.data_loader import REQUIRED_SOP_SOURCE_IDS, load_panels, load_sop, load_workstations
from src.event_history import read_event_history
from src.tools import (
    escalate_to_supervisor,
    get_panel,
    get_workstation_requirements,
    record_event,
    search_sop,
)


def test_known_panel_returns_exact_structured_record():
    expected = next(panel for panel in load_panels() if panel["panel_code"] == "P-1001")

    result = get_panel("P-1001")

    assert result["success"] is True
    assert result["data"] == expected


def test_known_panel_includes_correct_source():
    assert get_panel("P-1001")["sources"] == ["Panel P-1001"]


def test_panel_code_surrounding_whitespace_is_normalized():
    result = get_panel("  P-1001\n")

    assert result["success"] is True
    assert result["input"] == {"panel_code": "P-1001"}


def test_unknown_panel_returns_panel_not_found_without_fabricated_data():
    result = get_panel("P-9999")

    assert result["success"] is False
    assert result["error"]["code"] == "panel_not_found"
    assert result["data"] is None
    assert result["sources"] == []


@pytest.mark.parametrize("invalid_input", [None, "", "   ", 1001, ["P-1001"]])
def test_empty_or_invalid_panel_input_is_rejected_safely(invalid_input):
    result = get_panel(invalid_input)

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"
    json.dumps(result)


def test_panel_matching_is_exact_not_case_normalized():
    assert get_panel("p-1001")["error"]["code"] == "panel_not_found"


def test_known_workstation_returns_exact_record():
    expected = next(
        workstation
        for workstation in load_workstations()
        if workstation["workstation_id"] == "EDGE-01"
    )

    result = get_workstation_requirements("EDGE-01")

    assert result["success"] is True
    assert result["data"] == expected


def test_known_workstation_includes_correct_source():
    result = get_workstation_requirements(" EDGE-01 ")

    assert result["sources"] == ["Workstation EDGE-01"]
    assert result["input"] == {"workstation_id": "EDGE-01"}


def test_unknown_workstation_returns_stable_failure():
    result = get_workstation_requirements("UNKNOWN-01")

    assert result["success"] is False
    assert result["error"]["code"] == "workstation_not_found"
    assert result["data"] is None


@pytest.mark.parametrize("invalid_input", [None, "", "  ", 1, {"id": "EDGE-01"}])
def test_empty_or_invalid_workstation_input_is_rejected_safely(invalid_input):
    result = get_workstation_requirements(invalid_input)

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"
    json.dumps(result)


@pytest.mark.parametrize(
    ("query", "required_source"),
    [
        ("What should I do for edge banding?", "SOP-EDGE-001"),
        ("What should I do for drilling?", "SOP-DRILL-001"),
        ("This panel is at the wrong workstation.", "SOP-MISMATCH-001"),
        ("What spindle speed should I use?", "SOP-UNSUPPORTED-001"),
        ("I need a supervisor.", "SOP-ESCALATION-001"),
    ],
)
def test_sop_queries_retrieve_required_grounding(query, required_source):
    result = search_sop(query)

    assert result["success"] is True
    assert required_source in result["sources"]


def test_physical_label_mismatch_retrieves_mismatch_or_escalation_guidance():
    result = search_sop(
        "The physical panel label does not match the system information."
    )

    assert result["success"] is True
    assert {"SOP-MISMATCH-001", "SOP-ESCALATION-001"}.intersection(result["sources"])


def test_edge_banding_query_prioritizes_edge_and_excludes_drilling():
    result = search_sop("edge banding")

    assert result["sources"][0] == "SOP-EDGE-001"
    assert "SOP-DRILL-001" not in result["sources"]


def test_drilling_query_prioritizes_drilling_and_excludes_edge_banding():
    result = search_sop("drilling")

    assert result["sources"][0] == "SOP-DRILL-001"
    assert "SOP-EDGE-001" not in result["sources"]


def test_broad_correct_workstation_query_does_not_return_weak_unrelated_sections():
    result = search_sop(
        "Verify panel P-1001 at workstation EDGE-01 for the edge banding operation"
    )

    assert result["sources"] == ["SOP-EDGE-001"]


def test_mismatch_and_unsupported_queries_retrieve_their_specific_sections():
    assert search_sop("wrong workstation mismatch")["sources"][0] == "SOP-MISMATCH-001"
    assert search_sop("spindle speed")["sources"][0] == "SOP-UNSUPPORTED-001"


def test_unsupported_unrelated_query_returns_honest_no_match():
    result = search_sop("What is tomorrow's lunar weather forecast?")

    assert result["success"] is False
    assert result["error"]["code"] == "sop_no_match"
    assert result["data"] is None
    assert result["sources"] == []


@pytest.mark.parametrize("invalid_query", [None, "", "   ", 42])
def test_empty_or_invalid_sop_query_is_rejected(invalid_query):
    result = search_sop(invalid_query)

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


def test_returned_sop_content_comes_from_real_sections():
    sop_text = load_sop()
    result = search_sop("edge banding")

    for match in result["data"]["matches"]:
        assert match["content"] in sop_text
        assert match["title"] in sop_text


def test_search_results_never_include_fabricated_source_ids():
    queries = ["edge banding", "drilling", "wrong workstation", "spindle speed"]

    for query in queries:
        result = search_sop(query)
        assert set(result["sources"]) <= REQUIRED_SOP_SOURCE_IDS
        assert len(result["data"]["matches"]) <= 3


def test_escalation_returns_unique_ids(tmp_path):
    history_path = tmp_path / "events.jsonl"

    first = escalate_to_supervisor("First reason", event_history_path=history_path)
    second = escalate_to_supervisor("Second reason", event_history_path=history_path)

    assert first["data"]["escalation_id"] != second["data"]["escalation_id"]


def test_escalation_is_simulated_and_cites_source(tmp_path):
    result = escalate_to_supervisor(
        "Panel label mismatch",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        context={"observed": "label differs"},
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert result["data"]["status"] == "escalated"
    assert "simulated" in result["data"]["message"].lower()
    assert "no real supervisor was contacted" in result["data"]["message"].lower()
    assert result["sources"] == ["SOP-ESCALATION-001"]


def test_escalation_records_an_event(tmp_path):
    history_path = tmp_path / "events.jsonl"

    result = escalate_to_supervisor("Unknown panel", event_history_path=history_path)
    events = read_event_history(history_path)

    assert result["success"] is True
    assert len(events) == 1
    assert events[0]["event_type"] == "escalation"
    assert events[0]["metadata"]["escalation_id"] == result["data"]["escalation_id"]
    assert events[0]["metadata"]["simulated"] is True


@pytest.mark.parametrize("reason", [None, "", "   ", 123])
def test_empty_or_invalid_escalation_reason_is_rejected(reason, tmp_path):
    result = escalate_to_supervisor(reason, event_history_path=tmp_path / "events.jsonl")

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


def test_escalation_persistence_failure_does_not_claim_success(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("blocking file", encoding="utf-8")

    result = escalate_to_supervisor(
        "Cannot persist",
        event_history_path=parent_file / "events.jsonl",
    )

    assert result["success"] is False
    assert result["data"] is None
    assert result["error"]["code"] == "escalation_record_failed"
    assert "no supervisor was contacted" in result["error"]["message"].lower()


def test_non_serializable_escalation_context_is_rejected(tmp_path):
    result = escalate_to_supervisor(
        "Context test",
        context={"bad": object()},
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is False
    assert result["error"]["code"] == "context_not_serializable"
    json.dumps(result)


def _sample_results(tmp_path):
    return [
        get_panel("P-1001"),
        get_panel("P-9999"),
        get_workstation_requirements("EDGE-01"),
        get_workstation_requirements("UNKNOWN-01"),
        search_sop("edge banding"),
        search_sop("lunar weather"),
        record_event("scan", "Panel scanned", event_history_path=tmp_path / "events.jsonl"),
        escalate_to_supervisor(
            "Review needed", event_history_path=tmp_path / "events.jsonl"
        ),
    ]


def test_every_tool_result_uses_common_envelope(tmp_path):
    expected_fields = {"tool", "input", "success", "data", "sources", "error"}

    for result in _sample_results(tmp_path):
        assert set(result) == expected_fields
        assert isinstance(result["tool"], str)
        assert isinstance(result["input"], dict)
        assert isinstance(result["success"], bool)
        assert isinstance(result["sources"], list)
        assert (result["error"] is None) is result["success"]


def test_every_tool_result_is_json_serializable(tmp_path):
    for result in _sample_results(tmp_path):
        json.dumps(result)


def test_failures_are_safe_and_do_not_expose_paths_or_tracebacks(tmp_path):
    parent_file = tmp_path / "private-location"
    parent_file.write_text("blocking file", encoding="utf-8")
    failures = [
        get_panel("P-9999"),
        get_workstation_requirements("UNKNOWN-01"),
        search_sop("lunar weather"),
        record_event(
            "scan", "Cannot persist", event_history_path=parent_file / "events.jsonl"
        ),
    ]

    for result in failures:
        rendered = json.dumps(result)
        assert result["success"] is False
        assert "Traceback" not in rendered
        assert str(tmp_path) not in rendered


def test_tools_do_not_import_streamlit_openai_or_llm_modules():
    tools_path = Path(__file__).resolve().parents[1] / "src" / "tools.py"
    tree = ast.parse(tools_path.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint({"streamlit", "openai", "llm"})
