"""ASGI wrapper used by both Streamlit CLI and Vercel."""

from pathlib import Path

import streamlit as st


app = st.App(str(Path(__file__).resolve().with_name("streamlit_app.py")))
