"""Scripted-provider tests for grounded Phase 4 orchestration."""

from __future__ import annotations

import json

import pytest

from src.agent import run_agent
from src.event_history import DEFAULT_EVENT_HISTORY_PATH, read_event_history
from src.prompts import SYSTEM_INSTRUCTIONS


class ScriptedProvider:
    provider_name = "openai"
    model = "mock-model"

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        step = self.steps.pop(0)
        return step(self, kwargs) if callable(step) else step


def tool_turn(response_id, *calls):
    return {
        "success": True,
        "response_id": response_id,
        "function_calls": [
            {
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(arguments) if isinstance(arguments, dict) else arguments,
                "arguments_valid": True,
            }
            for call_id, name, arguments in calls
        ],
        "output_text": None,
        "refusal": None,
        "error": None,
    }


def final_turn(response_id, text):
    return {
        "success": True,
        "response_id": response_id,
        "function_calls": [],
        "output_text": text,
        "refusal": None,
        "error": None,
    }


@pytest.fixture(autouse=True)
def preserve_real_event_history():
    existed_before = DEFAULT_EVENT_HISTORY_PATH.exists()
    content_before = DEFAULT_EVENT_HISTORY_PATH.read_bytes() if existed_before else None
    yield
    assert DEFAULT_EVENT_HISTORY_PATH.exists() is existed_before
    if existed_before:
        assert DEFAULT_EVENT_HISTORY_PATH.read_bytes() == content_before


def correct_workstation_provider():
    return ScriptedProvider(
        [
            tool_turn("r1", ("c1", "get_panel", {"panel_code": "P-1001"})),
            tool_turn(
                "r2",
                (
                    "c2",
                    "get_workstation_requirements",
                    {"workstation_id": "EDGE-01"},
                ),
            ),
            tool_turn("r3", ("c3", "search_sop", {"query": "edge banding"})),
            tool_turn(
                "r4",
                (
                    "c4",
                    "record_event",
                    {
                        "event_type": "scan",
                        "message": "P-1001 scanned at EDGE-01",
                        "panel_code": "P-1001",
                        "workstation_id": "EDGE-01",
                        "metadata": None,
                    },
                ),
            ),
            final_turn(
                "r5",
                "P-1001 is assigned to EDGE-01 for edge banding. Follow the grounded checks.",
            ),
        ]
    )


