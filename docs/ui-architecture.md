# Phase 5 UI Architecture

## Request flow

`Streamlit UI → agent orchestration → OpenAI provider → deterministic tools → JSON / SOP / JSONL history`

`app.py` exports the ASGI wrapper and points it at `streamlit_app.py`. The UI script loads the ignored local `.env` in the server process and calls `src.ui.render_app`. The browser receives only the safe configuration label and configured model name; the API key is never placed in session state or rendered.

## Session state

The UI retains the current grounded panel, latest safe scan result, action context, and up to ten user/assistant exchanges in the current browser session. Workstation or panel-code changes clear stale scan details without silently deleting the conversation. Each user message records the context used for that request, and an explicit Clear chat control resets only the conversation.

Panel entry accepts canonical or compact codes case-insensitively, so `P-1001`, `p-1001`, `P1001`, and `p1001` all become `P-1001` before reaching the agent, tool trace, or event history.

The question area displays the exact panel and workstation context that will be sent to the agent. A default-on checkbox keeps panel questions fast and contextual. Operators can turn it off for a general SOP question; in that mode both identifiers are passed as `None`, so they are not automatically attached to question or escalation events. Native Streamlit chat messages and a single chat input provide the conversation flow without an additional forced rerun.

## Grounded panel display

Panel details are never parsed from model text. After a scan, the UI performs a deterministic `get_panel` lookup only when the agent's computed trace contains a successful `get_panel` call. A failed or unknown scan leaves no panel details to display.

## Safe result rendering

Sources come only from the agent result contract, whose orchestration already derives them from successful deterministic tool results. Scan instructions retain the existing alert design. Question answers appear as normal assistant messages, with grounded sources and a collapsible tool trace attached to the corresponding answer. Trace entries display sequence, tool name, normalized input, success, safe error code, and computed sources. They exclude system instructions, provider payloads, hidden reasoning, raw exceptions, and credentials. Credential-shaped strings and sensitive keys are redacted again at the UI boundary.

## Event history

The local application reads recent events from ignored `runtime/event_history.jsonl`; Vercel uses writable ephemeral `/tmp/shop-floor-ai-agent/event_history.jsonl`. History is available in one collapsed expander after events exist, rather than occupying the main conversation area. A fresh session or missing history renders no placeholder result card. Malformed or unreadable history produces a sanitized warning without paths or raw exceptions. Escalation success uses the neutral label `Supervisor escalation recorded.`

## Test seam

`render_app` accepts explicit agent-runner, panel-lookup, history-reader, environment, and event-history-path dependencies. Production defaults use the real agent and deterministic local functions. Streamlit AppTest passes explicit in-memory fakes through this seam, preventing automated UI tests from calling OpenAI or writing real history.

## Local-demo boundary

This is a single-user, no-auth local assessment demo. It has no database, production machine connection, or real supervisor integration. Final independent five-scenario browser verification remains pending.

## Hosted boundary

Vercel imports the root `app.py`, which exposes `streamlit_app.py` through `st.App` without a catch-all rewrite. The hosted function points event history at `/tmp/shop-floor-ai-agent/event_history.jsonl`. This makes writes possible without committing runtime data, but `/tmp` is ephemeral and history may reset across function instances or deployments. The Vercel deployment is therefore a reviewer demo, not durable production storage.
