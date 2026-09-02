"""Vercel ASGI entry point for the Streamlit application."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "EVENT_HISTORY_PATH", "/tmp/shop-floor-ai-agent/event_history.jsonl"
)

app = st.App(str(PROJECT_ROOT / "app.py"))
