"""Streamlit UI script for the Shop-Floor AI Agent."""

from dotenv import load_dotenv

from src.event_history import runtime_event_history_path
from src.ui import render_app


load_dotenv()
render_app(event_history_path=runtime_event_history_path())
