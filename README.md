# Shop-Floor AI Agent

## Project Overview

A junior AI engineer take-home project for a grounded shop-floor assistant.

## Current Status

Phase 3 – Deterministic tools and event history complete.

The repository now contains four fictional panel records, two fictional workstation records, a searchable Markdown SOP, deterministic validation, five logical tools, and local event history. The Streamlit UI, LLM integration, and agent orchestration are not implemented.

## Demo URL

Not available in Phase 3.

## Repository / Source Code

This repository is the source-code workspace.

## LLM Provider

OpenAI is planned; no LLM integration exists yet.

## Agent Implementation Approach

The five deterministic tools are `get_panel`, `get_workstation_requirements`, `search_sop`, `record_event`, and `escalate_to_supervisor`. Results contain normalized inputs, success or failure, grounded sources, structured data, and safe errors. Model-directed tool selection and agent orchestration are not implemented.

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

The deterministic grounding layer loads and validates JSON production facts and the Markdown SOP independently of Streamlit and OpenAI. Read-only tools retrieve those sources, while local-action tools append event history. Supervisor escalation is simulated for the assessment and does not contact a real person. The Streamlit UI, LLM integration, and agent orchestration remain future work.

## Required Test Results

Phase 2 data-validation and Phase 3 tool-contract tests are implemented. The five final end-to-end assessment scenarios have not been run or marked as passed.

## Brief Technical Questions

To be completed with the final submission.