def test_correct_workstation_uses_multiple_tool_rounds_and_grounded_sources(tmp_path):
    provider = correct_workstation_provider()

    result = run_agent(
        "Verify this panel at the selected workstation.",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        request_type="scan",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert [entry["tool"] for entry in result["trace"]] == [
        "get_panel",
        "get_workstation_requirements",
        "search_sop",
        "record_event",
    ]
    assert result["sources"] == [
        "Panel P-1001",
        "Workstation EDGE-01",
        "SOP-EDGE-001",
    ]
    assert len(provider.calls) == 5
    assert provider.calls[0]["instructions"] == SYSTEM_INSTRUCTIONS
    assert len(provider.calls[0]["tools"]) == 5
    assert provider.calls[1]["previous_response_id"] == "r1"
    assert read_event_history(tmp_path / "events.jsonl")[0]["event_type"] == "scan"


def test_live_defect_regression_correct_match_returns_grounded_success(tmp_path):
    provider = correct_workstation_provider()

    result = run_agent(
        "Verify whether panel P-1001 can be processed at workstation EDGE-01 and provide only grounded instructions.",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        request_type="scan",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert result["sources"] == [
        "Panel P-1001",
        "Workstation EDGE-01",
        "SOP-EDGE-001",
    ]
    response = result["response"].lower()
    assert "do not process" not in response
    assert "wrong workstation" not in response
    assert "drill-01" not in response


def test_incidental_mismatch_source_does_not_override_matching_structured_records(
    tmp_path, monkeypatch
):
    from src import agent as agent_module

    real_dispatch = agent_module.dispatch_tool

    def dispatch_with_incidental_source(name, arguments, *, context):
        result = real_dispatch(name, arguments, context=context)
        if name == "search_sop" and result["success"]:
            result["sources"].append("SOP-MISMATCH-001")
        return result

    monkeypatch.setattr(agent_module, "dispatch_tool", dispatch_with_incidental_source)
    provider = correct_workstation_provider()

    result = run_agent(
        "Verify P-1001 at EDGE-01.",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        request_type="scan",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert "do not process" not in result["response"].lower()


def test_operation_mismatch_is_treated_as_wrong_workstation(tmp_path, monkeypatch):
    from src import agent as agent_module

    real_dispatch = agent_module.dispatch_tool

    def dispatch_with_wrong_operation(name, arguments, *, context):
        result = real_dispatch(name, arguments, context=context)
        if name == "get_workstation_requirements" and result["success"]:
            result["data"] = {**result["data"], "supported_operation": "drilling"}
        return result

    monkeypatch.setattr(agent_module, "dispatch_tool", dispatch_with_wrong_operation)
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                ("c1", "get_panel", {"panel_code": "P-1001"}),
                (
                    "c2",
                    "get_workstation_requirements",
                    {"workstation_id": "EDGE-01"},
                ),
            ),
            final_turn("r2", "Proceed with processing at EDGE-01."),
        ]
    )

    result = run_agent(
        "Can P-1001 be processed at EDGE-01?",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is False
    assert "do not process" in result["response"].lower()


def test_wrong_workstation_says_not_to_process_and_gives_safe_next_step(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                ("c1", "get_panel", {"panel_code": "P-1003"}),
                (
                    "c2",
                    "get_workstation_requirements",
                    {"workstation_id": "EDGE-01"},
                ),
            ),
            tool_turn(
                "r2",
                ("c3", "search_sop", {"query": "wrong workstation mismatch"}),
            ),
            final_turn(
                "r3",
                "Do not process P-1003 at EDGE-01. Verify the record and route it to DRILL-01 or escalate if the mismatch remains.",
            ),
        ]
    )

    result = run_agent(
        "Can I process P-1003 here?",
        panel_code="P-1003",
        workstation_id="EDGE-01",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert "do not process" in result["response"].lower()
    assert "Panel P-1003" in result["sources"]
    assert "Workstation EDGE-01" in result["sources"]
    assert "SOP-MISMATCH-001" in result["sources"]
    assert len(provider.calls[0]["input_data"]) > 0


def test_unsupported_spindle_question_returns_no_numeric_setting(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                ("c1", "search_sop", {"query": "spindle speed"}),
            ),
            final_turn(
                "r2",
                "The spindle speed is unavailable in the approved sources. Consult approved documentation or a supervisor; do not guess.",
            ),
        ]
    )

    result = run_agent(
        "What spindle speed should I use?",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert "SOP-UNSUPPORTED-001" in result["sources"]
    assert not any(character.isdigit() for character in result["response"])


def test_unknown_panel_returns_panel_not_found_without_invented_facts(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "get_panel", {"panel_code": "P-9999"})),
            final_turn(
                "r2",
                "Panel Not Found. Verify the panel code and escalate if it remains unresolved.",
            ),
        ]
    )

    result = run_agent(
        "Check P-9999.",
        panel_code="P-9999",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert "panel not found" in result["response"].lower()
    assert result["sources"] == []
    assert result["trace"][0]["error"]["code"] == "panel_not_found"
    assert "material" not in result["response"].lower()
    assert "dimensions" not in result["response"].lower()


def test_supervisor_escalation_is_simulated_and_recorded(tmp_path):
    history_path = tmp_path / "events.jsonl"
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                (
                    "c1",
                    "search_sop",
                    {"query": "physical panel label mismatch escalation"},
                ),
                (
                    "c2",
                    "escalate_to_supervisor",
                    {
                        "reason": "Physical label conflicts with the system record",
                        "panel_code": "P-1001",
                        "workstation_id": "EDGE-01",
                        "context": None,
                    },
                ),
            ),
            final_turn(
                "r2",
                "Do not process the panel. A simulated escalation was recorded for this assessment; no real supervisor was contacted.",
            ),
        ]
    )

    result = run_agent(
        "The physical panel label does not match the system information.",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        provider=provider,
        event_history_path=history_path,
    )

    assert result["success"] is True
    assert result["escalated"] is True
    assert "simulated" in result["response"].lower()
    assert [entry["tool"] for entry in result["trace"]] == [
        "search_sop",
        "escalate_to_supervisor",
    ]
    assert "SOP-ESCALATION-001" in result["sources"]
    assert read_event_history(history_path)[0]["event_type"] == "escalation"


