# Phase 3 Tool Contracts

## Common result envelope

All five tools return JSON-serializable objects with:

- `tool`: stable tool name
- `input`: normalized tool input
- `success`: execution outcome
- `data`: structured result on success, otherwise `null`
- `sources`: grounded record or SOP references where applicable
- `error`: `null` on success, otherwise a safe `code` and operator-facing `message`

Failures do not expose stack traces or private filesystem paths.

## Read-only tools

- `get_panel(panel_code)` accepts `P-1001` or `P1001` case-insensitively, normalizes either form to canonical `P-1001`, and returns the exact matching JSON panel record and source. It does not perform fuzzy matching beyond this format normalization.
- `get_workstation_requirements(workstation_id)` returns one exact JSON workstation record and a source such as `Workstation EDGE-01`. It does not infer requirements.
- `search_sop(query)` parses level-two SOP headings and returns up to three ranked real sections using exact source-ID lookup, case-insensitive keyword matching, and explicit terminology aliases.

## Local-action tools

- `record_event(event_type, message, panel_code=None, workstation_id=None, metadata=None)` appends one UTF-8 JSON object to `runtime/event_history.jsonl`.
- `escalate_to_supervisor(reason, panel_code=None, workstation_id=None, context=None)` records an escalation event and returns `SOP-ESCALATION-001` as its source.

Supervisor escalation is represented by an assessment event. The tool never invents a supervisor name, contact method, response, or confirmation of personal contact.

## Stable error codes

- `invalid_input`
- `panel_not_found`
- `workstation_not_found`
- `sop_no_match`
- `sop_parse_error`
- `data_source_error`
- `unsupported_event_type`
- `metadata_not_serializable`
- `context_not_serializable`
- `event_write_failed`
- `escalation_record_failed`

## Event history

Supported event types are `scan`, `question`, and `escalation`. Each JSON Lines record contains a unique event ID, UTC timestamp, type, message, optional panel and workstation identifiers, and JSON-serializable metadata. Records are appended in chronological order; reads may return the latest positive number of entries while preserving their order.

The runtime directory and JSON Lines history are local and ignored by Git. Tool execution logs must not contain credentials, prompts, private chain-of-thought, or hidden model reasoning.

## Safety boundaries

Tools return only exact JSON records or real SOP sections. They never invent missing production facts, machine parameters, safety procedures, supervisor details, or retrieval matches. Unknown identifiers, unsupported queries, invalid inputs, and persistence failures return explicit structured failures.
