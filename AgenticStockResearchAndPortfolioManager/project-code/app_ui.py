"""Streamlit entry point. Run with bin/start_app.sh. The logic is in ui_app.py."""
import streamlit as st

import config
import ui_app

st.set_page_config(page_title=config.APP_NAME, layout="wide", initial_sidebar_state="expanded")
ui_app.render()