def test_different_requests_can_use_different_model_chosen_sequences(tmp_path):
    panel_provider = ScriptedProvider(
        [
            tool_turn("p1", ("pc1", "get_panel", {"panel_code": "P-1001"})),
            final_turn("p2", "Panel P-1001 was found in the production records."),
        ]
    )
    sop_provider = ScriptedProvider(
        [
            tool_turn("s1", ("sc1", "search_sop", {"query": "drilling"})),
            final_turn("s2", "Use the grounded drilling SOP instructions."),
        ]
    )

    panel_result = run_agent(
        "Find panel P-1001.", provider=panel_provider, event_history_path=tmp_path / "p.jsonl"
    )
    sop_result = run_agent(
        "What are the drilling instructions?",
        provider=sop_provider,
        event_history_path=tmp_path / "s.jsonl",
    )

    assert [entry["tool"] for entry in panel_result["trace"]] == ["get_panel"]
    assert [entry["tool"] for entry in sop_result["trace"]] == ["search_sop"]


def test_multiple_tool_calls_in_one_provider_turn_are_handled(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                ("c1", "get_panel", {"panel_code": "P-1001"}),
                (
                    "c2",
                    "get_workstation_requirements",
                    {"workstation_id": "EDGE-01"},
                ),
            ),
            final_turn("r2", "P-1001 and EDGE-01 match for edge banding."),
        ]
    )

    result = run_agent(
        "Verify panel and workstation.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert len(result["trace"]) == 2
    assert len(provider.calls[1]["input_data"]) == 2


def test_malformed_tool_arguments_are_returned_to_model_for_recovery(tmp_path):
    def verify_failure_then_recover(_provider, kwargs):
        output = json.loads(kwargs["input_data"][0]["output"])
        assert output["error"]["code"] == "invalid_tool_arguments"
        return tool_turn("r2", ("c2", "search_sop", {"query": "edge banding"}))

    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "get_panel", "{")),
            verify_failure_then_recover,
            final_turn("r3", "Use the grounded edge-banding SOP instructions."),
        ]
    )

    result = run_agent(
        "Give edge banding instructions.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert result["trace"][0]["error"]["code"] == "invalid_tool_arguments"
    assert "SOP-EDGE-001" in result["sources"]


def test_unknown_model_requested_tool_is_blocked_and_recoverable(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "run_shell", {})),
            tool_turn("r2", ("c2", "search_sop", {"query": "drilling"})),
            final_turn("r3", "Use only the grounded drilling SOP instructions."),
        ]
    )

    result = run_agent(
        "Give drilling instructions.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert result["trace"][0]["error"]["code"] == "unknown_tool"
    assert "SOP-DRILL-001" in result["sources"]


def test_tool_failure_can_be_returned_for_another_model_decision(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "get_panel", {"panel_code": "P-9999"})),
            tool_turn("r2", ("c2", "search_sop", {"query": "unknown panel"})),
            final_turn("r3", "Panel Not Found. Verify the code and escalate if unresolved."),
        ]
    )

    result = run_agent(
        "Check unknown panel P-9999.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert result["trace"][0]["success"] is False
    assert result["trace"][1]["success"] is True


def test_duplicate_tool_loop_is_bounded(tmp_path):
    repeated = tool_turn("r", ("c", "get_panel", {"panel_code": "P-1001"}))
    provider = ScriptedProvider([repeated, repeated, repeated])

    result = run_agent(
        "Check panel P-1001.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
        max_model_turns=3,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "agent_limit_reached"
    assert result["trace"][1]["error"]["code"] == "duplicate_tool_call"


def test_maximum_total_tool_calls_fail_safely_before_execution(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                ("c1", "get_panel", {"panel_code": "P-1001"}),
                ("c2", "search_sop", {"query": "edge banding"}),
            )
        ]
    )

    result = run_agent(
        "Check panel and SOP.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
        max_total_tool_calls=1,
    )

    assert result["error"]["code"] == "agent_limit_reached"
    assert result["trace"] == []


