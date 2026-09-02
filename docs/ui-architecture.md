# Phase 5 UI Architecture

## Request flow

`Streamlit UI → agent orchestration → OpenAI provider → deterministic tools → JSON / SOP / JSONL history`

`app.py` exports the ASGI wrapper and points it at `streamlit_app.py`. The UI script loads the ignored local `.env` in the server process and calls `src.ui.render_app`. The browser receives only the safe configuration label and configured model name; the API key is never placed in session state or rendered.

## Session state

The UI retains only the current grounded panel, latest safe agent result, action type, and result context. Workstation or panel-code changes clear panel details, response, sources, trace, and escalation state. A new scan clears stale output before calling the agent. Follow-up questions replace only the latest response while preserving the current grounded panel context.

The question area displays the exact panel and workstation context that will be sent to the agent. A default-on checkbox keeps panel questions fast and contextual. Operators can turn it off for a general SOP question; in that mode both identifiers are passed as `None`, so they are not automatically attached to question or escalation events.

## Grounded panel display

Panel details are never parsed from model text. After a scan, the UI performs a deterministic `get_panel` lookup only when the agent's computed trace contains a successful `get_panel` call. A failed or unknown scan leaves no panel details to display.

## Safe result rendering

Sources come only from the agent result contract, whose orchestration already derives them from successful deterministic tool results. The compact trace displays sequence, tool name, normalized input, success, safe error code, and computed sources. It excludes system instructions, provider payloads, hidden reasoning, raw exceptions, and credentials. Credential-shaped strings and sensitive keys are redacted again at the UI boundary.

## Event history

The local application reads recent events from ignored `runtime/event_history.jsonl`; Vercel uses writable ephemeral `/tmp/shop-floor-ai-agent/event_history.jsonl`. A missing file produces a neutral empty state. Malformed or unreadable history produces a sanitized warning without paths or raw exceptions. Escalation success is labeled explicitly as a completed simulation and never claims real contact.

## Test seam

`render_app` accepts explicit agent-runner, panel-lookup, history-reader, environment, and event-history-path dependencies. Production defaults use the real agent and deterministic local functions. Streamlit AppTest passes explicit in-memory fakes through this seam, preventing automated UI tests from calling OpenAI or writing real history.

## Local-demo boundary

This is a single-user, no-auth local assessment demo. It has no database, production machine connection, or real supervisor integration. Final independent five-scenario browser verification remains pending.

## Hosted demo boundary

Vercel imports the root `app.py`, which exposes `streamlit_app.py` through `st.App` without a catch-all rewrite. The hosted function points event history at `/tmp/shop-floor-ai-agent/event_history.jsonl`. This makes writes possible without committing runtime data, but `/tmp` is ephemeral and history may reset across function instances or deployments. The Vercel deployment is therefore a reviewer demo, not durable production storage.
