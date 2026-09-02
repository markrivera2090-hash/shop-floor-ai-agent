"""Streamlit entry point for the Shop-Floor AI Agent local demo."""

import os

from dotenv import load_dotenv

from src.ui import render_app


load_dotenv()
render_app(event_history_path=os.environ.get("EVENT_HISTORY_PATH") or None)
