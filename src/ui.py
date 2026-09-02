"""Testable Streamlit UI for the grounded shop-floor agent."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from src.agent import run_agent
from src.event_history import EventHistoryError, read_event_history
from src.tools import get_panel, normalize_panel_code as _normalize_panel_code


WORKSTATION_OPTIONS = {
    "EDGE-01 — Edge Banding": "EDGE-01",
    "DRILL-01 — Drilling": "DRILL-01",
}
PANEL_EXAMPLES = ("P-1001", "P-1002", "P-1003", "P-1004")
_SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_SOURCE_LABEL_PATTERN = re.compile(
    r"\b(?:SOP-[A-Z]+-\d{3}|Panel\s+[A-Z0-9-]+|Workstation\s+[A-Z0-9-]+)\b"
)
_SENSITIVE_KEYS = frozenset(
    {"api_key", "authorization", "credential", "password", "prompt", "secret", "token"}
)


def _initial_state() -> dict[str, Any]:
    return {
        "current_panel": None,
        "latest_result": None,
        "latest_scan_result": None,
        "latest_action": None,
        "result_context": None,
        "chat_messages": [],
    }


def _ensure_state() -> None:
    for key, value in _initial_state().items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_result_state() -> None:
    initial = _initial_state()
    for key in (
        "current_panel",
        "latest_result",
        "latest_scan_result",
        "latest_action",
        "result_context",
    ):
        st.session_state[key] = initial[key]


def _clear_chat_state() -> None:
    st.session_state.chat_messages = []


def _selected_workstation_id() -> str:
    label = st.session_state.get("workstation_label", next(iter(WORKSTATION_OPTIONS)))
    return WORKSTATION_OPTIONS.get(label, "EDGE-01")


def _safe_value(value: Any) -> Any:
    """Return a JSON-like value with credential-shaped data removed."""

    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if str(key).lower() in _SENSITIVE_KEYS
            else _safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_PATTERN.sub("[redacted]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unavailable]"


def _safe_result(result: Any) -> dict[str, Any]:
    """Normalize a runner result into the UI's safe display contract."""

    if not isinstance(result, dict):
        return {
            "success": False,
            "response": "The agent returned an invalid result. Stop and try again later.",
            "sources": [],
            "trace": [],
            "escalated": False,
            "model": None,
            "error": {"code": "invalid_agent_result", "message": "Agent result unavailable."},
        }
    response = result.get("response")
    sources = result.get("sources")
    trace = result.get("trace")
    error = result.get("error")
    safe_error = None
    if isinstance(error, dict):
        safe_error = {
            "code": str(error.get("code") or "agent_error"),
            "message": "The request could not be completed safely.",
        }
    safe_sources = [
        _safe_value(source) for source in sources if isinstance(source, str)
    ] if isinstance(sources, list) else []
    safe_response = (
        _safe_value(response)
        if isinstance(response, str) and response.strip()
        else "The request could not be completed safely."
    )
    safe_response = _SOURCE_LABEL_PATTERN.sub(
        lambda match: match.group(0)
        if match.group(0) in safe_sources
        else "[unverified source removed]",
        safe_response,
    )
    safe_trace = []
    if isinstance(trace, list):
        for index, entry in enumerate(trace, start=1):
            if not isinstance(entry, dict):
                continue
            entry_sources = entry.get("sources")
            entry_error = entry.get("error")
            safe_trace.append(
                {
                    "sequence": entry.get("sequence")
                    if isinstance(entry.get("sequence"), int)
                    else index,
                    "tool": _safe_value(entry.get("tool"))
                    if isinstance(entry.get("tool"), str)
                    else "unknown_tool",
                    "input": _safe_value(entry.get("input"))
                    if isinstance(entry.get("input"), dict)
                    else {},
                    "success": entry.get("success") is True,
                    "sources": [
                        _safe_value(source)
                        for source in entry_sources
                        if isinstance(source, str)
                    ]
                    if isinstance(entry_sources, list)
                    else [],
                    "error": {
                        "code": _safe_value(entry_error.get("code") or "tool_error"),
                        "message": "The tool could not be completed safely.",
                    }
                    if isinstance(entry_error, dict)
                    else None,
                }
            )
    return {
        "success": result.get("success") is True,
        "response": safe_response,
        "sources": safe_sources,
        "trace": safe_trace,
        "escalated": result.get("escalated") is True,
        "model": _safe_value(result.get("model"))
        if isinstance(result.get("model"), str)
        else None,
        "error": safe_error,
    }


