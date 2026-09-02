# Phase 4 Agent Architecture

## Execution flow

The orchestration follows:

`Input → Model decision → Tool dispatch → Tool result → Next decision → Response or action`

The operator request and current panel/workstation identifiers are passed as untrusted context. The model receives all five function definitions and chooses whether to call tools; facts are not prefetched into the prompt. Tool results are returned through Responses API continuation, allowing multiple decision rounds before final text.

## Provider boundary

`src/openai_provider.py` contains all OpenAI-specific behavior. It uses the installed OpenAI Python SDK Responses API, supports injected fake clients, applies bounded timeouts and output tokens, and permits at most one retry for transient failures. Credentials and the model name come only from `OPENAI_API_KEY` and `OPENAI_MODEL` or explicit server-side configuration.

## Tool allowlist

`src/tool_registry.py` exposes strict schemas and dispatches only:

- `get_panel`
- `get_workstation_requirements`
- `search_sop`
- `record_event`
- `escalate_to_supervisor`

Unknown names, malformed JSON, non-object arguments, unexpected properties, and missing required arguments produce safe structured failures. The model cannot supply a filesystem path; tests inject temporary event-history paths through a trusted execution context.

## Grounding and trace

Displayed sources are collected only from successful deterministic tool results. Model-written citations are not trusted. The activity trace records call order, tool name, normalized input, success or failure, safe errors, and grounded sources.

The trace is an execution audit, not private chain-of-thought. It excludes model reasoning, system prompts, provider metadata, raw exceptions, stack traces, and credentials.

## Safety and limits

The loop bounds model turns, total tool calls, and serialized tool-result size. Duplicate calls are not executed twice. Provider, dispatcher, configuration, and limit failures return sanitized errors while preserving any completed safe trace and sources.

A deterministic response gate blocks ungrounded production guidance, numeric answers to unsupported machine-parameter questions, permission to proceed at a wrong workstation, invented unknown-panel details, and claims that simulated escalation contacted a real person. Workstation compatibility is determined from successful structured panel and workstation results by comparing both the required workstation ID and operation; an incidental mismatch SOP search result is not treated as proof of a mismatch. A directly reported physical-label discrepancy remains a stop condition when grounded by mismatch guidance or a simulated escalation.

SOP retrieval gives strong weight to explicit intent aliases and title terms, removes generic verification words, requires a minimum relevance score, and retains only closely scored secondary sections. Edge Banding and Drilling are mutually exclusive search intents, while mismatch, unsupported-parameter, and escalation sections require matching issue language.

Supervisor escalation remains simulated and records only a local assessment event.

## Verification boundary

Automated tests use injected fake providers and clients; they do not call OpenAI, read a real API key, spend credits, or write the real runtime event history. A controlled live `gpt-5.6-sol` correct-workstation check passed with temporary event history after the false-mismatch regression was corrected.

The Streamlit UI is not implemented in Phase 4.
