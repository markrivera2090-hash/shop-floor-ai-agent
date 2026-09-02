# Shop-Floor AI Agent

## Project Overview

A junior AI engineer take-home project for a grounded shop-floor assistant.

## Current Status

Phase 5 – Streamlit application implemented, deployed, and automated-test verified

The repository includes a Streamlit operator UI over the grounded OpenAI agent. It supports workstation selection, panel scans, deterministic panel details, contextual or general follow-up questions, grounded sources, a safe tool trace, local or ephemeral hosted event history, and explicitly simulated escalation. The production page and core controls have been browser-verified; final independent end-to-end browser verification of all five scenarios remains pending.

## Demo URL

Production demo: [shop-floor-ai-agent-nu.vercel.app](https://shop-floor-ai-agent-nu.vercel.app)

The hosted application uses temporary event history that may reset between requests. For persistent local history, run the app locally at the loopback URL printed by Streamlit, normally `http://localhost:8501`.

## Repository / Source Code

This repository is the source-code workspace.

## LLM Provider

OpenAI is the provider integration. The model comes from `OPENAI_MODEL`, and server-side credentials come from `OPENAI_API_KEY`.

The controlled correct-workstation scenario was verified live with `gpt-5.6-sol`. It selected multiple tools, returned the required grounded sources, and did not produce a false mismatch. Automated backend and UI tests use injected fakes and never call OpenAI.

## Agent Implementation Approach

The LLM receives all five function definitions and selects tools through automatic function calling. It first distinguishes shop-floor requests from unrelated questions. Relevant requests use grounded tools; when approved data cannot resolve a relevant request, a deterministic safety backstop records the required escalation. Unrelated requests receive a concise scope response without tools, history, or escalation. A bounded orchestration loop executes only allowlisted deterministic tools, returns their results to the model, and supports additional tool rounds. Sources and the safe execution trace are computed from actual tool results rather than model-written citations. The UI has an explicit dependency-injection seam so tests can supply in-memory runners without activating the production provider.

## Data Storage Approach

JSON stores structured facts for four fictional panels and two workstations. Markdown stores the SOP for deterministic text retrieval using stable source IDs. Local scan, question, and simulated-escalation events are appended as ignored JSON Lines in `runtime/event_history.jsonl`. Panel details shown in the UI come from deterministic `get_panel` output, not model text.

## Approximate Time Spent

To be recorded when the assessment is complete.

## Setup

Python 3.11+ is required. Create a local environment and install the dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Set these server-side values in the ignored `.env` file:

```dotenv
OPENAI_API_KEY=your-local-key
OPENAI_MODEL=gpt-5.6-sol
```

Run the local app:

```bash
.venv/bin/streamlit run app.py
```

If configuration is missing, the UI still loads and reports `AI configuration unavailable` without exposing environment contents.

## Architecture

Streamlit calls the bounded agent, which calls the OpenAI provider and allowlisted deterministic tools over local JSON, Markdown, and ignored JSONL history. Session callbacks clear stale results after panel or workstation changes. Sources, trace fields, errors, and events are sanitized before display. Supervisor escalation is represented by a recorded assessment event.

This is a no-auth, single-user local assessment demo. It is not connected to production machines, a production database, or a real supervisor channel. See `docs/agent-architecture.md` and `docs/ui-architecture.md` for the detailed boundaries.

`app.py` exports a Streamlit ASGI application around `streamlit_app.py`, allowing both the local Streamlit CLI and Vercel to use the same UI. Because Vercel's writable `/tmp` filesystem is ephemeral, hosted event history may reset between function instances or deployments; local execution continues to use ignored `runtime/event_history.jsonl`.

## Required Test Results

The complete automated suite is run with:

```bash
.venv/bin/python -m pytest
```

The complete suite passes 208 tests with 0 failures, including 27 injected Streamlit AppTest scenarios. Syntax checks and local Streamlit/ASGI page-load smoke checks also pass. Controlled live API checks cover the correct-workstation and supervisor-escalation scenarios. The production page and core controls load successfully; final independent end-to-end browser verification of all five scenarios has not been marked as complete.

## Brief Technical Questions

To be completed with the final submission.
