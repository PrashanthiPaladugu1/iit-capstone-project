"""Scratch: render the Admin Guardrails tab with the Streamlit test harness and print what it shows."""
import os, sys, tempfile
os.environ["ARPM_ADMIN_PASSWORD"] = "x"
from pathlib import Path
from streamlit.testing.v1 import AppTest
import ui_app
from model_settings import SettingsStore
from chat_store import ChatStore

tmp = Path(tempfile.mkdtemp())
store = SettingsStore(tmp / "s.sqlite")
store.set_value("guardrails", {"custom": [
    {"id": "C1", "type": "keyword", "text": "No price targets.", "words": ["price target"], "action": "block", "enabled": True},
    {"id": "C2", "type": "prompt", "text": "Always say the data date.", "words": [], "action": "prompt", "enabled": False}], "next": 3})
chats = ChatStore(tmp / "c.sqlite")
ui_app.get_settings = lambda: store
ui_app.get_chats = lambda: chats
ui_app.get_agents = lambda: {}
ui_app.get_gateway = lambda: None
ui_app.usage_rows = lambda limit=200: []
ui_app.answer("What is the price target of TCS?", "s1")

def run_app():
    import ui_app as u
    u.render()


at = AppTest.from_function(run_app, default_timeout=30)
at.run(); at.button(key="open_admin").click().run()
at.text_input(key="admin_pw").set_value("x"); at.button(key="admin_login").click().run()
print("exception:", at.exception)
print("tabs:", [t.label for t in at.tabs])
for df in at.dataframe:
    cols = list(df.value.columns)
    print("\nTABLE", cols, "rows:", len(df.value))
    if "Fired" in cols or "Summary" in cols:
        print(df.value.to_string())
print("\nsubheaders:", [s.value for s in at.subheader])
print("checkboxes:", [(c.key, c.value) for c in at.checkbox])
print("buttons:", [b.key for b in at.button if b.key and b.key.startswith("gr_")])
