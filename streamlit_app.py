"""Streamlit UI script for the Shop-Floor AI Agent."""

import os

from dotenv import load_dotenv

from src.ui import render_app


load_dotenv()
render_app(event_history_path=os.environ.get("EVENT_HISTORY_PATH") or None)
