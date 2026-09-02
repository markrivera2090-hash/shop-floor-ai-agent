# Shop-Floor AI Agent

## Project Overview

A junior AI engineer take-home project for a grounded shop-floor assistant.

## Current Status

Phase 4 – OpenAI agent orchestration implemented, regression-tested, and live-verified.

The repository now includes OpenAI Responses API orchestration with model-directed function calling, a strict tool dispatcher, multi-round tool execution, grounded source collection, a safe activity trace, and deterministic response safety checks. The Streamlit UI is not implemented.

## Demo URL

Not available in Phase 4.

## Repository / Source Code

This repository is the source-code workspace.

## LLM Provider

OpenAI is the provider integration. The model comes from `OPENAI_MODEL`, and server-side credentials come from `OPENAI_API_KEY`.

The controlled correct-workstation scenario was verified live with `gpt-5.6-sol`. It selected multiple tools, returned the required grounded sources, and did not produce the previously observed false mismatch. Automated tests continue to use injected fakes and never call OpenAI.

## Agent Implementation Approach

The LLM receives all five function definitions and selects tools through automatic function calling. A bounded orchestration loop executes only allowlisted deterministic tools, returns their results to the model, and supports additional tool rounds. Sources and the safe execution trace are computed from actual tool results rather than model-written citations.

## Data Storage Approach

JSON stores structured facts for four fictional panels and two workstations. Markdown stores the SOP for deterministic text retrieval using stable source IDs. Local events are appended as ignored JSON Lines in `runtime/event_history.jsonl`.

## Approximate Time Spent

To be recorded when the assessment is complete.

## Setup

Python 3.11+ is required. Create a local environment and install the dependencies:

```bash
uv venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
```

## Architecture

The OpenAI provider adapter is separated from orchestration and the strict dispatcher. Deterministic tools remain the only source of panel facts, workstation facts, SOP content, and local actions. Supervisor escalation is simulated and does not contact a real person. Automated provider tests use injected fakes and never spend API credits. The Streamlit UI remains future work.

## Required Test Results

Phase 2 validation, Phase 3 tool contracts, and 167 Phase 4 mocked provider/orchestration regression tests pass. The controlled correct-workstation API scenario also passes. The five final end-to-end UI assessment scenarios have not been run or marked as passed.

## Brief Technical Questions

To be completed with the final submission.