def test_provider_failure_preserves_completed_safe_trace(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "get_panel", {"panel_code": "P-1001"})),
            {
                "success": False,
                "error": {"code": "provider_error", "message": "safe"},
            },
        ]
    )

    result = run_agent(
        "Check panel P-1001.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["error"]["code"] == "provider_error"
    assert len(result["trace"]) == 1
    assert result["sources"] == ["Panel P-1001"]


def test_no_tool_ungrounded_production_guidance_is_blocked(tmp_path):
    provider = ScriptedProvider([final_turn("r1", "Set the machine speed to maximum.")])

    result = run_agent(
        "How should I process this panel?",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is False
    assert result["error"]["code"] == "unsafe_or_ungrounded_response"
    assert "maximum" not in result["response"].lower()


def test_unsafe_numeric_spindle_output_is_blocked(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "search_sop", {"query": "spindle speed"})),
            final_turn("r2", "Use 5000 RPM for the spindle speed."),
        ]
    )

    result = run_agent(
        "What spindle speed should I use?",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is False
    assert result["error"]["code"] == "unsafe_or_ungrounded_response"
    assert "5000" not in result["response"]


def test_wrong_workstation_output_telling_operator_to_proceed_is_blocked(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn(
                "r1",
                ("c1", "get_panel", {"panel_code": "P-1003"}),
                (
                    "c2",
                    "get_workstation_requirements",
                    {"workstation_id": "EDGE-01"},
                ),
            ),
            final_turn("r2", "Proceed with processing at EDGE-01."),
        ]
    )

    result = run_agent(
        "Can P-1003 be processed at EDGE-01?",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is False
    assert "do not process" in result["response"].lower()
    assert "proceed" not in result["response"].lower()


def test_model_invented_citations_are_not_added_to_sources(tmp_path):
    provider = ScriptedProvider(
        [
            tool_turn("r1", ("c1", "get_panel", {"panel_code": "P-1001"})),
            final_turn("r2", "Panel P-1001 was found. Citation: SOP-FAKE-999."),
        ]
    )

    result = run_agent(
        "Find P-1001.",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )

    assert result["success"] is True
    assert result["sources"] == ["Panel P-1001"]
    assert "SOP-FAKE-999" not in result["sources"]


def test_agent_results_and_traces_are_json_serializable_without_private_reasoning(tmp_path):
    provider = correct_workstation_provider()

    result = run_agent(
        "Verify this panel.",
        panel_code="P-1001",
        workstation_id="EDGE-01",
        request_type="scan",
        provider=provider,
        event_history_path=tmp_path / "events.jsonl",
    )
    rendered = json.dumps(result)

    assert "chain-of-thought" not in rendered.lower()
    assert "system instructions" not in rendered.lower()
    assert SYSTEM_INSTRUCTIONS not in rendered


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request": ""},
        {"request": None},
        {"request": "x" * 2001},
        {"request": "ok", "request_type": "delete"},
        {"request": "ok", "panel_code": ""},
        {"request": "ok", "workstation_id": 7},
    ],
)
def test_invalid_agent_inputs_are_rejected(kwargs):
    result = run_agent(provider=ScriptedProvider([]), **kwargs)

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


def test_missing_configuration_returns_honest_error_without_api_call(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    result = run_agent("Check this panel.")

    assert result["success"] is False
    assert result["error"]["code"] == "configuration_error"
