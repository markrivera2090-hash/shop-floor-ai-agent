# Shop-Floor AI Agent

- **Demo URL:** [shop-floor-ai-agent-nu.vercel.app](https://shop-floor-ai-agent-nu.vercel.app)
- **Repository / source code:** [github.com/markrivera2090-hash/shop-floor-ai-agent](https://github.com/markrivera2090-hash/shop-floor-ai-agent)
- **LLM provider:** OpenAI (`gpt-5.6-sol`, configurable through `OPENAI_MODEL`)
- **Agent implementation approach:** Bounded OpenAI function-calling loop with five allowlisted tools, grounded sources, and deterministic safety checks
- **Data storage approach:** JSON production facts, Markdown SOP content, and ignored JSONL event history
- **Approximate time spent:** 10 hours, including implementation, testing, documentation, and deployment

## Project Overview

Shop-Floor AI Agent is a grounded assistant for two fictional manufacturing workstations: Edge Banding and Drilling. Operators can select a workstation, scan a panel, review approved production facts, use a normal conversational chat for contextual or general SOP questions, inspect each answer's tool trace, and review recorded events.

## Current Status

Phase 5 – application implemented, tested, and deployed.

The repository contains four fictional panels, two workstation definitions, a Markdown SOP, the Streamlit application, the OpenAI tool-calling agent, automated tests, and supporting architecture documentation.

## Setup

Python 3.11 or newer is required.

```bash
git clone https://github.com/markrivera2090-hash/shop-floor-ai-agent.git
cd shop-floor-ai-agent
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Add your server-side configuration to the ignored `.env` file:

```dotenv
OPENAI_API_KEY=your-local-key
OPENAI_MODEL=gpt-5.6-sol
```

Run the application:

```bash
.venv/bin/streamlit run app.py
```

Streamlit normally prints a local URL such as `http://localhost:8501`. If AI configuration is missing, the interface remains available and reports a configuration error without exposing environment values.

Run the automated tests:

```bash
.venv/bin/python -m pytest
```

## Architecture

The Streamlit UI sends the operator's question and optional selected-panel/workstation context to a bounded agent loop. The OpenAI model decides which declared tool to call, receives deterministic tool results, and may make additional tool calls before responding.

The five allowlisted tools read panel and workstation facts from JSON, search the approved Markdown SOP, and record operational or escalation events. Sources and the visible tool trace are derived from actual tool execution rather than model-written citations. Deterministic checks prevent unsupported production answers and ensure that relevant unresolved issues are escalated, while clearly unrelated questions are declined without recording an escalation.

Panel input is case-insensitive and accepts either `P-1001` or `P1001`, normalizing both to the canonical `P-1001` format. Local event history is stored in the ignored `runtime/event_history.jsonl`; hosted event history uses ephemeral storage and may reset between deployments or function instances.

The same application code runs locally and on Vercel. Additional design details are available in [`docs/agent-architecture.md`](docs/agent-architecture.md), [`docs/tool-contracts.md`](docs/tool-contracts.md), and [`docs/ui-architecture.md`](docs/ui-architecture.md).

## Required Test Results

- ☑ Correct Workstation
- ☑ Wrong Workstation
- ☑ Unsupported Question / No Hallucination
- ☑ Unknown Panel
- ☑ Supervisor Escalation

The automated suite currently passes **211 tests with 0 failures**, including **29 Streamlit AppTest scenarios**. It also covers tool selection, multi-tool workflows, conversational follow-ups, irrelevant-question handling, panel-code normalization, safe failures, source attribution, event recording, and non-duplicated escalation messaging.

## Brief Technical Questions

### 1. How does the agent decide which tool to call?

The model receives the user's request, optional UI context, the conversation state, and JSON schemas for all available tools. It chooses tools with OpenAI automatic function calling. The application validates every requested call against an allowlist, executes it, returns the result to the model, and permits another decision round instead of enforcing one fixed sequence.

### 2. What tools are available to the agent?

- `get_panel(panel_code)` retrieves structured panel facts.
- `get_workstation_requirements(workstation_id)` retrieves workstation capabilities and requirements.
- `search_sop(query)` finds relevant approved SOP passages.
- `record_event(...)` records an operational event.
- `escalate_to_supervisor(...)` records an escalation when a relevant issue cannot be resolved safely from approved information.

### 3. What information comes from structured data rather than the LLM?

Panel identity, dimensions, material, required workstation, edge requirements, drilling requirements, workstation capabilities, and workstation constraints come from JSON. Approved procedures come from the Markdown SOP. Event records, sources, and tool traces come from application code and executed tool results. The LLM interprets the question and composes the response; it is not the source of production facts.

### 4. How do you prevent unsupported or invented answers?

The system prompt forbids invented production facts, settings, speeds, tooling parameters, and safety procedures. Answers must be grounded through the declared tools. Deterministic safety checks reject unsupported values, attach sources from actual results, and record an escalation when an in-scope question cannot be resolved from approved data. Out-of-scope questions receive a concise scope response without tools or escalation.

### 5. What happens when a tool or LLM call fails?

Tool inputs are validated and failures are returned as structured, sanitized errors. The orchestration loop is bounded to prevent runaway calls. The UI shows a safe error message without credentials or internal details. For an unresolved shop-floor request, the agent provides a safe next step and records an escalation when appropriate; a provider failure does not produce a guessed answer.

### 6. If you had one more day, what would you improve first and why?

I would add persistent hosted event storage with authenticated access and request-level observability. Vercel's temporary filesystem can reset, so durable storage would make event history reliable across instances and deployments while better telemetry would make tool and provider failures easier to investigate.
