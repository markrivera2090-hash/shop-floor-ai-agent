# Shop-Floor AI Agent

## Project Overview

A junior AI engineer take-home project for a grounded shop-floor assistant.

## Current Status

Phase 2 – Grounding data and SOP complete.

The repository now contains four fictional panel records, two fictional workstation records, a searchable Markdown SOP, deterministic validation functions, and validation tests. The UI, agent, and LLM integration are not implemented.

## Demo URL

Not available in Phase 2.

## Repository / Source Code

This repository is the source-code workspace.

## LLM Provider

OpenAI is planned; no LLM integration exists yet.

## Agent Implementation Approach

Planned tool/function-calling agent with model-directed tool selection. Not implemented in Phase 2.

## Data Storage Approach

JSON stores structured facts for four fictional panels and two workstations. Markdown stores the SOP for future text retrieval using stable source IDs.

## Approximate Time Spent

To be recorded when the assessment is complete.

## Setup

Python 3.11+ is required. Create a local environment and install the dependencies:

```bash
uv venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
```

## Architecture

The deterministic grounding layer loads and validates JSON production facts and the Markdown SOP independently of Streamlit and OpenAI. The Streamlit UI and model-driven agent remain future work.

## Required Test Results

Phase 2 data-validation tests are implemented. The five final end-to-end assessment scenarios have not been run or marked as passed.

## Brief Technical Questions

To be completed with the final submission.
