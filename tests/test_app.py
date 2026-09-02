"""Streamlit UI tests with explicit in-memory dependencies and no OpenAI calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.event_history import DEFAULT_EVENT_HISTORY_PATH, EventHistoryError
from src.tools import get_panel
from src.ui import _safe_result, _safe_value


def _trace(tool, sequence, *, success=True, sources=None, tool_input=None, error=None):
    return {
        "sequence": sequence,
        "tool": tool,
        "input": tool_input or {},
        "success": success,
        "sources": sources or [],
        "error": error,
    }


def _correct_result():
    return {
        "success": True,
        "response": (
            "P-1001 matches EDGE-01 for edge banding. Follow the approved grounded "
            "checks; no machine settings are provided."
        ),
        "sources": ["Panel P-1001", "Workstation EDGE-01", "SOP-EDGE-001"],
        "trace": [
            _trace("get_panel", 1, sources=["Panel P-1001"], tool_input={"panel_code": "P-1001"}),
            _trace(
                "get_workstation_requirements",
                2,
                sources=["Workstation EDGE-01"],
                tool_input={"workstation_id": "EDGE-01"},
            ),
            _trace("search_sop", 3, sources=["SOP-EDGE-001"], tool_input={"query": "edge banding"}),
            _trace("record_event", 4, tool_input={"event_type": "scan"}),
        ],
        "escalated": False,
        "model": "mock-model",
        "error": None,
    }


def _wrong_result():
    return {
        "success": True,
        "response": "Do not process P-1003 at EDGE-01. Route it to DRILL-01.",
        "sources": [
            "Panel P-1003",
            "Workstation EDGE-01",
            "SOP-MISMATCH-001",
        ],
        "trace": [
            _trace("get_panel", 1, sources=["Panel P-1003"], tool_input={"panel_code": "P-1003"}),
            _trace(
                "get_workstation_requirements",
                2,
                sources=["Workstation EDGE-01"],
                tool_input={"workstation_id": "EDGE-01"},
            ),
            _trace("search_sop", 3, sources=["SOP-MISMATCH-001"], tool_input={"query": "wrong workstation"}),
        ],
        "escalated": False,
        "model": "mock-model",
        "error": None,
    }


def _unknown_result():
    return {
        "success": True,
        "response": "Panel Not Found. Verify the code and escalate if unresolved.",
        "sources": [],
        "trace": [
            _trace(
                "get_panel",
                1,
                success=False,
                tool_input={"panel_code": "P-9999"},
                error={"code": "panel_not_found", "message": "safe"},
            )
        ],
        "escalated": False,
        "model": "mock-model",
        "error": None,
    }


def _unsupported_result():
    return {
        "success": True,
        "response": (
            "The spindle speed is unavailable in approved sources. Do not guess. "
            "Supervisor escalation recorded."
        ),
        "sources": ["SOP-UNSUPPORTED-001", "SOP-ESCALATION-001"],
        "trace": [
            _trace("search_sop", 1, sources=["SOP-UNSUPPORTED-001"], tool_input={"query": "spindle speed"}),
            _trace("escalate_to_supervisor", 2, sources=["SOP-ESCALATION-001"]),
        ],
        "escalated": True,
        "model": "mock-model",
        "error": None,
    }


def _escalation_result():
    return {
        "success": True,
        "response": "Do not process. Supervisor escalation recorded.",
        "sources": ["SOP-MISMATCH-001", "SOP-ESCALATION-001"],
        "trace": [
            _trace("search_sop", 1, sources=["SOP-MISMATCH-001"]),
            _trace("escalate_to_supervisor", 2, sources=["SOP-ESCALATION-001"]),
        ],
        "escalated": True,
        "model": "mock-model",
        "error": None,
    }


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.events = []
        self.raise_provider_error = False

    def run(self, request, **kwargs):
        self.calls.append({"request": request, **kwargs})
        if self.raise_provider_error:
            raise RuntimeError("private provider detail /private/path sk-private-secret-value")
        if "physical panel label" in request.lower():
            self.events.append(
                {
                    "timestamp_utc": "2026-09-02T00:00:00Z",
                    "event_type": "escalation",
                    "panel_code": kwargs.get("panel_code"),
                    "workstation_id": kwargs.get("workstation_id"),
                    "message": "Simulated escalation recorded",
                    "metadata": {"simulated": True},
                }
            )
            return _escalation_result()
        if "spindle speed" in request.lower():
            self.events.append(
                {
                    "timestamp_utc": "2026-09-02T00:00:00Z",
                    "event_type": "escalation",
                    "panel_code": kwargs.get("panel_code"),
                    "workstation_id": kwargs.get("workstation_id"),
                    "message": "Supervisor escalation recorded",
                    "metadata": {"simulated": True},
                }
            )
            return _unsupported_result()
        if kwargs.get("panel_code") == "P-9999":
            return _unknown_result()
        if kwargs.get("panel_code") == "P-1003" and kwargs.get("workstation_id") == "EDGE-01":
            return _wrong_result()
        return _correct_result()

    def history(self, _path=None, *, limit=None):
        return self.events[-limit:] if limit else list(self.events)


def _app_entry(agent_runner, panel_lookup, history_reader, environment, event_history_path):
    from src.ui import render_app

    render_app(
        agent_runner=agent_runner,
        panel_lookup=panel_lookup,
        history_reader=history_reader,
        environment=environment,
        event_history_path=event_history_path,
    )


def _make_app(tmp_path, backend=None, *, environment=None, history_reader=None):
    backend = backend or FakeBackend()
    app = AppTest.from_function(
        _app_entry,
        kwargs={
            "agent_runner": backend.run,
            "panel_lookup": get_panel,
            "history_reader": history_reader or backend.history,
            "environment": environment
            if environment is not None
            else {"OPENAI_API_KEY": "configured-test-key", "OPENAI_MODEL": "mock-model"},
            "event_history_path": tmp_path / "events.jsonl",
        },
        default_timeout=10,
    )
    return app.run(), backend


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _visible_text(app):
    groups = (
        app.title,
        app.header,
        app.subheader,
        app.caption,
        app.markdown,
        app.info,
        app.success,
        app.warning,
        app.error,
    )
    return "\n".join(str(element.value) for group in groups for element in group)


@pytest.fixture(autouse=True)
def preserve_real_event_history():
    existed_before = DEFAULT_EVENT_HISTORY_PATH.exists()
    content_before = DEFAULT_EVENT_HISTORY_PATH.read_bytes() if existed_before else None
    yield
    assert DEFAULT_EVENT_HISTORY_PATH.exists() is existed_before
    if existed_before:
        assert DEFAULT_EVENT_HISTORY_PATH.read_bytes() == content_before


def _scan(app, panel_code, workstation_label="EDGE-01 — Edge Banding"):
    app.selectbox[0].set_value(workstation_label)
    app.text_input[0].set_value(panel_code)
    app.run()
    _button(app, "Scan Panel").click()
    return app.run()


def _ask(app, question):
    app.text_area[0].set_value(question)
    app.run()
    _button(app, "Ask Agent").click()
    return app.run()


def test_app_loads_with_title_controls_and_both_workstations(tmp_path):
    app, backend = _make_app(tmp_path)

    assert not app.exception
    assert app.title[0].value == "Shop-Floor AI Agent"
    assert app.selectbox[0].options == [
        "EDGE-01 — Edge Banding",
        "DRILL-01 — Drilling",
    ]
    assert app.text_input[0].label == "Panel code"
    assert app.checkbox(key="use_question_context").value is True
    assert "Question context: No panel code · Workstation EDGE-01" in _visible_text(app)
    assert {button.label for button in app.button} >= {"Scan Panel", "Ask Agent"}
    assert backend.calls == []


def test_configuration_status_never_displays_api_key(tmp_path):
    secret = "sk-private-test-key-value"
    app, _ = _make_app(
        tmp_path,
        environment={"OPENAI_API_KEY": secret, "OPENAI_MODEL": "mock-model"},
    )

    text = _visible_text(app)
    assert "AI configured" in text
    assert "mock-model" in text
    assert secret not in text
    assert secret not in json.dumps(dict(app.session_state.filtered_state))


def test_missing_configuration_loads_without_crashing(tmp_path):
    app, backend = _make_app(tmp_path, environment={})

    assert not app.exception
    assert "AI configuration unavailable" in _visible_text(app)
    assert backend.calls == []


def test_vercel_hosted_mode_discloses_temporary_history(tmp_path):
    app, _ = _make_app(
        tmp_path,
        environment={
            "OPENAI_API_KEY": "configured-test-key",
            "OPENAI_MODEL": "mock-model",
            "VERCEL": "1",
        },
    )

    assert "event history is temporary and may reset" in _visible_text(app)


def test_scan_calls_injected_runner_once_with_context(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["panel_code"] == "P-1001"
    assert call["workstation_id"] == "EDGE-01"
    assert call["request_type"] == "scan"
    assert not app.exception


@pytest.mark.parametrize("entered_code", ["p-1001", "P1001", "p1001"])
def test_scan_normalizes_supported_panel_code_variants(tmp_path, entered_code):
    app, backend = _make_app(tmp_path)
    app = _scan(app, entered_code)

    assert backend.calls[0]["panel_code"] == "P-1001"
    assert app.session_state["current_panel"]["panel_code"] == "P-1001"
    assert "Panel P-1001" in _visible_text(app)


def test_correct_scan_displays_grounded_panel_sources_and_multitool_trace(tmp_path):
    app, _ = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    text = _visible_text(app)

    panel = app.session_state["current_panel"]
    assert panel["panel_code"] == "P-1001"
    assert panel["cabinet_id"] == "CAB-2001"
    assert panel["required_operation"] == "edge_banding"
    assert panel["required_workstation_id"] == "EDGE-01"
    assert "Panel P-1001" in text
    assert "Workstation EDGE-01" in text
    assert "SOP-EDGE-001" in text
    assert "get_panel" in text
    assert "get_workstation_requirements" in text
    assert "search_sop" in text
    assert "do not process" not in text.lower()
    assert "false mismatch" not in text.lower()


def test_panel_display_uses_lookup_not_model_text(tmp_path):
    backend = FakeBackend()

    def invented_runner(request, **kwargs):
        result = _correct_result()
        result["response"] = "Invented panel: Secret Rocket Door with titanium material."
        return result

    app = AppTest.from_function(
        _app_entry,
        kwargs={
            "agent_runner": invented_runner,
            "panel_lookup": get_panel,
            "history_reader": backend.history,
            "environment": {},
            "event_history_path": tmp_path / "events.jsonl",
        },
    ).run()
    app = _scan(app, "P-1001")

    assert app.session_state["current_panel"]["panel_name"] == "Base Cabinet Left Side"
    assert app.session_state["current_panel"]["material"] != "titanium"


def test_wrong_workstation_shows_stop_and_required_drilling_station(tmp_path):
    app, _ = _make_app(tmp_path)
    app = _scan(app, "P-1003")
    text = _visible_text(app).lower()

    assert app.session_state["current_panel"]["panel_code"] == "P-1003"
    assert "do not process" in text
    assert "drill-01" in text
    assert "sop-mismatch-001" in text
    assert "proceed at edge-01" not in text


def test_unsupported_question_has_no_numeric_setting_and_has_required_source(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    app = _ask(app, "What spindle speed should I use?")
    text = _visible_text(app).lower()

    assert len(backend.calls) == 2
    assert backend.calls[-1]["request_type"] == "question"
    assert "spindle speed is unavailable" in text
    assert "sop-unsupported-001" in text
    assert not any(character.isdigit() for character in app.session_state["latest_result"]["response"])
    assert app.session_state["current_panel"]["panel_code"] == "P-1001"


def test_question_context_is_visible_and_passed_by_default(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")

    assert "Question context: Panel P-1001 · Workstation EDGE-01" in _visible_text(app)

    app = _ask(app, "What does the SOP say for this panel?")
    call = backend.calls[-1]

    assert call["request_type"] == "question"
    assert call["panel_code"] == "P-1001"
    assert call["workstation_id"] == "EDGE-01"


def test_general_question_mode_omits_panel_and_workstation_from_call_and_event(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    app.checkbox(key="use_question_context").uncheck()
    app.run()

    assert "Question context: None · general SOP question" in _visible_text(app)

    app = _ask(app, "The physical panel label does not match the system information.")
    call = backend.calls[-1]

    assert call["request_type"] == "question"
    assert call["panel_code"] is None
    assert call["workstation_id"] is None
    assert backend.events[-1]["panel_code"] is None
    assert backend.events[-1]["workstation_id"] is None
    assert "supervisor escalation recorded" in _visible_text(app).lower()


def test_unknown_panel_clears_prior_details_and_shows_failed_trace(tmp_path):
    app, _ = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    assert app.session_state["current_panel"] is not None

    app = _scan(app, "P-9999")
    text = _visible_text(app).lower()
    assert app.session_state["current_panel"] is None
    assert "panel not found" in text
    assert "panel_not_found" in text
    assert "base cabinet left side" not in text


def test_physical_label_mismatch_is_escalated_in_result_trace_and_history(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    app = _ask(app, "The physical panel label does not match the system information.")
    text = _visible_text(app).lower()

    assert "do not process" in text
    assert "supervisor escalation recorded" in text
    assert text.count("supervisor escalation recorded") == 1
    assert "escalate_to_supervisor" in text
    assert backend.events[0]["event_type"] == "escalation"
    assert backend.events[0]["metadata"]["simulated"] is True
    assert app.dataframe[0].value.iloc[0]["event_type"] == "escalation"
    assert bool(app.dataframe[0].value.iloc[0]["simulated_escalation"]) is True


def test_missing_history_is_neutral_empty_state(tmp_path):
    app, _ = _make_app(tmp_path)

    assert "No scan, question, or escalation history yet." in _visible_text(app)


def test_malformed_history_is_safely_reported_without_path(tmp_path):
    private_path = tmp_path / "private-events.jsonl"

    def broken_history(_path=None, *, limit=None):
        raise EventHistoryError(f"Malformed file at {private_path}")

    app, _ = _make_app(tmp_path, history_reader=broken_history)
    text = _visible_text(app)

    assert "could not be read safely" in text
    assert str(private_path) not in text


def test_provider_exception_is_sanitized_and_app_remains_usable(tmp_path):
    backend = FakeBackend()
    backend.raise_provider_error = True
    app, _ = _make_app(tmp_path, backend=backend)
    app = _scan(app, "P-1001")
    text = _visible_text(app)

    assert "invalid result" in text.lower()
    assert "private provider detail" not in text
    assert "/private/path" not in text
    assert "sk-private-secret-value" not in text
    assert not app.exception


def test_changing_panel_or_workstation_invalidates_stale_output_without_api_call(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    assert len(backend.calls) == 1

    app.text_input[0].set_value("P-1002")
    app.run()
    assert app.session_state["current_panel"] is None
    assert app.session_state["latest_result"] is None
    assert len(backend.calls) == 1

    app = _scan(app, "P-1001")
    app.selectbox[0].set_value("DRILL-01 — Drilling")
    app.run()
    assert app.session_state["current_panel"] is None
    assert app.session_state["latest_result"] is None


def test_invalid_empty_scan_does_not_call_agent_or_keep_stale_state(tmp_path):
    app, backend = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    app.text_input[0].set_value("")
    app.run()
    _button(app, "Scan Panel").click()
    app.run()

    assert len(backend.calls) == 1
    assert app.session_state["current_panel"] is None
    assert "Enter a panel code" in _visible_text(app)


def test_question_and_scan_results_are_visibly_distinguished(tmp_path):
    app, _ = _make_app(tmp_path)
    app = _scan(app, "P-1001")
    assert "Scan result" in _visible_text(app)

    app = _ask(app, "What spindle speed should I use?")
    assert "Question result" in _visible_text(app)


def test_sources_come_from_result_contract_not_model_citation_text(tmp_path):
    def runner(request, **kwargs):
        result = _correct_result()
        result["response"] += " Citation: SOP-FAKE-999."
        return result

    backend = FakeBackend()
    app = AppTest.from_function(
        _app_entry,
        kwargs={
            "agent_runner": runner,
            "panel_lookup": get_panel,
            "history_reader": backend.history,
            "environment": {},
            "event_history_path": tmp_path / "events.jsonl",
        },
    ).run()
    app = _scan(app, "P-1001")

    assert "SOP-FAKE-999" not in _visible_text(app)
    assert "SOP-FAKE-999" not in app.session_state["latest_result"]["sources"]


def test_trace_and_state_exclude_private_reasoning_prompts_and_credentials(tmp_path):
    secret = "sk-sensitive-render-key"

    def runner(request, **kwargs):
        result = _correct_result()
        result["trace"][0]["input"] = {
            "api_key": secret,
            "prompt": "hidden system instructions",
            "panel_code": "P-1001",
        }
        return result

    backend = FakeBackend()
    app = AppTest.from_function(
        _app_entry,
        kwargs={
            "agent_runner": runner,
            "panel_lookup": get_panel,
            "history_reader": backend.history,
            "environment": {"OPENAI_API_KEY": secret, "OPENAI_MODEL": "mock-model"},
            "event_history_path": tmp_path / "events.jsonl",
        },
    ).run()
    app = _scan(app, "P-1001")
    rendered = _visible_text(app) + json.dumps(dict(app.session_state.filtered_state))

    assert secret not in rendered
    assert "hidden system instructions" not in rendered
    assert "[redacted]" in rendered


def test_safe_helpers_are_json_serializable_and_redact_sensitive_values():
    secret = "sk-sensitive-helper-key"
    safe = _safe_result(
        {
            "success": True,
            "response": f"value {secret}",
            "sources": ["Panel P-1001"],
            "trace": [{"input": {"authorization": secret}, "success": True}],
            "escalated": False,
        }
    )

    rendered = json.dumps(safe)
    assert secret not in rendered
    assert "[redacted]" in rendered
    json.dumps(_safe_value({"values": (1, True, None), "object": object()}))


def test_ui_tests_use_temporary_history_and_never_modify_real_history(tmp_path):
    real_history_before = (
        DEFAULT_EVENT_HISTORY_PATH.read_bytes()
        if DEFAULT_EVENT_HISTORY_PATH.exists()
        else None
    )
    app, backend = _make_app(tmp_path)
    _scan(app, "P-1001")

    assert backend.calls[0]["event_history_path"] == tmp_path / "events.jsonl"
    real_history_after = (
        DEFAULT_EVENT_HISTORY_PATH.read_bytes()
        if DEFAULT_EVENT_HISTORY_PATH.exists()
        else None
    )
    assert real_history_after == real_history_before


def test_app_source_uses_real_runner_default_but_no_browser_test_switch():
    source = Path("src/ui.py").read_text(encoding="utf-8")
    app_source = Path("app.py").read_text(encoding="utf-8")
    script_source = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert "agent_runner: Callable[..., dict[str, Any]] = run_agent" in source
    assert 'st.App(str(Path(__file__).resolve().with_name("streamlit_app.py")))' in app_source
    assert "render_app(" in script_source
    assert "TEST_MODE" not in source + app_source + script_source
    assert "OPENAI_API_KEY" not in storable_session_keys(source)


def storable_session_keys(source):
    lines = [line for line in source.splitlines() if "session_state" in line]
    return "\n".join(lines)
