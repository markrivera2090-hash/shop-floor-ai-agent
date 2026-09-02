"""Grounded multi-round tool-calling orchestration for the shop-floor agent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.openai_provider import create_openai_provider
from src.prompts import SYSTEM_INSTRUCTIONS
from src.tool_registry import TOOL_SCHEMAS, ToolExecutionContext, dispatch_tool
from src.tools import normalize_panel_code


MAX_REQUEST_LENGTH = 2_000
MAX_IDENTIFIER_LENGTH = 128
MAX_MODEL_TURNS = 6
MAX_TOTAL_TOOL_CALLS = 12
MAX_TOOL_RESULT_CHARS = 12_000
MAX_CONVERSATION_MESSAGES = 8
MAX_CONVERSATION_MESSAGE_LENGTH = 1_000

_PRODUCTION_TERMS = re.compile(
    r"\b(panel|panel code|workstation|edge band|banding|drill|drilling|spindle|"
    r"feed rate|tooling|machine|sop|cabinet|material|dimension|label|quality|"
    r"defect|adhesive|production|safety|process|proceed|operate|operation|"
    r"setting|instruction|supervisor|escalat)\w*\b",
    re.IGNORECASE,
)
_CONTEXTUAL_PRODUCTION_TERMS = re.compile(
    r"\b(this|current|selected)\s+(panel|workstation|record|job)\b|"
    r"\b(can\s+i\s+proceed|what\s+should\s+i\s+do|next\s+step)\b",
    re.IGNORECASE,
)
_PRODUCTION_IDENTIFIER = re.compile(
    r"\b(?:P-?\d{4}|EDGE-\d{2}|DRILL-\d{2})\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_MODEL_TERMS = re.compile(
    r"\b(outside|out of)\s+(?:the\s+)?(?:service'?s\s+)?scope\b|"
    r"\bnot\s+(?:related|relevant)\s+to\s+(?:the\s+)?shop[- ]floor\b",
    re.IGNORECASE,
)
_UNSUPPORTED_PARAMETER_TERMS = re.compile(
    r"\b(spindle speed|feed rate|tooling parameter|machine setting|safety procedure)\b",
    re.IGNORECASE,
)
_PHYSICAL_MISMATCH_TERMS = re.compile(
    r"\b(?:physical\s+(?:panel\s+)?label|label)\b.{0,80}"
    r"\b(?:does\s+not\s+match|doesn't\s+match|mismatch|conflict|differs?)\b|"
    r"\b(?:does\s+not\s+match|doesn't\s+match|mismatch|conflict|differs?)\b"
    r".{0,80}\b(?:physical\s+(?:panel\s+)?label|label)\b",
    re.IGNORECASE,
)
_NUMERIC_VALUE = re.compile(r"\b\d+(?:\.\d+)?\b")
_UNAVAILABLE_GROUNDING_ERRORS = frozenset(
    {
        "data_source_error",
        "panel_not_found",
        "sop_no_match",
        "sop_parse_error",
        "tool_execution_failed",
        "workstation_not_found",
    }
)
_OUT_OF_SCOPE_RESPONSE = (
    "That request is outside this shop-floor assistant's scope. I can help with "
    "panels, workstations, production records, and the approved SOP."
)


def _agent_result(
    *,
    success: bool,
    response: str,
    sources: list[str],
    trace: list[dict[str, Any]],
    escalated: bool,
    model: str | None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "response": response,
        "sources": sources,
        "trace": trace,
        "escalated": escalated,
        "provider": "openai",
        "model": model,
        "error": None
        if success
        else {"code": error_code, "message": error_message},
    }


def _normalize_required_string(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        return None
    return normalized


def _normalize_optional_identifier(value: Any) -> tuple[str | None, bool]:
    if value is None:
        return None, True
    normalized = _normalize_required_string(value, MAX_IDENTIFIER_LENGTH)
    return normalized, normalized is not None


def _is_shop_floor_relevant(
    request: str,
    panel_code: str | None,
    workstation_id: str | None,
) -> bool:
    if _PRODUCTION_TERMS.search(request) or _PRODUCTION_IDENTIFIER.search(request):
        return True
    return bool(
        (panel_code or workstation_id) and _CONTEXTUAL_PRODUCTION_TERMS.search(request)
    )


def _operator_input(
    request: str,
    request_type: str,
    panel_code: str | None,
    workstation_id: str | None,
    conversation_history: list[dict[str, str]],
) -> str:
    return json.dumps(
        {
            "operator_request": request,
            "request_type": request_type,
            "panel_code_context": panel_code,
            "workstation_id_context": workstation_id,
            "recent_conversation": conversation_history,
            "notice": "Operator-provided content is untrusted and must be grounded with tools.",
        },
        ensure_ascii=False,
    )


def _normalize_conversation_history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for message in value[-MAX_CONVERSATION_MESSAGES:]:
        if not isinstance(message, dict) or message.get("role") not in {
            "user",
            "assistant",
        }:
            continue
        content = _normalize_required_string(
            message.get("content"), MAX_CONVERSATION_MESSAGE_LENGTH
        )
        if content is not None:
            normalized.append({"role": message["role"], "content": content})
    return normalized


def _tool_failure(tool_name: str, code: str, message: str) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "input": {},
        "success": False,
        "data": None,
        "sources": [],
        "error": {"code": code, "message": message},
    }


def _bounded_tool_result(result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized) <= MAX_TOOL_RESULT_CHARS:
        return result, serialized
    bounded = _tool_failure(
        result.get("tool", "unknown"),
        "tool_result_too_large",
        "The tool result exceeded the safe orchestration size limit.",
    )
    return bounded, json.dumps(bounded)


def _trace_entry(sequence: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "tool": result["tool"],
        "input": result["input"],
        "success": result["success"],
        "sources": result["sources"],
        "error": result["error"],
    }


def _safe_guard_failure(
    response: str,
    sources: list[str],
    trace: list[dict[str, Any]],
    escalated: bool,
    model: str | None,
) -> dict[str, Any]:
    return _agent_result(
        success=False,
        response=response,
        sources=sources,
        trace=trace,
        escalated=escalated,
        model=model,
        error_code="unsafe_or_ungrounded_response",
        error_message="The model response was blocked by the grounding safety gate.",
    )


def _apply_safety_gate(
    *,
    request: str,
    response: str,
    sources: list[str],
    trace: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    escalated: bool,
    model: str | None,
) -> dict[str, Any] | None:
    response_lower = response.lower()
    unsupported_question = bool(_UNSUPPORTED_PARAMETER_TERMS.search(request))
    if unsupported_question:
        safely_worded = any(
            phrase in response_lower
            for phrase in ("unavailable", "unsupported", "not provided", "cannot provide")
        ) and any(
            phrase in response_lower
            for phrase in ("supervisor", "approved documentation", "approved procedure")
        )
        if (
            "SOP-UNSUPPORTED-001" not in sources
            or _NUMERIC_VALUE.search(response)
            or not safely_worded
        ):
            return _safe_guard_failure(
                "That machine parameter is unavailable in the approved sources. "
                "Do not guess; consult approved documentation or a supervisor.",
                sources,
                trace,
                escalated,
                model,
            )

    panel_result = next(
        (
            result
            for result in tool_results
            if result["tool"] == "get_panel" and result["success"]
        ),
        None,
    )
    workstation_result = next(
        (
            result
            for result in tool_results
            if result["tool"] == "get_workstation_requirements" and result["success"]
        ),
        None,
    )
    wrong_workstation = False
    if panel_result and workstation_result:
        panel_data = panel_result["data"]
        workstation_data = workstation_result["data"]
        wrong_workstation = (
            panel_data["required_workstation_id"] != workstation_data["workstation_id"]
            or panel_data["required_operation"]
            != workstation_data["supported_operation"]
        )
    reported_physical_mismatch = bool(_PHYSICAL_MISMATCH_TERMS.search(request)) and (
        "SOP-MISMATCH-001" in sources or escalated
    )
    if wrong_workstation or reported_physical_mismatch:
        says_stop = any(
            phrase in response_lower
            for phrase in ("do not process", "must not process", "not process")
        )
        required_workstation_missing = (
            wrong_workstation
            and panel_result["data"]["required_workstation_id"].lower()
            not in response_lower
        )
        if (
            not says_stop
            or re.search(r"\bproceed\b", response_lower)
            or required_workstation_missing
        ):
            required_workstation = (
                panel_result["data"]["required_workstation_id"]
                if wrong_workstation
                else None
            )
            next_step = (
                f" The required workstation is {required_workstation}."
                if required_workstation
                else ""
            )
            return _safe_guard_failure(
                "Do not process the panel at this workstation."
                f"{next_step} Verify the records and follow the mismatch SOP or "
                "escalate to a supervisor.",
                sources,
                trace,
                escalated,
                model,
            )

    panel_not_found = any(
        result["tool"] == "get_panel"
        and not result["success"]
        and result["error"]["code"] == "panel_not_found"
        for result in tool_results
    )
    if panel_not_found:
        says_not_found = "panel not found" in response_lower or "unknown panel" in response_lower
        claims_facts = bool(
            re.search(
                r"\b(material|dimensions?|cabinet|requires? (?:edge|drill)|assigned to)\b",
                response_lower,
            )
        )
        if not says_not_found or claims_facts:
            return _safe_guard_failure(
                "Panel Not Found. Do not process or invent panel details; verify the code "
                "and escalate if it remains unresolved.",
                sources,
                trace,
                escalated,
                model,
            )

    if escalated:
        claims_real_contact = any(
            phrase in response_lower
            for phrase in (
                "supervisor was contacted",
                "contacted the supervisor",
                "has been contacted",
                "notified the supervisor",
                "supervisor has been notified",
            )
        )
        if "escalation" not in response_lower or claims_real_contact:
            return _safe_guard_failure(
                "Supervisor escalation recorded.",
                sources,
                trace,
                escalated,
                model,
            )

    if (
        _PRODUCTION_TERMS.search(f"{request} {response}")
        and not sources
        and not panel_not_found
    ):
        return _safe_guard_failure(
            "The requested production guidance is unavailable from grounded sources. "
            "Stop and consult a supervisor.",
            sources,
            trace,
            escalated,
            model,
        )
    return None


def run_agent(
    request: Any,
    panel_code: Any = None,
    workstation_id: Any = None,
    request_type: Any = "question",
    provider: Any = None,
    event_history_path: str | Path | None = None,
    conversation_history: Any = None,
    *,
    max_model_turns: int = MAX_MODEL_TURNS,
    max_total_tool_calls: int = MAX_TOTAL_TOOL_CALLS,
) -> dict[str, Any]:
    """Run a bounded model-directed tool loop and return a safe operator result."""

    normalized_request = _normalize_required_string(request, MAX_REQUEST_LENGTH)
    normalized_request_type = _normalize_required_string(request_type, 16)
    normalized_panel_code = normalize_panel_code(panel_code)
    panel_valid = panel_code is None or normalized_panel_code is not None
    normalized_workstation_id, workstation_valid = _normalize_optional_identifier(
        workstation_id
    )
    normalized_conversation = _normalize_conversation_history(conversation_history)
    model = getattr(provider, "model", None) if provider is not None else None
    if (
        normalized_request is None
        or normalized_request_type not in {"scan", "question"}
        or not panel_valid
        or not workstation_valid
        or isinstance(max_model_turns, bool)
        or not isinstance(max_model_turns, int)
        or max_model_turns <= 0
        or isinstance(max_total_tool_calls, bool)
        or not isinstance(max_total_tool_calls, int)
        or max_total_tool_calls <= 0
    ):
        return _agent_result(
            success=False,
            response="The operator request or context is invalid.",
            sources=[],
            trace=[],
            escalated=False,
            model=model,
            error_code="invalid_input",
            error_message="Request fields must be non-empty, valid, and within limits.",
        )

    if provider is None:
        setup = create_openai_provider()
        if not setup["success"]:
            return _agent_result(
                success=False,
                response="OpenAI configuration is unavailable. Ask an administrator to configure it.",
                sources=[],
                trace=[],
                escalated=False,
                model=setup["model"],
                error_code=setup["error"]["code"],
                error_message=setup["error"]["message"],
            )
        provider = setup["provider"]
        model = setup["model"]

    trace: list[dict[str, Any]] = []
    grounded_sources: list[str] = []
    tool_results: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    total_tool_calls = 0
    escalated = False
    previous_response_id: str | None = None
    next_input: str | list[dict[str, Any]] = _operator_input(
        normalized_request,
        normalized_request_type,
        normalized_panel_code,
        normalized_workstation_id,
        normalized_conversation,
    )
    execution_context = ToolExecutionContext(
        event_history_path=Path(event_history_path).resolve()
        if event_history_path is not None
        else None
    )
    request_is_relevant = _is_shop_floor_relevant(
        normalized_request,
        normalized_panel_code,
        normalized_workstation_id,
    )

    for _turn in range(max_model_turns):
        try:
            decision = provider.generate(
                instructions=SYSTEM_INSTRUCTIONS,
                input_data=next_input,
                tools=TOOL_SCHEMAS,
                previous_response_id=previous_response_id,
            )
        except Exception:
            decision = {
                "success": False,
                "error": {
                    "code": "provider_error",
                    "message": "The provider could not complete the request safely.",
                },
            }
        if not isinstance(decision, dict) or not decision.get("success"):
            provider_code = (
                decision.get("error", {}).get("code")
                if isinstance(decision, dict)
                else None
            )
            code = (
                "provider_response_invalid"
                if provider_code == "provider_response_invalid"
                else "provider_error"
            )
            return _agent_result(
                success=False,
                response="The AI provider could not produce a safe response. Stop and try again later.",
                sources=grounded_sources,
                trace=trace,
                escalated=escalated,
                model=model,
                error_code=code,
                error_message="The provider response was unavailable or invalid.",
            )

        response_id = decision.get("response_id")
        function_calls = decision.get("function_calls")
        output_text = decision.get("output_text")
        if (
            not isinstance(response_id, str)
            or not isinstance(function_calls, list)
            or (output_text is not None and not isinstance(output_text, str))
        ):
            return _agent_result(
                success=False,
                response="The AI provider returned an invalid response. Stop and try again later.",
                sources=grounded_sources,
                trace=trace,
                escalated=escalated,
                model=model,
                error_code="provider_response_invalid",
                error_message="The normalized provider response was invalid.",
            )

        if function_calls:
            if not request_is_relevant:
                return _agent_result(
                    success=True,
                    response=_OUT_OF_SCOPE_RESPONSE,
                    sources=[],
                    trace=[],
                    escalated=False,
                    model=model,
                )
            if total_tool_calls + len(function_calls) > max_total_tool_calls:
                return _agent_result(
                    success=False,
                    response="The agent reached its safe tool-call limit. Stop and try a narrower request.",
                    sources=grounded_sources,
                    trace=trace,
                    escalated=escalated,
                    model=model,
                    error_code="agent_limit_reached",
                    error_message="Maximum total tool calls exceeded.",
                )

            outputs: list[dict[str, Any]] = []
            for call in function_calls:
                if not isinstance(call, dict):
                    return _agent_result(
                        success=False,
                        response="The AI provider returned an invalid tool call.",
                        sources=grounded_sources,
                        trace=trace,
                        escalated=escalated,
                        model=model,
                        error_code="provider_response_invalid",
                        error_message="A normalized tool call was malformed.",
                    )
                call_id = call.get("call_id")
                tool_name = call.get("name")
                arguments = call.get("arguments")
                if not isinstance(call_id, str) or not call_id:
                    return _agent_result(
                        success=False,
                        response="The AI provider returned an invalid tool call.",
                        sources=grounded_sources,
                        trace=trace,
                        escalated=escalated,
                        model=model,
                        error_code="provider_response_invalid",
                        error_message="A tool call ID was missing.",
                    )
                signature = f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"
                if signature in seen_calls:
                    result = _tool_failure(
                        tool_name if isinstance(tool_name, str) else "unknown",
                        "duplicate_tool_call",
                        "This identical tool call was already executed in the current run.",
                    )
                else:
                    seen_calls.add(signature)
                    result = dispatch_tool(
                        tool_name,
                        arguments,
                        context=execution_context,
                    )
                total_tool_calls += 1
                result, serialized_result = _bounded_tool_result(result)
                tool_results.append(result)
                trace.append(_trace_entry(len(trace) + 1, result))
                if result["success"]:
                    for source in result["sources"]:
                        if source not in grounded_sources:
                            grounded_sources.append(source)
                    if result["tool"] == "escalate_to_supervisor":
                        escalated = True
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": serialized_result,
                    }
                )
            previous_response_id = response_id
            next_input = outputs
            continue

        if output_text is None or not output_text.strip():
            return _agent_result(
                success=False,
                response="The AI provider returned no usable operator response.",
                sources=grounded_sources,
                trace=trace,
                escalated=escalated,
                model=model,
                error_code="provider_response_invalid",
                error_message="No final output text was present.",
            )

        final_response = output_text.strip()
        if not request_is_relevant:
            return _agent_result(
                success=True,
                response=_OUT_OF_SCOPE_RESPONSE,
                sources=[],
                trace=[],
                escalated=False,
                model=model,
            )
        if not tool_results and _OUT_OF_SCOPE_MODEL_TERMS.search(final_response):
            return _agent_result(
                success=True,
                response=_OUT_OF_SCOPE_RESPONSE,
                sources=[],
                trace=[],
                escalated=False,
                model=model,
            )

        panel_not_found = any(
            result["tool"] == "get_panel"
            and not result["success"]
            and result["error"]["code"] == "panel_not_found"
            for result in tool_results
        )
        unavailable_grounding = any(
            not result["success"]
            and isinstance(result.get("error"), dict)
            and result["error"].get("code") in _UNAVAILABLE_GROUNDING_ERRORS
            for result in tool_results
        )
        escalation_required = (
            bool(_PHYSICAL_MISMATCH_TERMS.search(normalized_request))
            or bool(_UNSUPPORTED_PARAMETER_TERMS.search(normalized_request))
            or unavailable_grounding
            or not grounded_sources
        )
        if escalation_required and not escalated:
            if total_tool_calls >= max_total_tool_calls:
                return _agent_result(
                    success=False,
                    response=(
                        "STOP — do not process the panel. The required simulated "
                        "supervisor escalation could not be completed within the safe "
                        "tool-call limit."
                    ),
                    sources=grounded_sources,
                    trace=trace,
                    escalated=False,
                    model=model,
                    error_code="agent_limit_reached",
                    error_message="Maximum total tool calls exceeded.",
                )
            escalation_result = dispatch_tool(
                "escalate_to_supervisor",
                {
                    "reason": (
                        "Physical panel label conflicts with system information"
                        if _PHYSICAL_MISMATCH_TERMS.search(normalized_request)
                        else "Approved shop-floor information is unavailable or inconsistent"
                    ),
                    "panel_code": normalized_panel_code,
                    "workstation_id": normalized_workstation_id,
                    "context": {
                        "issue": "unresolved_shop_floor_request",
                        "observed": "Available approved information did not resolve the request",
                        "expected": "Grounded production data or SOP guidance",
                    },
                },
                context=execution_context,
            )
            total_tool_calls += 1
            escalation_result, _ = _bounded_tool_result(escalation_result)
            tool_results.append(escalation_result)
            trace.append(_trace_entry(len(trace) + 1, escalation_result))
            if not escalation_result["success"]:
                return _agent_result(
                    success=False,
                    response=(
                        "STOP — do not process the panel. The supervisor escalation "
                        "simulation could not be recorded; notify a supervisor through "
                        "the approved site process."
                    ),
                    sources=grounded_sources,
                    trace=trace,
                    escalated=False,
                    model=model,
                    error_code="escalation_record_failed",
                    error_message="The required escalation event could not be recorded.",
                )
            for source in escalation_result["sources"]:
                if source not in grounded_sources:
                    grounded_sources.append(source)
            escalated = True
            if panel_not_found:
                final_response = (
                    "Panel Not Found. Do not process or invent panel details. "
                    "Supervisor escalation recorded."
                )
            elif _PHYSICAL_MISMATCH_TERMS.search(normalized_request):
                final_response = (
                    "STOP — do not process the panel. Supervisor escalation recorded "
                    "for the unresolved label mismatch."
                )
            elif _UNSUPPORTED_PARAMETER_TERMS.search(normalized_request):
                final_response = (
                    "That machine parameter is unavailable in the approved sources. "
                    "Do not guess. Supervisor escalation recorded."
                )
            else:
                final_response = (
                    "The requested shop-floor guidance is unavailable in the approved "
                    "sources. Stop and follow the supervisor escalation process."
                )
        guard_failure = _apply_safety_gate(
            request=normalized_request,
            response=final_response,
            sources=grounded_sources,
            trace=trace,
            tool_results=tool_results,
            escalated=escalated,
            model=model,
        )
        if guard_failure is not None:
            return guard_failure
        return _agent_result(
            success=True,
            response=final_response,
            sources=grounded_sources,
            trace=trace,
            escalated=escalated,
            model=model,
        )

    return _agent_result(
        success=False,
        response="The agent reached its safe turn limit. Stop and try a narrower request.",
        sources=grounded_sources,
        trace=trace,
        escalated=escalated,
        model=model,
        error_code="agent_limit_reached",
        error_message="Maximum model turns exceeded.",
    )