def _has_successful_tool(result: dict[str, Any], tool_name: str) -> bool:
    return any(
        entry.get("tool") == tool_name and entry.get("success") is True
        for entry in result.get("trace", [])
        if isinstance(entry, dict)
    )


def _run_request(
    *,
    agent_runner: Callable[..., dict[str, Any]],
    panel_lookup: Callable[[Any], dict[str, Any]],
    request: str,
    request_type: str,
    panel_code: str | None,
    workstation_id: str | None,
    event_history_path: str | Path | None,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if request_type == "scan":
        _clear_result_state()
    else:
        st.session_state.latest_result = None
        st.session_state.latest_action = None

    try:
        raw_result = agent_runner(
            request,
            panel_code=panel_code,
            workstation_id=workstation_id,
            request_type=request_type,
            event_history_path=event_history_path,
            conversation_history=conversation_history,
        )
    except Exception:
        raw_result = None
    result = _safe_result(raw_result)

    panel = st.session_state.get("current_panel")
    if request_type == "scan":
        panel = None
        if panel_code and _has_successful_tool(result, "get_panel"):
            try:
                lookup_result = panel_lookup(panel_code)
            except Exception:
                lookup_result = None
            if isinstance(lookup_result, dict) and lookup_result.get("success") is True:
                data = lookup_result.get("data")
                if isinstance(data, dict):
                    panel = _safe_value(data)

    st.session_state.current_panel = panel
    st.session_state.latest_result = result
    if request_type == "scan":
        st.session_state.latest_scan_result = result
    st.session_state.latest_action = request_type
    st.session_state.result_context = {
        "panel_code": panel_code,
        "workstation_id": workstation_id,
    }
    return result


def _conversation_for_agent(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    conversation: list[dict[str, str]] = []
    for message in messages[-16:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user" and isinstance(message.get("content"), str):
            conversation.append({"role": "user", "content": message["content"]})
        elif role == "assistant" and isinstance(message.get("result"), dict):
            response = message["result"].get("response")
            if isinstance(response, str) and response.strip():
                conversation.append({"role": "assistant", "content": response})
    return conversation[-8:]


def _render_panel(panel: dict[str, Any] | None, workstation_id: str) -> None:
    st.subheader("Current panel information")
    if not panel:
        return

    dimensions = panel.get("dimensions_mm")
    if isinstance(dimensions, dict):
        dimension_text = (
            f"{dimensions.get('length')} × {dimensions.get('width')} × "
            f"{dimensions.get('thickness')} mm"
        )
    else:
        dimension_text = "Unavailable"
    rows = {
        "Panel code": panel.get("panel_code", "Unavailable"),
        "Cabinet ID": panel.get("cabinet_id", "Unavailable"),
        "Panel name": panel.get("panel_name", "Unavailable"),
        "Dimensions": dimension_text,
        "Material": panel.get("material", "Unavailable"),
        "Required operation": panel.get("required_operation", "Unavailable"),
        "Required workstation": panel.get("required_workstation_id", "Unavailable"),
    }
    st.table([{"Field": key, "Value": value} for key, value in rows.items()])

    if panel.get("required_workstation_id") == workstation_id:
        st.success("Workstation match: the selected workstation matches the panel record.")
    else:
        required = panel.get("required_workstation_id", "the required workstation")
        st.error(
            f"STOP — do not process at {workstation_id}. The panel requires {required}."
        )


def _render_sources_and_trace(result: dict[str, Any]) -> None:
    st.subheader("Sources")
    sources = result.get("sources", [])
    if sources:
        for source in sources:
            st.markdown(f"- `{source}`")
    else:
        st.caption("No grounded source references were returned.")

    with st.expander("Agent trace"):
        trace = result.get("trace", [])
        if not trace:
            st.caption("No tool activity was recorded.")
        for index, entry in enumerate(trace, start=1):
            if not isinstance(entry, dict):
                continue
            success = entry.get("success") is True
            icon = "✓" if success else "✗"
            sequence = entry.get("sequence", index)
            tool_name = entry.get("tool", "unknown_tool")
            st.markdown(f"{icon} **{sequence}. {tool_name}**")
            st.json(entry.get("input", {}), expanded=False)
            if entry.get("sources"):
                st.caption("Sources: " + ", ".join(entry["sources"]))
            if not success and isinstance(entry.get("error"), dict):
                st.caption(
                    "Safe error: " + str(entry["error"].get("code", "tool_error"))
                )


def _render_result(result: dict[str, Any] | None, action: str | None) -> None:
    st.subheader("Agent instructions")
    if result is None:
        return

    action_label = "Scan result" if action == "scan" else "Question result"
    st.caption(action_label)
    response = str(result.get("response", "The request could not be completed safely."))
    if result.get("escalated"):
        st.warning(response)
    elif result.get("success"):
        st.success(response)
    else:
        st.error(response)
        error = result.get("error")
        if isinstance(error, dict):
            st.caption(f"Safe error: {error.get('code', 'agent_error')}")

    _render_sources_and_trace(result)


def _render_chat_result(result: dict[str, Any]) -> None:
    response = str(result.get("response", "The request could not be completed safely."))
    if result.get("success"):
        st.markdown(response)
    else:
        st.error(response)
        error = result.get("error")
        if isinstance(error, dict):
            st.caption(f"Safe error: {error.get('code', 'agent_error')}")

    sources = result.get("sources", [])
    if sources:
        st.caption("Sources: " + ", ".join(f"`{source}`" for source in sources))

    trace = result.get("trace", [])
    if trace:
        with st.expander("Tool trace"):
            for index, entry in enumerate(trace, start=1):
                if not isinstance(entry, dict):
                    continue
                success = entry.get("success") is True
                icon = "✓" if success else "✗"
                sequence = entry.get("sequence", index)
                tool_name = entry.get("tool", "unknown_tool")
                st.markdown(f"{icon} **{sequence}. {tool_name}**")
                st.json(entry.get("input", {}), expanded=False)
                if entry.get("sources"):
                    st.caption("Sources: " + ", ".join(entry["sources"]))
                if not success and isinstance(entry.get("error"), dict):
                    st.caption(
                        "Safe error: "
                        + str(entry["error"].get("code", "tool_error"))
                    )


def _safe_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    metadata = event.get("metadata")
    simulated = isinstance(metadata, dict) and metadata.get("simulated") is True
    return {
        "timestamp": _safe_value(event.get("timestamp_utc") or "Unavailable"),
        "event_type": _safe_value(event.get("event_type") or "unknown"),
        "panel_code": _safe_value(event.get("panel_code") or "—"),
        "workstation_id": _safe_value(event.get("workstation_id") or "—"),
        "message": _safe_value(event.get("message") or "No message"),
        "simulated_escalation": simulated,
    }


def _render_history(
    history_reader: Callable[..., list[dict[str, Any]]],
    event_history_path: str | Path | None,
) -> None:
    try:
        events = history_reader(event_history_path, limit=20)
    except (EventHistoryError, OSError, ValueError, TypeError):
        st.warning("Event history is unavailable because it could not be read safely.")
        return
    except Exception:
        st.warning("Event history is temporarily unavailable.")
        return

    safe_events = [_safe_event(event) for event in events]
    safe_events = [event for event in safe_events if event is not None]
    if not safe_events:
        return
    with st.expander("Event history"):
        st.dataframe(list(reversed(safe_events)), width="stretch", hide_index=True)


def render_app(
    *,
    agent_runner: Callable[..., dict[str, Any]] = run_agent,
    panel_lookup: Callable[[Any], dict[str, Any]] = get_panel,
    history_reader: Callable[..., list[dict[str, Any]]] = read_event_history,
    environment: Mapping[str, str] | None = None,
    event_history_path: str | Path | None = None,
) -> None:
    """Render the local app with explicit dependency seams for safe UI tests."""

    config = os.environ if environment is None else environment
    configured_model = config.get("OPENAI_MODEL", "").strip()
    ai_configured = bool(config.get("OPENAI_API_KEY", "").strip() and configured_model)

    st.set_page_config(page_title="Shop-Floor AI Agent", page_icon="🏭", layout="wide")
    _ensure_state()

    st.title("Shop-Floor AI Agent")
    st.caption("Junior AI engineer assessment · fictional shop-floor prototype")
    if ai_configured:
        st.success(f"AI configured · model: {_safe_value(configured_model)}")
    else:
        st.warning("AI configuration unavailable")
    if config.get("VERCEL"):
        st.caption("Hosted prototype · event history is temporary and may reset.")

    st.subheader("Scan controls")
    control_left, control_right = st.columns(2)
    with control_left:
        st.selectbox(
            "Workstation",
            list(WORKSTATION_OPTIONS),
            key="workstation_label",
            on_change=_clear_result_state,
        )
    with control_right:
        st.text_input(
            "Panel code",
            placeholder="Enter P-1001, P1001, or an unknown code such as P-9999",
            key="panel_code_input",
            on_change=_clear_result_state,
        )
        st.caption("Examples: " + ", ".join(PANEL_EXAMPLES))

    if st.button("Scan Panel", type="primary", width="stretch"):
        panel_code = _normalize_panel_code(st.session_state.panel_code_input)
        workstation_id = _selected_workstation_id()
        if panel_code is None:
            _clear_result_state()
            invalid_result = _safe_result(
                {
                    "success": False,
                    "response": "Enter a panel code before scanning.",
                    "sources": [],
                    "trace": [],
                    "escalated": False,
                    "error": {"code": "invalid_input"},
                }
            )
            st.session_state.latest_result = invalid_result
            st.session_state.latest_scan_result = invalid_result
            st.session_state.latest_action = "scan"
        else:
            _run_request(
                agent_runner=agent_runner,
                panel_lookup=panel_lookup,
                request=(
                    f"Verify whether panel {panel_code} can be processed at workstation "
                    f"{workstation_id} and provide only grounded instructions."
                ),
                request_type="scan",
                panel_code=panel_code,
                workstation_id=workstation_id,
                event_history_path=event_history_path,
            )

    current_workstation = _selected_workstation_id()
    _render_panel(st.session_state.current_panel, current_workstation)
    _render_result(st.session_state.latest_scan_result, "scan")

    st.subheader("Ask the agent")
    current_panel = st.session_state.current_panel
    question_panel_code = (
        current_panel.get("panel_code")
        if isinstance(current_panel, dict)
        else _normalize_panel_code(st.session_state.panel_code_input)
    )
    use_question_context = st.checkbox(
        "Use selected panel and workstation context",
        value=True,
        key="use_question_context",
        help=(
            "Turn this off for a general SOP question that should not be associated "
            "with the selected panel or workstation."
        ),
    )
    if use_question_context:
        panel_context_label = (
            f"Panel {question_panel_code}" if question_panel_code else "No panel code"
        )
        st.caption(
            f"Question context: {panel_context_label} · Workstation {current_workstation}"
        )
    else:
        st.caption("Question context: None · general SOP question")

    st.button(
        "Clear chat",
        icon=":material/delete_sweep:",
        on_click=_clear_chat_state,
    )

    with st.container(border=True):
        transcript = st.container()
        question = st.chat_input(
            "Ask about a panel, approved SOP guidance, or a shop-floor issue",
            key="agent_chat_input",
            submit_mode="disable",
        )

    with transcript:
        for message in st.session_state.chat_messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "user":
                with st.chat_message("user"):
                    st.markdown(str(message.get("content", "")))
                    if message.get("context"):
                        st.caption(str(message["context"]))
            elif role == "assistant" and isinstance(message.get("result"), dict):
                with st.chat_message("assistant"):
                    _render_chat_result(message["result"])

        if question:
            normalized_question = question.strip()
            if not normalized_question:
                st.warning("Enter a question before asking the agent.")
            else:
                selected_panel = question_panel_code if use_question_context else None
                selected_workstation = (
                    current_workstation if use_question_context else None
                )
                context_label = (
                    f"Context: {panel_context_label} · Workstation {current_workstation}"
                    if use_question_context
                    else "Context: General SOP question"
                )
                safe_question = str(_safe_value(normalized_question))
                user_message = {
                    "role": "user",
                    "content": safe_question,
                    "context": context_label,
                }
                st.session_state.chat_messages.append(user_message)
                with st.chat_message("user"):
                    st.markdown(safe_question)
                    st.caption(context_label)

                with st.chat_message("assistant"):
                    with st.status(
                        ":shimmer[Checking approved records]", type="compact"
                    ) as request_status:
                        result = _run_request(
                            agent_runner=agent_runner,
                            panel_lookup=panel_lookup,
                            request=normalized_question,
                            request_type="question",
                            panel_code=selected_panel,
                            workstation_id=selected_workstation,
                            event_history_path=event_history_path,
                            conversation_history=_conversation_for_agent(
                                st.session_state.chat_messages[:-1]
                            ),
                        )
                        request_status.update(
                            label="Checked approved records", state="complete"
                        )
                    _render_chat_result(result)

                st.session_state.chat_messages.append(
                    {"role": "assistant", "result": result}
                )
                st.session_state.chat_messages = st.session_state.chat_messages[-20:]

    _render_history(history_reader, event_history_path)
